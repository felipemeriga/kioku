"""Cheap, conservative source selection before generation; no routing model call."""

import calendar
import json
import re
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dateutil.parser import isoparse

MONTHS = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
MONTH_PATTERN = "|".join(MONTHS)
CUTOFF = r"as of|before|by the end of|by end of|até"
ISO_DATE = r"\d{4}-\d{2}-\d{2}"
PORTUGUESE_YESTERDAY_RANGE = r"(?:de|entre) ontem (?:pra|para|a|até|e) hoje"
CLOCK = r"\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?"
EXACT_CUTOFF = re.compile(
    rf"\b({CUTOFF})\s+({ISO_DATE})(?:T|\s+(?:at\s+(?:exactly\s+)?|às\s+)?)"
    rf"({CLOCK})(?:\s*(Z|UTC|[+-]\d{{2}}:?\d{{2}})(?![\w/]))?"
    rf"(?![\w:+-]|\.\d)(?:\s+(?:in|em)\s+([a-z_]+(?:/[a-z_+-]+)+))?",
    re.I,
)

ANSWER_INSTRUCTION = """Answer the user's current question from the supplied current-turn evidence.
Use tools only for a specific missing fact. Cite only current evidence or new tool results.
For a multi-part question, check source support for each requested component. If results
cover only one component, search separately for the uncovered parts; do not fill those
gaps from general knowledge. Do not add worked numerical examples unless requested.
For implementation calculations or guarantees, a caller or comment is not sufficient evidence:
retrieve the responsible function body, or state only what the documentation describes.
For duplicate-request protection, consider two separate requests: determine whether they reuse
the same identifier before claiming deduplication. A different key on each request cannot
provide that guarantee. Keep the direct answer consistent with this executable behavior.
For a focused factual question, give one short paragraph or up to three short bullets,
normally within 120 words. Stop once the requested facts are answered. Include a timeline
or a longer overview when the user requested that scope. Do not add unsolicited technical
tutorials or assertions about deployment, missing records, or tests. Partial retrieval does
not establish absence across the whole period. For current code behavior, check indexed source
before relying on dated notes. If asked what starts a service, trace its caller; treat "who" in
a code question as a component or function unless the user asks for a person or team. For an
exact cadence, endpoint, parameter, error message, or comparison, use a targeted tool call
when the supplied excerpt lacks the requested detail. For a dated issue recap, check every
session-day group in the supplied inventory and include each distinct issue; a short answer
should not silently skip a session. When a code graph result identifies a file and line but
the search excerpt lacks the implementation, use code_graph_lookup source for that exact line.
Return a complete standalone answer."""


def history_question(question):
    low = question.lower()
    # A document discussing agent memory is still a document question.
    if re.search(
        r"\b(?:document|documentation|spec|manual|pdf|documentação|documentacao|documento)\b"
        r".*\b(?:say|describe|define|diz|descreve|explica)\b",
        low,
    ):
        return False
    return bool(
        re.search(
            r"\b(?:recorded work|agent history|original session|previous attempts?"
            r"|past sessions?)\b"
            r"|\b(?:did|have|had|were)\s+(?:we|i|you)\b"
            r"|\b(?:we|i)\s+(?:worked|tried|discussed|investigated|had|changed|deployed)\b"
            r"|\b(?:agent|session|journal)\s+(?:work|activity|records)\b"
            r"|\b(?:earlier|previous|past)\s+(?:work|attempts?|experiments?|investigation)\b"
            r"|\bsessions?\s+(?:discussed|recorded|worked)\b"
            r"|\bremember\s+(?:why|when|how|what|whether|if)\b"
            r"|\b(?:já\s+)?(?:tentamos|mudamos|decidimos|discutimos|investigamos|"
            r"rejeitamos|fizemos|trabalhamos|corrigimos|testamos|tivemos|resolvemos)\b"
            r"|\ba gente\s+(?:fez|tentou|mudou|decidiu|discutiu|investigou|"
            r"trabalhou|corrigiu|testou)\b"
            r"|\b(?:lembra|lembre|lembro)\s+(?:por que|por quê|quando|como|o que|se)\b",
            low,
        )
    )


def date_filters(question, timezone, now=None):
    """Resolve only explicit years or relative periods; incident mentions are not filters."""
    zone = ZoneInfo(timezone)
    today = (now or datetime.now(zone)).astimezone(zone).date()
    cutoff = EXACT_CUTOFF.search(question)
    if cutoff:
        marker, day, clock, offset, named_zone = cutoff.groups()
        stamp = f"{day}T{clock}{'Z' if offset and offset.upper() == 'UTC' else offset or ''}"
        try:
            instant = isoparse(stamp)
            if instant.tzinfo is None:
                instant = instant.replace(tzinfo=ZoneInfo(named_zone) if named_zone else zone)
            if marker.lower() == "before":
                instant = instant.astimezone(UTC) - timedelta(microseconds=1)
            return {"as_of": instant.isoformat()}
        except (ValueError, OverflowError, ZoneInfoNotFoundError):
            return {"as_of": stamp}  # Let the typed tool reject an invalid cutoff.
    low = question.lower()
    start = end = None
    if re.search(
        rf"\b(?:{PORTUGUESE_YESTERDAY_RANGE}"
        r"|(?:from|between) yesterday (?:to|through|and) today)\b",
        low,
    ):
        return {
            "from_date": (today - timedelta(days=1)).isoformat(),
            "through_date": today.isoformat(),
        }
    if re.search(r"\b(?:day before yesterday|anteontem)\b", low):
        start = end = today - timedelta(days=2)
    elif re.search(r"\b(?:yesterday|ontem)\b", low):
        start = end = today - timedelta(days=1)
    elif re.search(
        r"\b(?:(?:this|last) week|(?:esta|essa|nesta|nessa) semana|semana passada)\b", low
    ):
        start = today - timedelta(days=today.weekday())
        if re.search(r"\b(?:last week|semana passada)\b", low):
            start -= timedelta(days=7)
        end = min(start + timedelta(days=6), today)
    elif re.search(
        r"\b(?:(?:this|last) month|(?:este|esse|neste|nesse) m[eê]s|m[eê]s passado)\b", low
    ):
        start = today.replace(day=1)
        if re.search(r"\b(?:last month|m[eê]s passado)\b", low):
            start = (start - timedelta(days=1)).replace(day=1)
        end = min(start.replace(day=calendar.monthrange(start.year, start.month)[1]), today)
    elif re.search(r"\b(?:today|hoje)\b", low) and (
        history_question(question)
        or re.search(r"\b(?:work|worked|recorded|issues|experiments)\b", low)
    ):
        start = end = today
    else:
        iso = re.findall(rf"\b{ISO_DATE}\b", low)
        named = re.search(
            rf"\b({MONTH_PATTERN})\s+(\d{{1,2}})(?:\s*[–—-]\s*(\d{{1,2}}))?,?\s+(\d{{4}})\b", low
        )
        month = re.search(rf"\b({MONTH_PATTERN})\s+(\d{{4}})\b", low)
        if not re.search(rf"\b(?:{CUTOFF})\b", low) and re.search(
            r"\b(?:outage|incident|failure|regression|bug|falha|incidente)\b.*"
            r"\b(?:from|of|on|de|em)\s+",
            low,
        ):
            return {}
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
    cutoff_words = re.sub(r"\bday before yesterday\b", "", low)
    if re.search(r"\bbefore\b", cutoff_words) and start == end:
        return {"as_of": (end - timedelta(days=1)).isoformat()}
    if re.search(r"\b(?:as of|by the end of|by end of|até)\b", low):
        return {"as_of": end.isoformat()}
    return {"from_date": start.isoformat(), "through_date": end.isoformat()}


def source_question(question: str) -> bool:
    low = question.lower()
    return bool(
        re.search(r"\b(?:code|source|function|scheduler|ingester)\b", low)
        or re.search(r"\bhow\s+does\s+the\s+(?:new|current)\s+\w+\s+work\b", low)
    )


def source_search_query(question: str, repo_name: str | None = None) -> str:
    """Make a single scoped code lookup cover the source the question asks for.

    This only changes the first retrieval query. The original user wording is
    still passed to the answerer, and the existing tool can search again when
    the first set of sources is incomplete.
    """
    low = question.lower()
    if not source_question(question):
        return question
    query = question
    if re.search(r"\b(?:new|current)\s+\w+\s+work", low):
        query = re.sub(r"\bnew\s+", "", query, flags=re.I)
        query += " current source code implementation"
    if re.search(r"\b(?:who|what|which)\b.*\b(?:start|starts|starting|launch)\b", low):
        query += " scheduler caller invokes launch function callee implementation"
    if re.search(r"\b(?:error|failure|fail|can't)\b", low) and re.search(
        r"\b(?:start|starting|launch)\b", low
    ):
        query += " caller logger.error catch cleanup underlying start function thrown errors"
    if repo_name and repo_name.lower() not in low:
        query += f" in {repo_name}"
    return query


def prefetch(question, user_timezone, execute, *, filename=None, folders=(), repo_name=None):
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
        query = source_search_query(question, repo_name)
        return run("knowledge_base_search", {"query": query}), calls

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
    dated_issue_overview = bool(
        filters
        and re.search(
            r"\b(?:what|which)\s+(?:were\s+the\s+)?(?:issues|problems|incidents)\b"
            r".*\b(?:we|i)\b",
            question,
            re.I,
        )
        and not re.search(r"\bwith\s+\S+", question, re.I)
    )
    overview = dated_issue_overview or bool(
        re.search(
            r"\b(?:what did we work|what have we worked|group.*(?:day|repository)"
            r"|work.*(?:this|last) (?:week|month))"
            r"|\b(?:o que|em que)\s+(?:(?:a gente|nós)\s+)?"
            r"(?:fizemos|fez|trabalhamos|trabalhou)\s+(?:(?:na|no)\s+)?"
            r"(?:hoje|ontem|anteontem|semana passada|(?:nesta|nessa|esta|essa) semana"
            r"|m[eê]s passado|(?:neste|nesse|este|esse) m[eê]s"
            rf"|{PORTUGUESE_YESTERDAY_RANGE})\b",
            question,
            re.I,
        )
    )
    if "as_of" in filters:
        args["query"] = EXACT_CUTOFF.sub("", args["query"]).strip()
    if overview:
        args["query"] = ""
        # Historical cutoffs use originals only. Overview includes revisable journals.
        if "as_of" in filters:
            overview = False
            args["order"] = "latest"
        else:
            args["order"] = "chronological"
            args["projection"] = "overview"
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
        from services.agent_memory import technical_terms

        # Dated reports supply concrete navigation anchors for a later status
        # check. Keep the original scope/cutoff; journals themselves are reports,
        # not proof that a command ran or a deployment happened.
        reports = (first.get("activity") or {}).get("days", [])[:2]
        anchors = sorted(
            {
                t
                for report in reports
                for t in technical_terms(report.get("summary", ""))
                if "_" in t or t.isdigit() or (len(t) >= 5 and t.isalpha())
            }
        )[:8]
        followup = {}
        if anchors:
            focused = " ".join("#" + t if t.isdigit() else t.upper() for t in anchors)
            followup = decoded(
                run(
                    "search_agent_history",
                    {
                        **args,
                        "query": focused,
                        "order": "latest",
                        "limit": 5,
                    },
                )
            )
            pages.append(followup)
        # Read actual context, not only discovery excerpts. No new search scope
        # is invented; signed references retain their original temporal bounds.
        seen = set()
        primary = first.get("matches", [])
        candidates = primary[:1] + followup.get("matches", [])[:1] + primary[1:]
        for match in candidates:
            # Native archives can contain the same message in both an event
            # stream and a response record. Preserve both locators in search,
            # but spend the bounded expansion budget on distinct context.
            key = (match.get("excerpt") or match["reference"]).strip()
            if key in seen:
                continue
            seen.add(key)
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
            if len(expansions) == 2:
                break
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
