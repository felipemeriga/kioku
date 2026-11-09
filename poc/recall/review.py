"""Build a private evidence viewer and shareable aggregate report from the frozen POC run."""

import argparse
import json
from pathlib import Path

AUDIT = {
    "sdk": (
        "pass",
        "Identifies the SDK build and reported identification method; source is an assistant report, not independent verification.",
    ),
    "heap": (
        "limited",
        "Finds a 3 GiB decision, but history also contains a later 4 GiB configuration; top five excerpts do not reconcile scope and chronology.",
    ),
    "baseline": (
        "pass",
        "Recovers the measured baseline and appropriately avoids calling the plateau a proven unbounded leak.",
    ),
    "new-sdk": (
        "limited",
        "Finds the package assessment, but misses the original link attempt/results and correctly admits that limitation.",
    ),
    "rss": (
        "limited",
        "Retrieves the earlier disk incident and unproven-leak conclusion, but does not integrate the later memory experiment.",
    ),
    "memory-cap": (
        "pass",
        "Distinguishes Go runtime budget from total process RSS and a hard memory cap.",
    ),
    "latency": (
        "reject",
        "The answer borrows a citation retrieved for a different question in the same batch. Per-question source validation rejects it; isolate answer contexts.",
    ),
    "clock": (
        "pass",
        "Finds negative ages and wall/monotonic divergence; preserves uncertainty about suspension versus clock changes.",
    ),
    "disk": ("pass", "Does not turn disk saturation into proof of a memory leak."),
    "absent-db": (
        "pass",
        "Abstains from inventing a MongoDB-to-PostgreSQL migration despite unrelated PostgreSQL matches.",
    ),
    "absent-kernel": ("pass", "Abstains from inventing a production kernel fix."),
    "deployment": (
        "pass",
        "Does not treat mixed build-host experiments as proof of production deployment or a solved target.",
    ),
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--private", type=Path, required=True)
    args = parser.parse_args()
    private = args.private
    retrieval = json.loads((private / "retrieval.json").read_text())
    result = json.loads((private / "answers.json").read_text())
    reference = json.loads((private / "anchor-reference.json").read_text())
    usage = [result["planning_usage"], *result["answer_usage"]]
    for a in result["answers"]:
        a["audit"], a["audit_note"] = AUDIT[a["id"]]
    summary = {
        "sessions": 4,
        "records": 3354,
        "chunks": 23720,
        "snapshot_bytes": 25687384,
        "snapshot_sha256": result["snapshot_sha256"],
        "questions": len(retrieval),
        "manual_acceptable": sum(a["audit"] == "pass" for a in result["answers"]),
        "manual_limited": sum(a["audit"] == "limited" for a in result["answers"]),
        "manual_rejected": sum(a["audit"] == "reject" for a in result["answers"]),
        "citation_validation_pass": sum(
            a["citations_valid"] for a in result["answers"]
        ),
        "anchor_probe_cases": len(reference),
        "direct_anchor_hits": sum(
            any(e["event_id"] in reference.get(r["id"], []) for e in r["direct"])
            for r in retrieval
        ),
        "expanded_anchor_hits": sum(
            any(e["event_id"] in reference.get(r["id"], []) for e in r["expanded"])
            for r in retrieval
        ),
        "input_tokens_including_cache_creation": sum(
            u["usage"].get("input_tokens", 0)
            + u["usage"].get("cache_creation_input_tokens", 0)
            + u["usage"].get("cache_read_input_tokens", 0)
            for u in usage
        ),
        "output_tokens": sum(u["usage"].get("output_tokens", 0) for u in usage),
        "api_equivalent_usd_reported_by_cli": sum(
            u.get("total_cost_usd", 0) for u in usage
        ),
        "native_model_seconds": sum(u["elapsed_seconds"] for u in usage),
        "retrieval_ms_total": sum(r["retrieval_ms"] for r in retrieval),
        "cases": [
            {"id": a["id"], "audit": a["audit"], "note": a["audit_note"]}
            for a in result["answers"]
        ],
    }
    Path(__file__).with_name("summary.json").write_text(
        json.dumps(summary, indent=2) + "\n"
    )
    data = json.dumps(
        {"summary": summary, "retrieval": retrieval, "answers": result["answers"]}
    ).replace("<", "\\u003c")
    viewer = r"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Kioku · Recall POC</title><style>
*{box-sizing:border-box}body{margin:0;background:#090611;color:#f6f1fa;font:15px/1.6 system-ui,sans-serif}header{padding:24px 5vw;border-bottom:1px solid #493554}header b{color:#ff009d}main{max-width:1400px;margin:auto;padding:36px}h1{font-size:32px;line-height:1.2}p{max-width:85ch;color:#c1b2ce}nav{display:flex;gap:10px;flex-wrap:wrap}.stat{padding:12px 18px;background:#1c102c;border:1px solid #4a345f;border-radius:7px}.layout{display:grid;grid-template-columns:320px minmax(0,1fr);gap:24px;margin-top:30px}aside button{width:100%;text-align:left;margin:0 0 8px;padding:12px;background:#130c20;border:1px solid #473452;color:#d9cbe5;border-radius:6px;cursor:pointer}button:focus-visible{outline:2px solid #00e5f5;outline-offset:3px}button[aria-pressed=true]{border-color:#00d7ed;background:#25113a}article{background:#130c20;border:1px solid #493554;padding:26px;border-radius:8px;min-width:0}h2{font-size:22px;margin-top:0}.badge{color:#00e5dc}.note{padding:14px;border-left:3px solid #ffb64b;background:#251c18}.reject{border-color:#ff579b}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#090611;border:1px solid #3b2a4c;padding:16px;font:13px/1.6 ui-monospace,monospace}small{color:#a897ba}details{border-top:1px solid #493554;margin-top:18px;padding-top:14px}summary{cursor:pointer;color:#00e5f5}button.tab{background:#231032;color:inherit;border:1px solid #654b78;padding:8px 16px;cursor:pointer;margin-right:8px;border-radius:4px}@media(max-width:850px){main{padding:18px}.layout{grid-template-columns:1fr}aside{max-height:250px;overflow:auto}article{padding:18px}} </style>
<header><b>記 kioku</b> / Originals-only recall / Read-only POC</header><main><h1>Can an agent find what we already tried?</h1><p>Real archived originals. Natural-language questions. Lexical retrieval with optional agent reformulation. No journal index, maintained learnings, embeddings or production changes.</p><nav id="stats"></nav><p><small>November 2–6, 2026 • c360-lead • Four Codex sessions. Private snapshot; evidence below contains real source excerpts. Anchor hits measure topic discovery, not answer accuracy.</small></p><div class="layout"><aside id="questions"></aside><article id="detail"></article></div></main><script id="data" type="application/json">DATA</script><script>
const d=JSON.parse(document.getElementById('data').textContent);const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));let selected=d.answers[0].id,mode='expanded';
document.getElementById('stats').innerHTML=[`${d.summary.manual_acceptable}/12 acceptable in manual review`,`${d.summary.citation_validation_pass}/12 exact-citation checks`,`${d.summary.direct_anchor_hits} → ${d.summary.expanded_anchor_hits} / 9 topic probes`,`${d.summary.input_tokens_including_cache_creation.toLocaleString()} input tokens`].map(x=>`<div class="stat">${esc(x)}</div>`).join('');
function render(){document.getElementById('questions').innerHTML=d.retrieval.map(r=>`<button data-id="${esc(r.id)}" aria-pressed="${selected===r.id}">${esc(r.question)}</button>`).join('');const r=d.retrieval.find(x=>x.id===selected),a=d.answers.find(x=>x.id===selected);document.getElementById('detail').innerHTML=`<span class="badge">${esc(a.audit)} · model: ${esc(a.status)}</span><h2>${esc(r.question)}</h2><p class="note ${a.audit==='reject'?'reject':''}">${esc(a.audit_note)}</p><h3>Answer produced</h3><p>${esc(a.answer)}</p><h3>Agent search reformulations</h3><pre>${esc(r.queries.join('\n'))}</pre><h3>Retrieved originals</h3><button class="tab" data-mode="direct" aria-pressed="${mode==='direct'}">Direct question</button><button class="tab" data-mode="expanded" aria-pressed="${mode==='expanded'}">Reformulated searches</button>${r[mode].map((e,i)=>`<details><summary>${i+1}. ${esc(e.role)} · ${esc(e.event_at||'undated')} · ${esc(e.event_id.slice(0,12))}</summary><small>Session ${esc(e.session_id)}<br>Segment ${esc(e.object_id)}<br>Original byte range ${e.byte_offset}–${e.byte_offset+e.byte_length}; excerpt starts ${e.excerpt_offset} characters into decoded text.</small><pre>${esc(e.text)}</pre></details>`).join('')}<details><summary>Answer citation checks</summary><p>Exact quote validation: ${a.citations_valid?'passed':'FAILED — answer rejected'}</p>${a.citations.map(c=>`<small>${esc(c.event_id)}</small><pre>${esc(c.quote)}</pre>`).join('')}</details>`;}
document.getElementById('questions').addEventListener('click',e=>{const b=e.target.closest('[data-id]');if(b){selected=b.dataset.id;render()}});document.getElementById('detail').addEventListener('click',e=>{const b=e.target.closest('[data-mode]');if(b){mode=b.dataset.mode;render()}});render();
</script></html>""".replace("DATA", data)
    out = private / "review"
    out.mkdir(exist_ok=True, mode=0o700)
    (out / "index.html").write_text(viewer)
    print(json.dumps(summary, indent=2))
    print("Private interactive review:", out / "index.html")


if __name__ == "__main__":
    main()
