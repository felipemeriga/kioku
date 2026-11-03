"""Read-only real Kioku source snapshot questions, with deterministic source checks."""

import json
import shutil
from pathlib import Path

from native import NativeRunner
from soak import HERE, mcp


def main():
    runtime = Path("/private/tmp/kioku-claude-poc-runtime/complex")
    corpus = runtime / "source"
    files = [
        "backend/services/rag.py",
        "backend/services/llm.py",
        "backend/services/usage_ledger.py",
        "backend/services/query.py",
        "backend/services/tools.py",
        "backend/routes/mihari.py",
        "backend/services/repo_learnings.py",
        "backend/routes/chat.py",
        "mihari/mihari.py",
    ]
    for name in files:
        target = corpus / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(HERE.parents[1] / name, target)
    runner = NativeRunner(runtime / "calls")
    schema = {
        "type": "object",
        "properties": {
            "answer": {"type": "string"},
            "sources": {"type": "array", "items": {"type": "string"}},
            "unknowns": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["answer", "sources", "unknowns"],
        "additionalProperties": False,
    }
    questions = [
        (
            "stream-disconnect",
            "How does chat generation continue after browser disconnect, and where is the assistant answer persisted? Trace stream_rag_response and _generate_and_save.",
            ["thread", "messages"],
        ),
        (
            "cache-billing",
            "Which distinct token counters are used to price a call? Explain cache write TTLs and reads using usage_row.",
            ["cache", "1.25", "0.1"],
        ),
        (
            "maintenance-selection",
            "How does Mihari choose which briefing sections to update after commits, and can detailed documentation be updated? Trace review_new_commits and review-plan.",
            ["documentation", "activity"],
        ),
        (
            "learning-evidence",
            "What prevents an unsupported proposed learning from becoming a repository fact? Trace apply_updates and _extract.",
            ["quote", "source"],
        ),
    ]
    results = []
    session = None
    for model in ["haiku", "sonnet"]:
        for label, question, terms in questions:
            prompt = (
                "Use both knowledge_base_search and code_graph_lookup to inspect this real Kioku source snapshot. "
                "Answer in English under200words. Give source paths exactly as returned, without line suffixes. "
                "Do not invent claims or paths; list unknowns.\n" + question
            )
            record = runner.call(
                f"complex-{model}-{label}",
                prompt,
                model=model,
                mcp=mcp(corpus),
                schema=schema,
                persist=False,
            )
            body = record.get("structured_output") or {}
            sources = body.get("sources") or []
            results.append(
                {
                    "label": label,
                    "model": model,
                    "call_id": record["id"],
                    "returncode": record["returncode"],
                    "sources_exist": bool(sources)
                    and all((corpus / path).is_file() for path in sources),
                    "expected_concepts_present": all(
                        term.lower() in body.get("answer", "").lower() for term in terms
                    ),
                    "sources": sources,
                    "answer": body.get("answer"),
                    "elapsed_s": record["elapsed_s"],
                    "list_cost_usd": record["list_cost_usd"],
                }
            )
            (runtime / "checks.json").write_text(json.dumps(results, indent=2))
            print(json.dumps(results[-1]), flush=True)
    # Explicit stateful followup on a real code question, separate from fixture recall.
    first = runner.call(
        "complex-stateful-initial",
        "Use the tools to explain usage_row cache-write pricing briefly.",
        mcp=mcp(corpus),
    )
    session = first.get("session_id")
    second = runner.call(
        "complex-stateful-followup",
        "Given that explanation, why would recording only input_tokens undercount cost? Answer briefly.",
        resume=session,
        mcp=mcp(corpus),
    )
    print(
        json.dumps(
            {"stateful_followup_call": second["id"], "returncode": second["returncode"]}
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
