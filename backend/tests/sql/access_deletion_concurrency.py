"""Disposable PostgreSQL fixture: a reserved write must block a deletion snapshot."""

import json
import os
import subprocess
import time

PSQL = json.loads(
    os.getenv(
        "KIOKU_SQL_PSQL_COMMAND",
        '["psql","-h","localhost","-U","postgres","-d","root_access_fixture","-v","ON_ERROR_STOP=1","-qAt"]',
    )
)
OWNER = "10000000-0000-4000-8000-000000000001"
ROOT = "20000000-0000-4000-8000-000000000001"
RESOURCE = "30000000-0000-4000-8000-000000000021"
CREDENTIAL = "80000000-0000-4000-8000-000000000021"
OP = "90000000-0000-4000-8000-000000000021"


def query(sql, check=True):
    return subprocess.run(PSQL, input=sql, capture_output=True, text=True, timeout=15, check=check)


query(f"""
insert into access_resources(id,user_id,root_folder_id,name,type,shared)
values('{RESOURCE}','{OWNER}','{ROOT}','concurrency fixture','other',true);
insert into access_credentials(id,user_id,root_folder_id,resource_id,kind,fields)
values('{CREDENTIAL}','{OWNER}','{ROOT}','{RESOURCE}','uri','["connection"]');
""")
writer = subprocess.Popen(
    PSQL, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
)
writer.stdin.write(f"""BEGIN; SET LOCAL application_name='kioku-delete-writer';
select reserve_credential_write('{OP}','{OWNER}','{ROOT}','{CREDENTIAL}',
1,'race-synthetic-only','synthetic-hmac',null,null);
select pg_sleep(3); COMMIT;
""")
writer.stdin.close()
try:
    for _ in range(60):
        ready = query(
            "select count(*) from pg_stat_activity "
            "where application_name='kioku-delete-writer' and wait_event='PgSleep';"
        ).stdout.strip()
        if ready == "1":
            break
        if writer.poll() is not None:
            raise AssertionError("Writer exited before holding its reservation")
        time.sleep(0.05)
    else:
        raise AssertionError("Writer did not reach its reserved transaction")
    deletion = query(
        f"select begin_access_resource_deletion('{OWNER}','{ROOT}','{RESOURCE}');", check=False
    )
    assert deletion.returncode != 0 and "resource_busy" in deletion.stderr, (
        "Deletion raced ahead of an uncommitted reservation"
    )
    assert writer.wait(timeout=10) == 0
    assert (
        query(
            f"select deletion_requested_at is null from access_resources where id='{RESOURCE}';"
        ).stdout.strip()
        == "t"
    )
    query(
        f"select cancel_credential_write('{OP}','{OWNER}'); "
        f"delete from access_resources where id='{RESOURCE}';"
    )
    print("Concurrent credential reservation/deletion serialization passed")
finally:
    if writer.poll() is None:
        writer.kill()
        writer.wait()
