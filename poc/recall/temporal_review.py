"""Add the temporal benchmark and evidence timeline to the private comparison."""

import argparse
import json
from pathlib import Path
import re


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--private", type=Path, required=True)
    private = parser.parse_args().private
    files = list(private.glob("v3-temporal-*/results.json"))
    path = max(files, key=lambda f: f.stat().st_mtime)
    result = json.loads(path.read_text())
    items = result["results"]
    page = (private / "review" / "comparison.html").read_text()
    data = json.loads(
        re.search(
            r'<script id="data" type="application/json">(.*?)</script>', page, re.S
        )[1]
    )
    answers = []
    retrieval = []
    for item in items:
        a = item["answer"]
        sources = item["sources"]
        answers.append(
            {
                **a,
                "audit": "time scoped" if a["citations_valid"] else "reject",
                "audit_note": "Record-time filtering is enforced before retrieval. A note recorded later may describe an older event. Source resolution does not independently verify the model’s interpretation.",
                "citations": [
                    {"event_id": s["event_id"], "quote": s["text"]}
                    for s in a.get("resolved_citations", [])
                ],
                "limitations": [
                    f"Requested record-time interval: {item['plan'].get('start_date') or 'earliest archived record'} through {item['plan'].get('end_date') or 'latest archived record'} ({result['timezone']}).",
                    *a.get("limitations", []),
                ],
            }
        )
        retrieval.append(
            {
                "id": item["id"],
                "question": item["question"],
                "queries": item["plan"]["queries"],
                "direct": [],
                "expanded": [{**s, "event_at": s["recorded_at"]} for s in sources],
            }
        )
    summary = {
        "temporal": True,
        "questions": len(items),
        "date_scope_matches": sum(
            i.get("date_scope_matches_expected", False) for i in items
        ),
        "citation_validation_pass": sum(i["answer"]["citations_valid"] for i in items),
        "no_future_records": all(
            all(
                (
                    i["plan"].get("end_date") is None
                    or s["recorded_local"][:10] <= i["plan"]["end_date"]
                )
                and (
                    i["plan"].get("start_date") is None
                    or s["recorded_local"][:10] >= i["plan"]["start_date"]
                )
                for s in i["sources"]
            )
            for i in items
        ),
    }
    data["versions"]["Temporal · time-aware"] = {
        "summary": summary,
        "answers": answers,
        "retrieval": retrieval,
    }
    encoded = json.dumps(data).replace("<", "\\u003c")
    page = re.sub(
        r'(<script id="data" type="application/json">).*?(</script>)',
        lambda m: m[1] + encoded + m[2],
        page,
        flags=re.S,
    )
    page = page.replace(
        "let d=versions['Improved · same questions']",
        "let d=versions['Temporal · time-aware']",
    ).replace(
        "selector.value='Improved · same questions'",
        "selector.value='Temporal · time-aware'",
    )
    old = "[`${d.summary.manual_acceptable}/${d.answers.length} acceptable in manual review`,`${d.summary.citation_validation_pass}/${d.answers.length} valid source references`,`${d.summary.input_tokens_including_cache_creation.toLocaleString()} input tokens`]"
    new = (
        "(d.summary.temporal?[`${d.summary.date_scope_matches}/${d.answers.length} date scopes interpreted correctly`,`${d.summary.citation_validation_pass}/${d.answers.length} valid source references`,'Record time ≠ described event time']:"
        + old
        + ")"
    )
    page = page.replace(old, new)
    marker = "<h3>Agent search reformulations</h3>"
    timeline = """${a.timeline?.length?`<h3>Recorded history</h3>${a.timeline.map(step=>`<section class="note"><strong>${esc(step.recorded_at)} · recorded (UTC)</strong><p>${esc(step.description)}</p><small>Described event time: ${esc(step.described_event_time||'unknown')}<br>Sources: ${esc(step.citations.join(', '))}</small></section>`).join('')}`:''}"""
    page = page.replace(marker, timeline + marker)
    page = page.replace(
        "${i+1}. ${esc(e.role)}", "${i+1}. ${esc(e.source_id||'')} ${esc(e.role)}"
    )
    (private / "review" / "temporal.html").write_text(page)
    Path(__file__).with_name("temporal-summary.json").write_text(
        json.dumps(summary, indent=2) + "\n"
    )
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
