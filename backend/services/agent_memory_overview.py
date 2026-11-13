"""One snapshot of dated reports and original activity, without loading raw objects."""

import re
from collections import defaultdict
from zoneinfo import ZoneInfo

from dateutil.parser import isoparse

from services.agent_evidence import rpc
from services.agent_memory import journal_activity
from services.period_reports import report_context


def overview(sb, user_id, folders, after, before, tz, session):
    scope = {f["id"]: f["name"] for f in folders}
    snapshot = rpc(
        sb,
        "agent_memory_overview",
        {
            "p_user_id": user_id,
            "p_folder_ids": list(scope),
            "p_after": after,
            "p_before": before,
            "p_session": session,
            "p_timezone": tz,
        },
    )
    rows = snapshot["entries"]
    days = journal_activity(
        sb, user_id, list(scope), after, before, tz, limit=2000, session=session, rows=rows
    )["days"]
    entries = defaultdict(list)
    for row in rows[:2000]:
        day = isoparse(row["captured_at"]).astimezone(ZoneInfo(tz)).date().isoformat()
        entries[row["folder_id"], row["session_id"], day].append(row)
    for day in days:
        reports = sorted(
            entries[day["folder_id"], day["session_id"], day["date"]],
            key=lambda e: (e["captured_at"], e["entry_id"]),
        )
        # Include every dated entry, including late corrections. These are exact
        # compact prefixes, never a fabricated synthesis or a cumulative title.
        lines = []
        for report in reports:
            body = re.sub(r"\s+", " ", report.get("body") or "").strip()
            prefix = body[:180]
            lines.append(f"{report['captured_at']}: {prefix}" + (" …" if len(body) > 180 else ""))
        day["summary"] = "\n".join(lines)
        day["summary_truncated"] = any(
            len(re.sub(r"\s+", " ", r["body"]).strip()) > 180 for r in reports
        )
        day["repository"] = scope[day["folder_id"]]
        day.pop("interpretation", None)
    original = snapshot["original_days"][:2000]
    for day in original:
        day["repository"] = scope[day["folder_id"]]
    pending = snapshot["index_pending_objects"]
    within_limit = snapshot["entry_count"] <= 2000 and snapshot["original_day_count"] <= 2000
    complete = within_limit and pending == 0
    return {
        "status": "ok",
        "projection": "overview",
        "period_reports": report_context(sb, user_id, list(scope), after, before, tz, session),
        "matches": [],
        "scope": [{"id": k, "name": v} for k, v in scope.items()],
        "time_scope": {"after": after, "before_exclusive": before, "timezone": tz},
        "snapshot_at": snapshot["snapshot_at"],
        "activity": {"days": days, "has_more": False, "entry_count": snapshot["entry_count"]},
        "original_activity": original,
        "inventory_complete": complete,
        "index_pending_objects": pending,
        "content_truncated": any(d["summary_truncated"] for d in days),
        "coverage": (
            "complete_activity_inventory"
            if complete
            else "original_index_pending"
            if within_limit
            else "inventory_limit_reached_narrow_dates"
        ),
        "interpretation": (
            "Every returned dated journal entry has a compact report prefix, "
            "in chronological order, "
            "including later updates. These are reported work, not proof of deployment. Titles can "
            "describe cumulative sessions. Original activity includes sessions without journals, "
            "but its counts alone do not establish what happened. Answer a concise overview from "
            "these reports; expand signed day references only for specifically needed detail. "
            "inventory_complete describes day coverage, not full report text "
            "or uncaptured activity."
        ),
    }
