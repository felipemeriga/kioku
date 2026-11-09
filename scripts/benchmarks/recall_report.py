"""Build a private paired latency/evidence report; never treat keywords as factual accuracy."""

import argparse
import csv
import hashlib
import html
import json
import math
import os
import re
import statistics
from pathlib import Path

from dateutil.parser import isoparse


def percentile(values, fraction):
    if not values:
        return None
    values = sorted(values)
    rank = (len(values) - 1) * fraction
    low, high = math.floor(rank), math.ceil(rank)
    return round(values[low] + (values[high] - values[low]) * (rank - low), 3)


def tool_union(tools):
    intervals = sorted(
        (isoparse(t["started_at"]).timestamp(), isoparse(t["finished_at"]).timestamp())
        for t in tools
        if t.get("started_at") and t.get("finished_at")
    )
    total, edge = 0, float("-inf")
    for start, end in intervals:
        total += max(0, end - max(edge, start))
        edge = max(edge, end)
    return round(total, 3)


def metrics(state, question, gold, audit):
    terminal = state.get("terminal") or {}
    debug = terminal.get("debug") or {}
    execution = debug.get("execution") or {}
    failure_attempts = (state.get("failure_telemetry") or {}).get("attempts") or []
    usage = (
        execution.get("usage")
        or (failure_attempts[-1].get("usage") if failure_attempts else {})
        or {}
    )
    attempts = (execution.get("timings") or {}).get("attempts") or failure_attempts
    tools = debug.get("tool_calls") or state.get("recovered_tools") or []
    answer = terminal.get("replace") or ""
    citations = terminal.get("citations") or []
    cited = {int(x) for x in re.findall(r"\[(\d+)\]", answer)}
    available = {c.get("number") for c in citations}
    retrieved, expanded, queries = [], [], []
    seen_batches, repeated_batches, context_characters = set(), 0, 0
    for artifact in state.get("artifacts", []):
        name = artifact["tool"]["name"]
        if name not in {"search_agent_history", "read_agent_evidence"}:
            continue
        chunks = artifact.get("chunks", [])
        text = "".join(chunk.get("result", "") for chunk in chunks)
        try:
            result = json.loads(text)
        except ValueError:
            continue
        context_characters += len(text)
        if name == "search_agent_history":
            queries.append(
                {
                    "requested": artifact["tool"].get("input"),
                    "effective_terms": result.get("search_terms"),
                    "matching_mode": result.get("matching_mode"),
                    "total_matches": result.get("total_matches"),
                }
            )
            batch = tuple(row["event_id"] for row in result.get("matches", []))
            if batch:
                repeated_batches += batch in seen_batches
                seen_batches.add(batch)
            retrieved.extend(row["event_id"] for row in result.get("matches", []))
        else:
            expanded.extend(row["event_id"] for row in result.get("evidence", []))
    reference = set(gold.get(question["id"], []))
    ranked = list(dict.fromkeys(retrieved))
    first = next(
        (i + 1 for i, event in enumerate(ranked[:50]) if event in reference), None
    )
    dcg = sum(
        1 / math.log2(i + 2)
        for i, event in enumerate(ranked[:10])
        if event in reference
    )
    ideal = sum(1 / math.log2(i + 2) for i in range(min(10, len(reference))))
    models = list((usage.get("model_usage") or {}).values())
    return {
        "key": state["key"],
        "case": question["id"],
        "pair": state["pair"],
        "effort": state["effort"],
        "workers": state.get("workers", 1),
        "success": bool(state.get("success")),
        "error_code": (terminal.get("error") or {}).get("code")
        if isinstance(terminal.get("error"), dict)
        else terminal.get("error"),
        "effort_verified": (state.get("verified_control") or {}).get("effort")
        == state["effort"],
        "server_seconds": (debug.get("timings") or {}).get("total_seconds"),
        "runner_seconds": sum(a.get("elapsed_seconds", 0) for a in attempts)
        if attempts
        else None,
        "queue_seconds": sum(a.get("queue_wait_seconds", 0) for a in attempts)
        if attempts
        else None,
        "first_text_seconds": attempts[0].get("first_text_seconds")
        if attempts
        else None,
        "tool_union_seconds": tool_union(tools),
        "search_calls": sum(t.get("name") == "search_agent_history" for t in tools),
        "read_calls": sum(t.get("name") == "read_agent_evidence" for t in tools),
        "all_tool_calls": len(tools),
        "memory_tool_context_characters": context_characters,
        "repeated_nonempty_result_batches": repeated_batches,
        "unique_original_events": len(set(retrieved + expanded)),
        "kind": question.get("kind", "temporal"),
        "thinking_tokens": sum(m.get("thinkingTokens", 0) for m in models)
        if models and usage.get("complete")
        else None,
        "output_tokens": usage.get("output_tokens"),
        "cache_read_tokens": usage.get("cache_read_tokens"),
        "citation_numbers_resolve": cited <= available,
        "cited_sources": len(cited),
        "anchor_eligible": bool(reference),
        "direct_anchor_hit": bool(set(retrieved) & reference) if reference else None,
        "expanded_anchor_hit": bool(set(retrieved + expanded) & reference)
        if reference
        else None,
        "anchor_reciprocal_rank": 1 / first if first else 0 if reference else None,
        "topic_probe_recall_at_50": len(set(ranked[:50]) & reference) / len(reference)
        if reference
        else None,
        "topic_probe_ndcg_at_10": dcg / ideal if ideal else None,
        "audit": audit.get(state["key"]),
        "answer_sha256": hashlib.sha256(answer.encode()).hexdigest(),
        "question": state.get("question", question["question"]),
        "answer": answer,
        "citations": [
            {
                key: c.get(key)
                for key in ("number", "source", "excerpt", "created_at", "last_updated")
            }
            for c in citations
            if c.get("number") in cited
        ],
        "queries": queries,
    }


def quality_by_kind(rows):
    result = {}
    for kind in sorted({row["kind"] for row in rows}):
        subset = [row for row in rows if row["kind"] == kind]
        audited = [row for row in subset if row["audit"] is not None]
        result[kind] = {
            "trials": len(subset),
            "audited": len(audited),
            "manual_mean_score": statistics.mean(
                row["audit"]["score"] for row in audited
            )
            if audited
            else None,
        }
    return result


def aggregate(rows):
    measured = [
        "server_seconds",
        "runner_seconds",
        "first_text_seconds",
        "queue_seconds",
        "tool_union_seconds",
        "search_calls",
        "read_calls",
        "thinking_tokens",
        "output_tokens",
        "memory_tool_context_characters",
        "repeated_nonempty_result_batches",
        "unique_original_events",
    ]
    result = {}
    for effort in ["low", "high"]:
        group = [r for r in rows if r["effort"] == effort]
        eligible = [r for r in group if r["anchor_eligible"]]
        audited = [r for r in group if r["audit"] is not None]
        result[effort] = {
            "trials": len(group),
            "completed": sum(r["success"] for r in group),
            "effort_verified": sum(r["effort_verified"] for r in group),
            "citation_number_failures": sum(
                not r["citation_numbers_resolve"] for r in group
            ),
            "anchor_cases": len(eligible),
            "direct_anchor_hits": sum(bool(r["direct_anchor_hit"]) for r in eligible),
            "expanded_anchor_hits": sum(
                bool(r["expanded_anchor_hit"]) for r in eligible
            ),
            "anchor_mrr": statistics.mean(r["anchor_reciprocal_rank"] for r in eligible)
            if eligible
            else None,
            "topic_probe_recall_at_50": statistics.mean(
                r["topic_probe_recall_at_50"] for r in eligible
            )
            if eligible
            else None,
            "topic_probe_ndcg_at_10": statistics.mean(
                r["topic_probe_ndcg_at_10"] for r in eligible
            )
            if eligible
            else None,
            "by_kind": quality_by_kind(group),
            "manually_audited": len(audited),
            "manual_mean_score": statistics.mean(r["audit"]["score"] for r in audited)
            if audited
            else None,
            "manual_passes": sum(r["audit"].get("verdict") == "pass" for r in audited),
            "timings": {
                key: {
                    "n": len(values),
                    "median": percentile(values, 0.5),
                    "p95": percentile(values, 0.95),
                }
                for key in measured
                if (
                    values := [
                        r[key] for r in group if isinstance(r[key], (int, float))
                    ]
                )
            },
        }
    pairs = {}
    for row in rows:
        pairs.setdefault(row["pair"], {})[row["effort"]] = row
    ratios = [
        p["low"]["runner_seconds"] / p["high"]["runner_seconds"]
        for p in pairs.values()
        if set(p) == {"low", "high"}
        and all(p[e]["success"] and p[e]["runner_seconds"] for e in p)
        and p["low"]["workers"] == p["high"]["workers"]
    ]
    result["paired_runner_ratio"] = {
        "pairs": len(ratios),
        "median_low_over_high": percentile(ratios, 0.5),
    }
    return result


def comparison_table(summary):
    def timing(effort, name, percentile="median"):
        value = summary[effort]["timings"].get(name, {}).get(percentile)
        return "Unavailable" if value is None else f"{value:.1f} s"

    columns = [
        (
            "Completed trials",
            lambda e: f"{summary[e]['completed']} / {summary[e]['trials']}",
        ),
        ("Runner median", lambda e: timing(e, "runner_seconds")),
        ("Runner p95", lambda e: timing(e, "runner_seconds", "p95")),
        ("First text median", lambda e: timing(e, "first_text_seconds")),
        ("Observed tool time median", lambda e: timing(e, "tool_union_seconds")),
        (
            "Manual quality score",
            lambda e: (
                "Pending"
                if summary[e]["manual_mean_score"] is None
                else f"{summary[e]['manual_mean_score']:.0%} ({summary[e]['manually_audited']} audited)"
            ),
        ),
        (
            "Known topic-anchor discovery",
            lambda e: (
                f"{summary[e]['expanded_anchor_hits']} / {summary[e]['anchor_cases']}"
            ),
        ),
        (
            "Invalid citation numbers",
            lambda e: str(summary[e]["citation_number_failures"]),
        ),
    ]
    return (
        "<section><h2>Measured comparison</h2><table><thead><tr><th>Metric</th><th>Low</th><th>High</th></tr></thead><tbody>"
        + "".join(
            "<tr><td>"
            + html.escape(label)
            + "</td><td>"
            + html.escape(value("low"))
            + "</td><td>"
            + html.escape(value("high"))
            + "</td></tr>"
            for label, value in columns
        )
        + "</tbody></table></section>"
    )


def private_write(path, text):
    fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(text)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--run", type=Path, required=True)
    p.add_argument("--questions", type=Path, required=True)
    p.add_argument("--gold", type=Path)
    p.add_argument("--audit", type=Path)
    args = p.parse_args()
    questions = json.loads(args.questions.read_text())
    gold = json.loads(args.gold.read_text()) if args.gold else {}
    audit = (
        json.loads(args.audit.read_text()) if args.audit and args.audit.exists() else {}
    )
    rows = []
    for item in json.loads((args.run / "plan.json").read_text()):
        path = args.run / (item["key"] + ".json")
        if path.exists() and (state := json.loads(path.read_text())).get("finished"):
            rows.append(metrics(state, questions[item["question_index"]], gold, audit))
    summary = aggregate(rows)
    private_write(args.run / "summary.json", json.dumps(summary, indent=2))
    data = json.dumps(rows).replace("<", "\\u003c")
    totals = html.escape(json.dumps(summary, indent=2))
    comparison = comparison_table(summary)
    page = (
        """<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Recall effort benchmark</title>
<style>body{margin:0;background:#0b0812;color:#eee8f5;font:15px system-ui}main{max-width:1400px;margin:auto;padding:36px}h1{font-size:30px}p,small{color:#b8adc6}button,select{background:#21172f;color:inherit;border:1px solid #68507e;border-radius:6px;padding:10px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:12px ui-monospace;line-height:1.6}table{border-collapse:collapse;width:100%}th,td{text-align:left;padding:12px;border-bottom:1px solid #49345f}th:nth-child(2){color:#29cedb}th:nth-child(3){color:#ee269d}section{background:#140e20;border:1px solid #49345f;border-radius:10px;margin:20px 0;padding:20px}.pair{display:grid;grid-template-columns:1fr 1fr;gap:18px}.answer{border-top:3px solid #29cedb;padding:16px;background:#191123;min-width:0}.answer.high{border-color:#ee269d}.answer pre{font:14px system-ui;line-height:1.7}.meta{color:#8de1d6}summary{cursor:pointer}label{display:inline-block;margin-right:18px}@media(max-width:700px){main{padding:18px}.pair{grid-template-columns:1fr}}</style>
<main><small>KIOKU / RECALL EVALUATION</small><h1>Reasoning effort: speed and evidence</h1>
<p>Actual native subscription runs. Low and High use the same model, scope, tool limits and output budget. Failed trials remain in the results. Queue time, model runtime and overlapping tool intervals are reported separately.</p>
<p>Anchor hits and topic-probe recall@50/MRR@50/nDCG@10 measure discovery of known original records in first-appearance tool-trace order; they do not establish factual accuracy or form a complete relevance judgment for the live archive. Citation-number resolution does not prove that a source supports a claim. Manual audits are reported separately. Missing timing values are never replaced with zero.</p>
COMPARISON<label>Question <select id="question"><option value="">All questions</option></select></label><label>Show <select id="status"><option value="">All trials</option><option value="failure">Execution failures</option><option value="audited">Manually audited</option></select></label>
<div id="cases"></div><section><details><summary>Aggregate metrics and sample sizes</summary><pre>SUMMARY</pre></details></section></main>
<script id="data" type="application/json">DATA</script><script>
const rows=JSON.parse(document.getElementById('data').textContent), select=document.getElementById('question'), status=document.getElementById('status');
for(const id of [...new Set(rows.map(r=>r.case))]){const o=document.createElement('option');o.value=id;o.textContent=id;select.append(o)}
const fmt=v=>Number.isFinite(v)?v.toFixed(1):'unavailable';
const esc=v=>String(v??'unavailable').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function render(){const groups=new Map();for(const r of rows){if(select.value&&r.case!==select.value)continue;if(status.value==='failure'&&r.success)continue;if(status.value==='audited'&&!r.audit)continue;const g=groups.get(r.pair)||[];g.push(r);groups.set(r.pair,g)}document.getElementById('cases').innerHTML=[...groups].map(([n,rs])=>`<section><h2>${esc(rs[0].case)} <small>Pair ${n+1}</small></h2><p>${esc(rs[0].question)}</p><div class="pair">${rs.sort((a,b)=>a.effort==='low'?-1:b.effort==='low'?1:0).map(r=>`<article class="answer ${r.effort}"><h3>${esc(r.effort.toUpperCase())} · ${r.success?'Completed':'Failed'}</h3><div class="meta">Runner ${fmt(r.runner_seconds)}s · Tools ${fmt(r.tool_union_seconds)}s · ${r.search_calls} searches / ${r.read_calls} reads</div><p>${r.audit?esc(r.audit.verdict+': '+r.audit.note):'Factual audit pending'}</p><pre>${esc(r.answer || (r.error_code ? "No answer: " + r.error_code : "No durable answer"))}</pre><details><summary>Cited evidence (${r.citations.length})</summary>${r.citations.map(c=>`<p>[${c.number}] ${esc(c.source)}</p><pre>${esc(c.excerpt)}</pre>`).join('')}</details><details><summary>Search strategy</summary><pre>${esc(JSON.stringify(r.queries,null,2))}</pre></details></article>`).join('')}</div></section>`).join('')}
select.onchange=status.onchange=render;render();</script>""".replace("SUMMARY", totals)
        .replace("COMPARISON", comparison)
        .replace("DATA", data)
    )
    private_write(args.run / "report.html", page)
    compact = [
        {
            k: v
            for k, v in row.items()
            if k not in {"answer", "question", "queries", "citations"}
        }
        for row in rows
    ]
    private_write(args.run / "metrics.json", json.dumps(compact, indent=2))
    with (args.run / "metrics.csv").open("w") as stream:
        os.chmod(args.run / "metrics.csv", 0o600)
        writer = csv.DictWriter(
            stream, fieldnames=list(compact[0]) if compact else ["key"]
        )
        writer.writeheader()
        writer.writerows(compact)
    print(json.dumps({"completed_trials": len(rows), "summary": summary}))


if __name__ == "__main__":
    main()
