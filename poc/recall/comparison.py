"""Preserve baseline results and add a private, inspectable version comparison."""

import argparse
import json
from pathlib import Path
import re


def usage_total(usages):
    return {
        "input_tokens": sum(
            sum(
                u["usage"].get(k, 0)
                for k in [
                    "input_tokens",
                    "cache_creation_input_tokens",
                    "cache_read_input_tokens",
                ]
            )
            for u in usages
        ),
        "output_tokens": sum(u["usage"].get("output_tokens", 0) for u in usages),
        "api_equivalent_usd": sum(u.get("total_cost_usd", 0) for u in usages),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--private", type=Path, required=True)
    private = parser.parse_args().private
    page = (private / "review" / "index.html").read_text()
    base = json.loads(
        re.search(
            r'<script id="data" type="application/json">(.*?)</script>', page, re.S
        )[1]
    )
    # Baseline remains in its original artifacts and summary.json.
    versions = {"Baseline": base}
    comparison = {}
    for name, folder in [
        ("Improved · same questions", "v2-development"),
        ("Improved · fresh questions", "v2-holdout"),
    ]:
        result = json.loads((private / folder / "answers.json").read_text())
        packets = json.loads((private / folder / "packets.json").read_text())
        answers = []
        for a in result["answers"]:
            limited = folder == "v2-development" and a["id"] in ["heap", "new-sdk"]
            note = (
                "Still incomplete: relevant context was retrieved, but the final scoped configuration or original link-result evidence is missing."
                if limited
                else "Manual review: useful and appropriately qualified for the supplied evidence. Source spans are copied deterministically; this does not independently verify every claim."
            )
            answers.append(
                {
                    **a,
                    "audit": "limited" if limited else "pass",
                    "audit_note": note,
                    "citations": [
                        {"event_id": s["event_id"], "quote": s["text"]}
                        for s in a["resolved_citations"]
                    ],
                }
            )
        old_by_id = {r["id"]: r for r in base["retrieval"]}
        retrieval = [
            {
                "id": r["id"],
                "question": r["question"],
                "queries": old_by_id.get(r["id"], {}).get(
                    "queries",
                    [
                        "Fresh-question reformulations are retained in the private planner trace."
                    ],
                ),
                "direct": old_by_id.get(r["id"], {}).get("direct", []),
                "expanded": r["sources"],
            }
            for r in packets
        ]
        usages = [a["usage"] for a in result["answers"]]
        if folder == "v2-holdout":
            usages.append(
                json.loads((private / folder / "planning-usage.json").read_text())
            )
        totals = usage_total(usages)
        acceptable = sum(a["audit"] == "pass" for a in answers)
        summary = {
            "improved": True,
            "manual_acceptable": acceptable,
            "citation_validation_pass": result["citations_valid"],
            "input_tokens_including_cache_creation": totals["input_tokens"],
        }
        versions[name] = {
            "summary": summary,
            "answers": answers,
            "retrieval": retrieval,
        }
        comparison[folder] = {
            "questions": len(answers),
            "improved": True,
            "manual_acceptable": acceptable,
            "manual_limited": len(answers) - acceptable,
            "valid_source_references": result["citations_valid"],
            "budget_characters": result["evidence_character_budget"],
            **totals,
        }
    Path(__file__).with_name("improvements-summary.json").write_text(
        json.dumps(comparison, indent=2) + "\n"
    )
    data = json.dumps({"versions": versions}).replace("<", "\\u003c")
    page = re.sub(
        r'(<script id="data" type="application/json">).*?(</script>)',
        lambda m: m[1] + data + m[2],
        page,
        flags=re.S,
    )
    page = page.replace(
        '<nav id="stats">',
        '<label for="version">Compare retrieval versions </label><select id="version" style="padding:10px;background:#21102f;color:white;border:1px solid #77548c;margin:12px 0"></select><nav id="stats">',
    )
    page = page.replace(
        "const d=JSON.parse(document.getElementById('data').textContent);",
        "const versions=JSON.parse(document.getElementById('data').textContent).versions;let d=versions['Improved · same questions'];const selector=document.getElementById('version');Object.keys(versions).forEach(key=>{const o=document.createElement('option');o.value=key;o.textContent=key;selector.appendChild(o)});selector.value='Improved · same questions';",
    )
    original = re.search(r"document.getElementById\('stats'\).innerHTML=.*?;\n", page)[
        0
    ]
    page = page.replace(original, "")
    stats = "document.getElementById('stats').innerHTML=[`${d.summary.manual_acceptable}/${d.answers.length} acceptable in manual review`,`${d.summary.citation_validation_pass}/${d.answers.length} valid source references`,`${d.summary.input_tokens_including_cache_creation.toLocaleString()} input tokens`].map(x=>`<div class=\"stat\">${esc(x)}</div>`).join('');"
    page = page.replace("function render(){", "function render(){" + stats)
    page = page.replace(
        "render();\n</script>",
        "selector.addEventListener('change',()=>{d=versions[selector.value];selected=d.answers[0].id;mode='expanded';render()});render();\n</script>",
    )
    page = page.replace("Record text", "Record text")
    page = page.replace(
        "</p><h3>Agent search reformulations</h3>",
        "</p>${a.limitations?.length?`<h3>Evidence limits</h3><ul>${a.limitations.map(x=>`<li>${esc(x)}</li>`).join('')}</ul>`:''}<h3>Agent search reformulations</h3>",
    )
    page = page.replace(
        "Reformulated searches</button>",
        "${d.summary.improved?'Expanded context':'Reformulated searches'}</button>",
    )
    page = page.replace(
        'class="tab" data-mode="direct"',
        'class="tab" data-mode="direct" ${r.direct.length?\'\':\'disabled title="No direct baseline was run for fresh questions"\'}',
    )
    (private / "review" / "comparison.html").write_text(page)
    print(json.dumps(comparison, indent=2))


if __name__ == "__main__":
    main()
