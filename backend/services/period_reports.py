"""Repository period reports: explicit calendar boundaries and bounded source evidence."""

import hashlib
import json
import re
from calendar import monthrange
from copy import deepcopy
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, TypeAdapter

TIMESTAMP = TypeAdapter(AwareDatetime)

POLICY = 2
REPORT_SHAPE = {
    "title": "",
    "summary": "",
    "summary_source_ids": [""],
    "sections": [
        {"heading": "", "items": [{"text": "", "source_ids": [""], "evidence_quote": ""}]}
    ],
}
REPORT_GUIDE = (
    "Write a useful dated repository review, not a concatenation of session summaries. "
    "Weekly: progress/outcomes, decisions, still open. Monthly: how work evolved across weeks, "
    "recurring themes, corrections and carryover. Use only supplied sources and exact source IDs. "
    "Every summary and item must cite supporting sources. For evidence_quote select the ID "
    "of a supplied exact excerpt belonging to a cited source, rather than rewriting its text. "
    "Journal claims are reported work, never independently verified. Commands are not results. "
    "A principal-branch commit confirms code presence, not deployment or runtime success. "
    "PR states require supplied GitHub metadata; otherwise say unavailable. Distinguish dates of "
    "observations from dates of incidents. Preserve contradictions and unresolved results. "
    "Reconcile each topic chronologically using observed_at, including within the same day. "
    "Lead with its latest supported state at the cutoff. If a later source reverts, corrects, "
    "or supersedes earlier work, explicitly describe that reversal and cite both sources. "
    "Do not list superseded proposals or resolved issues as current open work. A newer journal "
    "claim does not override stronger Git or runtime evidence without support; "
    "qualify uncertainty. "
    "A prior weekly report is orientation, not independent evidence; cite its underlying sources. "
    "Source coverage is bounded: never claim complete verification or invent missing activity. "
    "Prefer three to five substantive findings; do not repeat the same fact across sections. "
    "Do not invent hypothetical risks or future experiments absent from the sources. "
    "Do not manufacture contradictions between differently scoped measurements or metrics. "
    "Unavailable integrations are coverage limits, not newly invented work items. "
    "Keep prose concise and useful, with no generic recommendations. Maximum six sections, "
    "eight items each, summary 1200 characters, each item 1000 characters."
)


def calendar_period(kind, anchor):
    if kind == "weekly":
        start = anchor - timedelta(days=anchor.weekday())
        return start, start + timedelta(days=6)
    if kind == "monthly":
        return anchor.replace(day=1), anchor.replace(day=monthrange(anchor.year, anchor.month)[1])
    raise ValueError("Invalid report kind")


def instants(start, end, tz):
    zone = ZoneInfo(tz)
    return (
        datetime.combine(start, time.min, zone).astimezone(timezone.utc),
        datetime.combine(end + timedelta(days=1), time.min, zone).astimezone(timezone.utc),
    )


def iso(value):
    # PostgREST trims trailing fractional zeros; Python 3.10's parser only
    # accepts three or six digits. Validate RFC3339 independently of runtime.
    return TIMESTAMP.validate_python(value)


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def report_rows(sb, owner, folder, kind, tz, limit=16):
    return (
        sb.table("repo_period_reports")
        .select("id,period_start,period_end,revision,source_digest,generated_at,content,coverage")
        .eq("user_id", owner)
        .eq("folder_id", folder)
        .eq("kind", kind)
        .eq("timezone", tz)
        .order("period_start", desc=True)
        .limit(limit)
        .execute()
        .data
        or []
    )


def capture_report(sb, owner, folder, payload, now=None):
    """Choose one due period. Preparation never mutates the last good report."""
    now = now or datetime.now(timezone.utc)
    tz = payload.get("timezone", "UTC")
    today = now.astimezone(ZoneInfo(tz)).date()
    candidates = []
    # Fast first result, then current month and last completed periods, then backfill.
    for kind, anchor in [
        ("weekly", today),
        ("monthly", today),
        ("weekly", today - timedelta(days=7)),
        ("monthly", today.replace(day=1) - timedelta(days=1)),
    ]:
        candidates.append((kind, *calendar_period(kind, anchor)))
    for n in range(2, 9):
        candidates.append(("weekly", *calendar_period("weekly", today - timedelta(weeks=n))))
    stored = {
        kind: {r["period_start"]: r for r in report_rows(sb, owner, folder, kind, tz)}
        for kind in ("weekly", "monthly")
    }
    for kind, start, end in candidates:
        old = stored[kind].get(start.isoformat())
        closed = today > end
        if old and not closed and old.get("coverage", {}).get("policy") == POLICY:
            generated = iso(old["generated_at"]).astimezone(ZoneInfo(tz)).date()
            if kind == "weekly" and generated == today:
                continue
            if (
                kind == "monthly"
                and calendar_period("weekly", generated)[0] == calendar_period("weekly", today)[0]
            ):
                continue
        after, before = instants(start, end, tz)
        cutoff = min(now, before)
        snapshot = (
            sb.rpc(
                "period_report_sources",
                {
                    "p_user": owner,
                    "p_folder": folder,
                    "p_after": after.isoformat(),
                    "p_before": cutoff.isoformat(),
                    "p_timezone": tz,
                },
            )
            .execute()
            .data
        )
        entries = snapshot.get("entries", [])
        events = snapshot.get("events", [])
        commits = [c for c in payload.get("commits", []) if after <= iso(c["at"]) < cutoff]
        pulls = [p for p in payload.get("pull_requests", []) if after <= iso(p["at"]) < cutoff]
        if not entries and not events and not commits and not pulls:
            continue
        fingerprint = digest(
            {
                "policy": POLICY,
                "kind": kind,
                "start": start.isoformat(),
                "timezone": tz,
                "closed": closed,
                "snapshot": snapshot,
                "commits": commits,
                "pulls": pulls,
                "github_coverage": payload.get("github_coverage", "unavailable"),
            }
        )
        if old and old["source_digest"] == fingerprint:
            continue
        if not closed:
            stamps = [iso(row["captured_at"]) for row in entries]
            stamps += [iso(row["event_at"]) for row in events]
            stamps += [iso(row["at"]) for row in [*commits, *pulls]]
            cutoff = min(now, max(stamps) + timedelta(microseconds=1))
        # Retain a chronological spread rather than silently dropping the last days.
        journal_total = len(entries)
        if len(entries) > 80:
            entries = [entries[round(i * (len(entries) - 1) / 79)] for i in range(80)]
        commit_total, pull_total = len(commits), len(pulls)
        commits, pulls = commits[:150], pulls[:100]
        sources = []
        for row in entries:
            sources.append(
                {
                    "id": "journal:" + row["entry_id"],
                    "kind": "journal",
                    "date": iso(row["captured_at"]).astimezone(ZoneInfo(tz)).date().isoformat(),
                    "observed_at": iso(row["captured_at"]).isoformat(),
                    "session_id": row["session_id"],
                    "agent": row["agent"],
                    "entry_id": row["entry_id"],
                    "journal_date": row.get("journal_date"),
                    "text": row["body"][:2000],
                }
            )
        # Load a bounded selection from the actual immutable originals, not reconstructed prose.
        from services.agent_evidence import EvidenceStore

        store = EvidenceStore(sb, owner, folder)
        for event in events:
            content = store.event_content(event["session_id"], event)
            sources.append(
                {
                    "id": "original:" + event["event_id"],
                    "kind": "original",
                    "date": iso(event["event_at"]).astimezone(ZoneInfo(tz)).date().isoformat(),
                    "observed_at": iso(event["event_at"]).isoformat(),
                    "session_id": event["session_id"],
                    "event_id": event["event_id"],
                    "role": event["role"],
                    "event_type": event["event_type"],
                    "text": content[:3000],
                    "truncated": bool(event.get("source_truncated")) or len(content) > 3000,
                }
            )
        for c in commits:
            sources.append(
                {
                    "id": "commit:" + c["sha"],
                    "kind": "git_commit",
                    "date": iso(c["at"]).astimezone(ZoneInfo(tz)).date().isoformat(),
                    "observed_at": iso(c["at"]).isoformat(),
                    "sha": c["sha"],
                    "url": c.get("url"),
                    "text": c["text"][:500],
                }
            )
        for p in pulls:
            sources.append(
                {
                    "id": "pull:" + str(p["number"]),
                    "kind": "github_pull_request",
                    "date": iso(p["at"]).astimezone(ZoneInfo(tz)).date().isoformat(),
                    "observed_at": iso(p["at"]).isoformat(),
                    "url": p["url"],
                    "text": p["text"][:500],
                }
            )
        sources.sort(key=lambda source: (iso(source["observed_at"]), source["id"]))
        weekly = []
        if kind == "monthly":
            weekly = [
                {
                    "period_start": r["period_start"],
                    "title": r["content"]["title"],
                    "summary": r["content"]["summary"],
                }
                for r in stored["weekly"].values()
                if start.isoformat() <= r["period_start"] <= end.isoformat()
            ]
        return {
            "operation": "reports",
            "input": {
                "head_sha": payload["head_sha"],
                "kind": kind,
                "period_start": start.isoformat(),
                "period_end": end.isoformat(),
                "timezone": tz,
                "cutoff": cutoff.isoformat(),
                "status": "final" if closed else "draft",
                "sources": sources,
                "weekly_orientation": weekly[:6],
            },
            "current": old.get("content") if old else None,
            "expected_sections": {},
            "expected_reviews": {},
            "report": {
                "kind": kind,
                "period_start": start.isoformat(),
                "period_end": end.isoformat(),
                "timezone": tz,
                "cutoff": cutoff.isoformat(),
                "status": "final" if closed else "draft",
                "source_digest": fingerprint,
                "expected_revision": old["revision"] if old else 0,
                "coverage": {
                    "policy": POLICY,
                    "journal_entries": snapshot.get("entry_count", len(entries)),
                    "journal_entries_included": len(entries),
                    "indexed_entries_available": journal_total,
                    "git_commits": commit_total,
                    "git_commits_included": len(commits),
                    "pull_requests": pull_total,
                    "pull_requests_included": len(pulls),
                    "original_events_included": len(events),
                    "original_events": snapshot.get("event_count", len(events)),
                    "github": payload.get("github_coverage", "unavailable"),
                    "originals": "bounded_sample",
                },
            },
        }, None
    return None, "reports are current or no period activity"


def report_quote_choices(sources):
    """Compact model choices; publication resolves IDs to unchanged original excerpts."""
    choices = {}
    count = 0
    for source in sources:
        excerpts = []
        for line in source["text"].splitlines():
            for sentence in re.split(r"(?<=[.!?])\s+", line):
                for start in range(0, len(sentence), 250):
                    text = sentence[start : start + 250].strip()
                    if 12 <= len(text) <= 250 and text not in excerpts:
                        excerpts.append(text)
        choices[source["id"]] = []
        for text in excerpts[:6]:
            choices[source["id"]].append({"id": f"q{count}", "text": text})
            count += 1
    return choices


def validate_report(snapshot, value):
    value = deepcopy(value)
    quotes = {
        quote["id"]: (source, quote["text"])
        for source, choices in report_quote_choices(snapshot["input"]["sources"]).items()
        for quote in choices
    }
    sources = {s["id"]: s for s in snapshot["input"]["sources"]}
    if (
        not 3 <= len(value["title"].strip()) <= 160
        or not 20 <= len(value["summary"].strip()) <= 1200
    ):
        raise ValueError("Invalid report title or summary")

    def cited(ids):
        if (
            not ids
            or len(ids) > 12
            or len(ids) != len(set(ids))
            or any(i not in sources for i in ids)
        ):
            raise ValueError("Report cites unknown or missing evidence")

    cited(value["summary_source_ids"])
    if not 1 <= len(value["sections"]) <= 6:
        raise ValueError("Invalid report sections")
    for section in value["sections"]:
        if not 3 <= len(section["heading"]) <= 100 or not 1 <= len(section["items"]) <= 8:
            raise ValueError("Invalid report section")
        for item in section["items"]:
            cited(item["source_ids"])
            if item["evidence_quote"] in quotes:
                source, text = quotes[item["evidence_quote"]]
                if source not in item["source_ids"]:
                    raise ValueError("Report quote belongs to an uncited source")
                item["evidence_quote"] = text
            if not 10 <= len(item["text"]) <= 1000 or not 12 <= len(item["evidence_quote"]) <= 250:
                raise ValueError("Invalid report item")
            if not any(item["evidence_quote"] in sources[i]["text"] for i in item["source_ids"]):
                raise ValueError("Report lacks an exact supporting quote")
    return value


def render_report(content):
    return "\n\n".join(
        [
            content["title"],
            content["summary"],
            *[
                section["heading"]
                + "\n"
                + "\n".join("- " + item["text"] for item in section["items"])
                for section in content["sections"]
            ],
        ]
    )


def report_context(sb, owner, folders, after, before, tz, session=None):
    """Optional indexed orientation. No model or raw archive calls on the chat path."""
    if session or not after or not before:
        return []
    from services.agent_memory import encode_reference

    first = iso(after).astimezone(ZoneInfo(tz)).date().isoformat()
    last = (iso(before) - timedelta(microseconds=1)).astimezone(ZoneInfo(tz)).date().isoformat()
    try:
        rows = (
            sb.table("repo_period_reports")
            .select(
                "id,folder_id,kind,period_start,period_end,timezone,cutoff,status,revision,generated_at,content"
            )
            .eq("user_id", owner)
            .in_("folder_id", folders)
            .eq("timezone", tz)
            .lte("period_start", last)
            .gte("period_end", first)
            .order("period_start", desc=True)
            .limit(8)
            .execute()
            .data
            or []
        )
    except Exception as exc:  # Optional orientation must not break original recall.
        import logging

        logging.getLogger(__name__).warning(
            "period report orientation unavailable: %s", type(exc).__name__
        )
        return []
    result = []
    for row in rows:
        content = row.pop("content")
        result.append(
            {
                **row,
                "excerpt": content["title"] + "\n" + content["summary"],
                "orientation_only": row["period_start"] < first or row["period_end"] > last,
                "reference": encode_reference(
                    {
                        "v": 1,
                        "kind": "period_report",
                        "owner": owner,
                        "folder": row["folder_id"],
                        "report": row["id"],
                        "revision": row["revision"],
                        "start": 0,
                    }
                ),
                "interpretation": (
                    "Persisted synthesis, not independent proof. Check dates and cutoff. "
                    "For a specific day use its journal and originals. "
                    "Later synthesis is not as-of knowledge."
                ),
            }
        )
    return result


def read_report_reference(sb, owner, ref, char_limit):
    from services.agent_memory import encode_reference, invalid

    report = (
        sb.table("repo_period_reports")
        .select("id,folder_id,kind,period_start,period_end,timezone")
        .eq("user_id", owner)
        .eq("folder_id", ref["folder"])
        .eq("id", ref["report"])
        .limit(1)
        .execute()
        .data
        or []
    )
    versions = (
        sb.table("repo_period_report_revisions")
        .select("*")
        .eq("user_id", owner)
        .eq("report_id", ref["report"])
        .eq("revision", ref["revision"])
        .limit(1)
        .execute()
        .data
        or []
    )
    if not report or not versions:
        invalid("report_reference_not_found", 404)
    value = versions[0]
    body = render_report(value["content"])
    start = ref["start"]
    more = start + char_limit < len(body)
    source_offset = ref.get("source_offset", 0)
    source_page = value["sources"][source_offset : source_offset + 8]
    sources = [{**source, "text": source["text"][:500]} for source in source_page]
    for source in sources:
        if source["kind"] == "original":
            source["reference"] = encode_reference(
                {
                    "v": 1,
                    "owner": owner,
                    "folder": ref["folder"],
                    "session": source["session_id"],
                    "event": source["event_id"],
                    "start": 0,
                    "length": len(source["text"]),
                    "after": None,
                    "before": value["cutoff"],
                    "timezone": report[0]["timezone"],
                }
            )
    return {
        "status": "ok",
        "period_reports": [
            {
                **report[0],
                "revision": ref["revision"],
                "cutoff": value["cutoff"],
                "generated_at": value["generated_at"],
                "excerpt": body[start : start + char_limit] if "source_offset" not in ref else "",
                "coverage": value["coverage"],
                "sources": sources,
                "source_count": len(value["sources"]),
                "next_sources_reference": encode_reference(
                    {**ref, "source_offset": source_offset + 8}
                )
                if source_offset + 8 < len(value["sources"])
                else None,
                "next_reference": encode_reference({**ref, "start": start + char_limit})
                if more
                else None,
            }
        ],
        "interpretation": (
            "A versioned synthesis. Sources may be reported, sampled or unavailable; "
            "verify originals for precise outcomes."
        ),
    }
