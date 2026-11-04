"""Authorized I/O snapshots for pure maintenance operations."""

from services.folder_summary.briefing_schema import snapshot_sections


def capture(sb, owner, folder, operation, payload):
    from services.folder_summary.repo import get_latest_summary

    if operation == "activity" and not payload.get("commits"):
        return None, "no commits"
    if operation in ("how_it_runs", "deployment", "reground") and not payload.get("files"):
        return None, "no files"
    latest = get_latest_summary(sb, folder, owner)
    sections = snapshot_sections(latest)
    if operation == "review_plan" and not latest:
        return None, "no briefing yet"
    targets = (
        payload.get("selected", ["architecture", "overview"])
        if operation == "reground"
        else [operation]
    )
    if operation not in ("review_plan", "learnings"):
        if not latest:
            return None, "no briefing yet"
        editable = [s for s in targets if (sections.get(s) or {}).get("provenance") != "user_ui"]
        if not editable:
            return None, "section edited by user"
        if operation == "reground":
            targets = editable
            payload = {**payload, "selected": editable}
    expected = {s: sections.get(s) for s in targets if s in sections}
    current = {s: (sections.get(s) or {}).get("content") for s in targets}
    freshness = (
        sb.table("repo_freshness")
        .select("section_reviews")
        .eq("folder_id", folder)
        .eq("user_id", owner)
        .limit(1)
        .execute()
        .data
        or []
    )
    reviews = freshness[0].get("section_reviews", {}) if freshness else {}
    extra = {"expected_reviews": {name: reviews.get(name) for name in expected}}

    if operation == "review_plan":
        expected = sections
        current = {s: (v or {}).get("content") for s, v in sections.items()}
    elif operation in ("activity", "how_it_runs", "deployment"):
        current = current.get(operation)
        if current is None:
            return None, "section not present"
        if operation == "how_it_runs" and isinstance(current, str):
            current = {"requirements": [], "local_dev": current}
    if operation in ("documentation", "review_plan"):
        docs = (
            sb.table("repo_documentation")
            .select("id,content,abstract,generated_at")
            .eq("folder_id", folder)
            .eq("user_id", owner)
            .order("generated_at", desc=True)
            .limit(1)
            .execute()
            .data
            or []
        )
        extra["documentation_revision"] = docs[0].get("id") if docs else None
        if operation == "documentation":
            if not docs:
                return None, "no detailed documentation yet"
            current = docs[0]
        else:
            current["documentation"] = docs[0].get("abstract", "") if docs else ""
    if operation == "reground":
        extra["symbols"] = (
            sb.table("repo_symbols")
            .select("file,symbol,kind")
            .order("file")
            .order("symbol")
            .order("kind")
            .eq("folder_id", folder)
            .eq("user_id", owner)
            .limit(100)
            .execute()
            .data
            or []
        )
        extra["edges"] = (
            sb.table("repo_edges")
            .select("ref_file,src_node_id,dst_node_id,relation")
            .order("ref_file")
            .order("src_node_id")
            .order("dst_node_id")
            .order("relation")
            .eq("folder_id", folder)
            .eq("user_id", owner)
            .limit(50)
            .execute()
            .data
            or []
        )
    if operation == "learnings":
        from services.agent_journal import read_journal
        from services.repo_learnings import journal_entries

        def days_from(table, columns):
            rows = []
            for offset in range(0, 10000, 500):
                page = (
                    sb.table(table)
                    .select(columns)
                    .eq("user_id", owner)
                    .eq("folder_id", folder)
                    .order("journal_date")
                    .range(offset, offset + 499)
                    .execute()
                    .data
                    or []
                )
                rows.extend(page)
                if len(page) < 500:
                    break
            return rows

        days = days_from("agent_journal_days", "journal_date,revision")
        checkpoints = days_from("repo_learning_days", "journal_date,revision,processed_ids")
        prior = {d["journal_date"]: d for d in checkpoints}
        pending = None
        for day in days:
            old = prior.get(day["journal_date"], {})
            if old.get("revision") == day["revision"]:
                continue
            entries = journal_entries(
                read_journal(sb, owner, folder, day["journal_date"])["markdown"],
                day["journal_date"],
            )
            fresh = [e for e in entries if e["id"] not in set(old.get("processed_ids") or [])][:8]
            # Empty days need no model; handled atomically with the next nonempty batch.
            pending = (day, old, entries, fresh)
            break
        if pending is None:
            return None, "no pending journal entries"
        day, old, entries, fresh = pending
        payload = {**payload, "new_entries": fresh}
        extra["learning_day"] = {**day, "prior": old, "all_ids": [e["id"] for e in entries]}
        current = (
            sb.table("repo_learnings")
            .select("topic_key,statement,status,source_entries")
            .eq("user_id", owner)
            .eq("folder_id", folder)
            .order("updated_at", desc=True)
            .limit(80)
            .execute()
            .data
            or []
        )
        expected = {}
    extra["expected_reviews"] = {name: reviews.get(name) for name in expected}
    return {
        "operation": operation,
        "input": payload,
        "current": current,
        "expected_sections": expected,
        **extra,
    }, None
