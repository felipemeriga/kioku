"""Cheap, conservative source selection before generation; no routing model call."""

import calendar
import json
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

MONTHS = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
MONTH_PATTERN = "|".join(MONTHS)


def history_question(question):
    low = question.lower()
    # A document discussing agent memory is still a document question.
    if re.search(
        r"\b(?:document|documentation|spec|manual|pdf)\b.*\b(?:say|describe|define)\b", low
    ):
        return False
    return bool(
        re.search(
            r"\b(?:recorded work|agent history|original session|previous attempts?"
            r"|past sessions?)\b"
            r"|\b(?:did|have|had|were)\s+(?:we|i|you)\b"
            r"|\b(?:we|i)\s+(?:worked|tried|discussed|investigated)\b"
            r"|\bsessions?\s+(?:discussed|recorded|worked)\b",
            low,
        )
    )


def date_filters(question, timezone, now=None):
    """Resolve only explicit years or relative periods; incident mentions are not filters."""
    today = (now or datetime.now(ZoneInfo(timezone))).astimezone(ZoneInfo(timezone)).date()
    low = question.lower()
    start = end = None
    if "yesterday" in low:
        start = end = today - timedelta(days=1)
    elif re.search(r"\b(?:this|last) week\b", low):
        start = today - timedelta(days=today.weekday())
        if "last week" in low:
            start -= timedelta(days=7)
        end = min(start + timedelta(days=6), today)
    elif re.search(r"\b(?:this|last) month\b", low):
        start = today.replace(day=1)
        if "last month" in low:
            start = (start - timedelta(days=1)).replace(day=1)
        end = min(start.replace(day=calendar.monthrange(start.year, start.month)[1]), today)
    elif re.search(r"\b(?:work|worked|recorded|issues|experiments)\b.*\btoday\b", low):
        start = end = today
    else:
        iso = re.findall(r"\b\d{4}-\d{2}-\d{2}\b", low)
        named = re.search(
            rf"\b({MONTH_PATTERN})\s+(\d{{1,2}})(?:\s*[–—-]\s*(\d{{1,2}}))?,?\s+(\d{{4}})\b", low
        )
        month = re.search(rf"\b({MONTH_PATTERN})\s+(\d{{4}})\b", low)
        try:
            if iso:
                start, end = date.fromisoformat(iso[0]), date.fromisoformat(iso[-1])
            elif named:
                name, first, last, year = named.groups()
                start = date(int(year), MONTHS[name], int(first))
                end = date(int(year), MONTHS[name], int(last or first))
            elif month and re.search(r"\b(?:worked|work|recorded|during|throughout)\b", low):
                name, year = month.groups()
                start = date(int(year), MONTHS[name], 1)
                end = min(
                    date(start.year, start.month, calendar.monthrange(start.year, start.month)[1]),
                    today,
                )
        except ValueError:
            return {}  # The agent must clarify malformed/ambiguous dates, not guess.
    if start is None or end is None or start > end:
        return {}
    if re.search(r"\bbefore\b", low) and start == end:
        return {"as_of": (end - timedelta(days=1)).isoformat()}
    if re.search(r"\b(?:as of|by the end of|by end of)\b", low):
        return {"as_of": end.isoformat()}
    return {"from_date": start.isoformat(), "through_date": end.isoformat()}


def prefetch(question, user_timezone, execute, *, filename=None, folders=()):
    """Return source-aware evidence and the exact calls for durable tracing.

    execute is the caller's existing owner/scope-bound tool dispatcher. It is
    never given a model-supplied owner, URL, or broader authorization.
    """
    calls = []

    def run(name, arguments):
        value = execute(name, arguments)
        calls.append({"name": name, "input": arguments, "result": value})
        return value

    if re.search(r"(?:^|[.!?;]\s+)do not use (?:any )?tools[.!]?\s*$", question, re.I):
        return json.dumps({"source": "none", "reason": "User requested no tool use."}), calls
    if filename or not history_question(question):
        return run("knowledge_base_search", {"query": question}), calls

    filters = date_filters(question, user_timezone)
    args = {"query": question, "timezone": user_timezone, "order": "relevance", **filters}
    named = [
        f
        for f in folders
        if len(f["name"]) > 2
        and re.search(r"(?<![\w-])" + re.escape(f["name"]) + r"(?![\w-])", question, re.I)
    ]
    if len(named) == 1:
        args["folder"] = named[0]["id"]
        args["query"] = re.sub(re.escape(named[0]["name"]), "", question, flags=re.I)
    elif not named:
        repository = re.search(r"\b(?:in|for)\s+([a-z][a-z0-9]*(?:-[a-z0-9]+)+)\b", question, re.I)
        if repository:
            # Let the shared authority resolver return not-found/ambiguous;
            # a named repo outside this scope must not become a global search.
            args["folder"] = repository[1]
    overview = bool(
        re.search(
            r"\b(?:what did we work|what have we worked|group.*(?:day|repository)"
            r"|work.*(?:this|last) (?:week|month))",
            question,
            re.I,
        )
    )
    if overview:
        args["query"] = ""
        args["order"] = "chronological"
    session = re.search(r"\bsession\s+([a-z0-9][a-z0-9_.:-]{6,179})", question, re.I)
    if session:
        args["session"] = session[1]
    pages = []

    def decoded(value):
        try:
            result = json.loads(value)
            if isinstance(result, dict):
                return result
        except (ValueError, TypeError):
            pass
        return {"status": "error", "code": "invalid_history_result"}

    first = decoded(run("search_agent_history", args))
    pages.append(first)
    # An overview can cover many session-days. Fetch bounded pages here instead
    # of spending a model round deciding to press Next for every ten days.
    while overview and len(pages) < 5:
        activity = pages[-1].get("activity") or {}
        if not activity.get("has_more") or len(json.dumps(pages)) > 40000:
            break
        pages.append(
            decoded(run("search_agent_history", {**args, "offset": activity["next_offset"]}))
        )
    expansions = []
    if not overview:
        # Read actual context, not only discovery excerpts. No new search scope
        # is invented; signed references retain their original temporal bounds.
        for match in first.get("matches", [])[:2]:
            value = run(
                "read_agent_evidence",
                {
                    "reference": match["reference"],
                    "before_records": 1,
                    "after_records": 1,
                    "char_limit": 4000,
                },
            )
            expansions.append(decoded(value))
    return json.dumps(
        {
            "source": "agent_history",
            "pages": pages,
            "expanded_evidence": expansions,
            "interpretation": (
                "Dates on journal bodies are capture dates; cumulative session titles "
                "are not day facts. Original record time differs from described incident time. "
                "Reports are not deployment proof. Follow remaining pages or references for "
                "concrete gaps; never claim no record from a partial search."
            ),
        },
        ensure_ascii=False,
    ), calls
