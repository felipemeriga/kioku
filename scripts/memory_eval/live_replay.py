"""Replay sealed, read-only real-history queries through the installed Kioku CLI.

This caller never opens gold annotations. Output includes private signed evidence
references and source excerpts, so it is exclusively created with mode 0600.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

FLAGS = {
    "folder": "--folder",
    "from_date": "--from",
    "through_date": "--through",
    "as_of": "--as-of",
    "timezone": "--timezone",
    "session": "--session",
}
ERRORS = (
    "evidence_query_timeout",
    "evidence_database_unavailable",
    "evidence_database_busy",
    "scope_too_broad",
    "invalid_overview_arguments",
)
CONFIG_ERRORS = {
    "inside a repository connected with kioku init": "unconfigured_repository",
    "No valid Kioku connection in .mcp.json": "invalid_repository_binding",
    "unknown option": "unsupported_cli_option",
}


def invoke(arguments, timeout):
    started = time.perf_counter()
    try:
        process = subprocess.run(
            ["kioku", *arguments], capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        return {
            "status": "client_timeout",
            "ms": (time.perf_counter() - started) * 1000,
        }
    elapsed = (time.perf_counter() - started) * 1000
    diagnostics = process.stdout + "\n" + process.stderr
    try:
        result = json.loads(process.stdout)
    except ValueError:
        result = None
    success = (
        process.returncode == 0
        and isinstance(result, dict)
        and result.get("status") == "ok"
    )
    configuration_error = None
    error_code = None
    if not success:
        configuration_error = next(
            (code for message, code in CONFIG_ERRORS.items() if message in diagnostics),
            None,
        )
        detail = result.get("detail") if isinstance(result, dict) else None
        structured = result.get("code") if isinstance(result, dict) else None
        if isinstance(detail, dict):
            structured = structured or detail.get("code")
        rendered = re.search(r"\bKioku: ([a-z][a-z0-9_]{0,100})\b", diagnostics)
        error_code = configuration_error
        if (
            not error_code
            and isinstance(structured, str)
            and re.fullmatch(r"[a-z][a-z0-9_]{0,100}", structured)
        ):
            error_code = structured
        error_code = error_code or (rendered[1] if rendered else None)
        error_code = error_code or next(
            (code for code in ERRORS if code in diagnostics), None
        )
    return {
        "status": "ok" if success else "cli_error",
        "process_exit": process.returncode,
        "ms": elapsed,
        "stdout_bytes": len(process.stdout.encode()),
        "stderr_bytes": len(process.stderr.encode()),
        "error_code": error_code,
        "local_configuration_error": configuration_error is not None,
        "result": result if success else None,
    }


def trial_metrics(search, reads):
    result = search["result"] if search["status"] == "ok" else {}
    matches = (
        [] if result.get("originals_searched") is False else result.get("matches", [])
    )
    deferred = sum(match.get("requires_evidence_read") is True for match in matches)
    return {
        "journal_hints": len(result.get("journal_hints", [])),
        "originals_searched": result.get("originals_searched", True)
        if result
        else None,
        "original_excerpts": sum(
            bool(match.get("excerpt"))
            and match.get("requires_evidence_read") is not True
            for match in matches
        ),
        "deferred_locators": deferred,
        "original_fallback": bool(result.get("strategy_fallback")),
        "signed_reads_attempted": len(reads),
        "signed_reads_succeeded": sum(
            read["status"] == "ok" and bool(read["result"].get("evidence"))
            for read in reads
        ),
    }


def cutoff_metrics(search, reads, cutoff):
    result = search["result"] if search["status"] == "ok" else {}
    timestamps = [match.get("recorded_at") for match in result.get("matches", [])]
    for hint in result.get("journal_hints", []):
        timestamps.extend((hint.get("captured_at"), hint.get("synced_at")))
    for read in reads:
        if read["status"] == "ok":
            timestamps.extend(
                row.get("recorded_at") for row in read["result"].get("evidence", [])
            )

    violations = unverifiable = 0
    for stamp in timestamps:
        try:
            recorded_at = datetime.fromisoformat(stamp)
        except (TypeError, ValueError):
            unverifiable += 1
            continue
        if recorded_at.utcoffset() is None:
            unverifiable += 1
        elif recorded_at > cutoff:
            violations += 1
    return {"cutoff_violations": violations, "cutoff_unverifiable": unverifiable}


def run(
    manifest_path,
    expected_hash,
    output,
    timeout,
    cutoff_ceiling,
    *,
    strategy="original",
    evidence_mode="hydrate",
):
    raw = manifest_path.read_bytes()
    actual_hash = hashlib.sha256(raw).hexdigest()
    if actual_hash != expected_hash:
        raise ValueError("The sealed real-question manifest changed")
    manifest = json.loads(raw)
    queries = manifest["queries"]
    if not isinstance(queries, list) or not queries:
        raise ValueError("The manifest must contain a nonempty query list")
    ceiling = datetime.fromisoformat(cutoff_ceiling)
    if ceiling.tzinfo is None:
        raise ValueError("The contamination cutoff ceiling must be offset-aware")
    if any(
        not isinstance(q["case_id"], str)
        or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", q["case_id"])
        for q in queries
    ):
        raise ValueError("Case IDs must be short alphanumeric labels")
    if len({q["case_id"] for q in queries}) != len(queries):
        raise ValueError("The manifest repeats case IDs")
    for query in queries:
        if (
            not isinstance(query["question"], str)
            or not query["question"].strip()
            or not query["filters"].get("as_of")
            or not str(query["filters"].get("folder") or "").strip()
        ):
            raise ValueError("Real-history queries need explicit scope and cutoffs")
        cutoff = datetime.fromisoformat(query["filters"]["as_of"])
        if cutoff.tzinfo is None or cutoff > ceiling:
            raise ValueError(
                "A query exceeds the declared contamination cutoff ceiling"
            )
        if set(query["filters"]) - set(FLAGS):
            raise ValueError("Unexpected live query filters")
    fd = os.open(output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w", buffering=1) as stream:

        def write(value):
            stream.write(json.dumps(value, ensure_ascii=False) + "\n")

        write(
            {
                "record_type": "run",
                "started_at": datetime.now(timezone.utc).isoformat(),
                "cli_repository_cwd": str(Path.cwd()),
                "query_sha256": actual_hash,
                "expected_cases": len(queries),
                "boundary": "installed CLI, fresh public MCP transport, live archive",
                "policy": {
                    "order": "relevance",
                    "strategy": strategy,
                    "evidence_mode": evidence_mode,
                    "limit": 10,
                    "reads": 2,
                    "read_selection": "distinct discovery excerpts",
                    "before_records": 1,
                    "after_records": 1,
                    "char_limit": 4000,
                    "process_timeout_seconds": timeout,
                    "cutoff_ceiling": cutoff_ceiling,
                },
            }
        )
        for query in queries:
            args = [
                "history",
                "--order",
                "relevance",
                "--limit",
                "10",
                "--strategy",
                strategy,
                "--evidence-mode",
                evidence_mode,
            ]
            for field, flag in FLAGS.items():
                if query["filters"].get(field):
                    args.extend([flag, str(query["filters"][field])])
            search = invoke([*args, "--", query["question"]], timeout)
            selected = set()
            reads = []
            result = search["result"] if search["status"] == "ok" else {}
            matches = (
                []
                if result.get("originals_searched") is False
                else result.get("matches", [])
            )
            for match in matches:
                reference = match.get("reference")
                if not reference:
                    continue
                key = (match.get("excerpt") or reference).strip()
                if key in selected:
                    continue
                selected.add(key)
                reads.append(
                    invoke(
                        [
                            "evidence",
                            "--before",
                            "1",
                            "--after",
                            "1",
                            "--chars",
                            "4000",
                            "--",
                            reference,
                        ],
                        timeout,
                    )
                )
                if len(reads) == 2:
                    break
            metrics = trial_metrics(search, reads)
            metrics.update(
                cutoff_metrics(
                    search, reads, datetime.fromisoformat(query["filters"]["as_of"])
                )
            )
            write(
                {
                    "record_type": "trial",
                    "case_id": query["case_id"],
                    "search": search,
                    "reads": reads,
                    "metrics": metrics,
                }
            )
            print(
                json.dumps(
                    {
                        "case_id": query["case_id"],
                        "status": search["status"],
                        "search_ms": round(search["ms"]),
                        **metrics,
                    }
                ),
                flush=True,
            )
        write({"record_type": "completion", "cases": len(queries)})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queries", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=45)
    parser.add_argument("--cutoff-ceiling", required=True)
    parser.add_argument(
        "--strategy", choices=("original", "journal-guided"), default="original"
    )
    parser.add_argument(
        "--evidence-mode", choices=("hydrate", "cached-preview"), default="hydrate"
    )
    arguments = parser.parse_args()
    if not 1 <= arguments.timeout_seconds <= 120:
        parser.error("Timeout must be between 1 and 120 seconds")
    run(
        arguments.queries,
        arguments.sha256,
        arguments.output,
        arguments.timeout_seconds,
        arguments.cutoff_ceiling,
        strategy=arguments.strategy,
        evidence_mode=arguments.evidence_mode,
    )


if __name__ == "__main__":
    main()
