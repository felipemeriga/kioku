"""Edge-case accuracy + scope-isolation eval — REAL pipeline, no mocks.

Runs against the persistent kioku-eval-lab corpus (seed with eval.lab_seed)
plus the user's real code + document corpus. Two families:

EDGE — adversarial retrieval accuracy on the lab corpus:
  E1 polysemy      A birdwatching guide that literally says "watcher",
                   "06:00", "18:00" must NOT crowd out the repo-watcher
                   material for a repo-watcher question.
  E2 drift         When a lab doc (watcher-drift-note: "hourly") CONTRADICTS
                   real code (watcher.py: twice daily), the blend surfaces
                   BOTH so the conflict is visible.
  E3 buried        A single-sentence answer (Friday deploy freeze) buried in
                   a long handbook is retrievable.
  E4 cross-lingual An English question hits a Portuguese-only policy doc.
  E5 supersede     "Current" latency budget returns BOTH v1 and v2 so the
                   model can resolve the supersession.
  E6 pseudo-vs-real A behavioral code query ranks the real implementation
                   above a look-alike pseudo-code SPEC doc.

SCOPE — retrieval never leaks across roots:
  S1 cosm scope    A cosm code query returns only cosm-repo code; no kioku
                   code, no lab docs.
  S2 kioku scope   A kioku code query returns only kioku code; no cosm code,
                   no lab docs.
  S3 lab scope     A code-flavored query in the (code-free) lab root returns
                   ZERO code — the blend respects scope, never reaching into
                   kioku/cosm.
  S4 no doc leak   A lab-only term, searched in cosm scope, returns no lab
                   doc.

Run inside the backend environment / container (seed first):
    python -m eval.lab_seed <user_id>
    python -m eval.edge_lab <user_id>
Exits 0 when all cases pass, 1 otherwise.
"""

from __future__ import annotations

import sys

from db.client import get_supabase
from services.embeddings import embed_query
from services.scope import descendant_folder_ids
from services.search import search_documents

LAB_ROOT_NAME = "kioku-eval-lab"

LAB_DOC_NAMES = {
    "birdwatching-guide.md",
    "codename-glossary.md",
    "latency-budget-v1.md",
    "latency-budget-v2.md",
    "onboarding-handbook.md",
    "politica-de-ferias.md",
    "pseudo-backoff-spec.md",
    "sla-table.md",
    "watcher-drift-note.md",
}


def _resolve(sb, user_id: str, name: str, parent: str | None = None) -> str | None:
    q = sb.table("folders").select("id").eq("user_id", user_id).eq("name", name)
    q = q.is_("parent_id", "null") if parent is None else q.eq("parent_id", parent)
    rows = q.execute().data or []
    return rows[0]["id"] if rows else None


def _search(user_id: str, query: str, folder_ids: list[str] | None = None) -> list[dict]:
    return search_documents(
        embed_query(query),
        query_text=query,
        user_id=user_id,
        fast_mode=True,
        top_k=8,
        folder_ids=folder_ids,
    )


def _is_code(r: dict) -> bool:
    return r.get("source_type") == "code"


def _src(r: dict) -> str:
    return (r.get("metadata") or {}).get("source_filename", "")


def _folder(r: dict) -> str | None:
    return (r.get("metadata") or {}).get("folder_id")


def _describe(r: dict) -> str:
    return f"{'code' if _is_code(r) else 'doc'}:{_src(r)}"


def _rank_doc(results: list[dict], name: str) -> int | None:
    for i, r in enumerate(results):
        if not _is_code(r) and _src(r) == name:
            return i
    return None


def _rank_code_file(results: list[dict], fragment: str) -> int | None:
    for i, r in enumerate(results):
        if _is_code(r) and fragment in _src(r):
            return i
    return None


def _report(label: str, ok: bool, detail: str) -> bool:
    print(f"{'PASS' if ok else 'FAIL'}  {label}: {detail}")
    return ok


def run(user_id: str) -> int:
    sb = get_supabase()
    stats = {"fail": 0}

    def check(label: str, ok: bool, detail: str) -> None:
        if not _report(label, ok, detail):
            stats["fail"] += 1

    lab = _resolve(sb, user_id, LAB_ROOT_NAME)
    cosm = _resolve(sb, user_id, "cosm")
    personal = _resolve(sb, user_id, "personal")
    if not lab:
        print(f"lab root {LAB_ROOT_NAME!r} not found — run `python -m eval.lab_seed {user_id}`")
        return 2
    lab_ids = descendant_folder_ids(sb, lab, user_id)
    cosm_ids = descendant_folder_ids(sb, cosm, user_id) if cosm else []
    # kioku repo lives at personal/repositories/kioku
    kioku_ids: list[str] = []
    if personal:
        repos = _resolve(sb, user_id, "repositories", personal)
        kioku = _resolve(sb, user_id, "kioku", repos) if repos else None
        kioku_ids = descendant_folder_ids(sb, kioku, user_id) if kioku else []

    # ── EDGE ──────────────────────────────────────────────────────────
    # E1 polysemy: repo-watcher question, birdwatching must not take top-3.
    r = _search(user_id, "how often does the repo watcher poll for changes?")
    top4 = [_describe(x) for x in r[:4]]
    drift_at = _rank_doc(r, "watcher-drift-note.md")
    watcher_code_at = _rank_code_file(r, "watcher/watcher.py")
    watcher_present = drift_at is not None or watcher_code_at is not None
    bird_top3 = any(_src(x) == "birdwatching-guide.md" for x in r[:3])
    ok = watcher_present and not bird_top3
    check("E1 polysemy", ok, f"watcher={watcher_present} bird_top3={bird_top3} | {top4}")

    # E2 drift: doc (hourly) and code (twice daily) both surface.
    ok = drift_at is not None and watcher_code_at is not None
    check("E2 drift-doc+code", ok, f"drift_doc@{drift_at} watcher_code@{watcher_code_at}")

    # E3 buried: Friday freeze answer in the long handbook (lab scope).
    r = _search(user_id, "when does the production deploy freeze happen?", lab_ids)
    hb_at = _rank_doc(r, "onboarding-handbook.md")
    ok = hb_at == 0
    check("E3 buried-answer", ok, f"handbook@{hb_at} | {[_describe(x) for x in r[:3]]}")

    # E4 cross-lingual: EN query → PT doc.
    r = _search(user_id, "how many vacation days per year does the policy grant?", lab_ids)
    pt_at = _rank_doc(r, "politica-de-ferias.md")
    ok = pt_at == 0
    check("E4 cross-lingual", ok, f"pt_doc@{pt_at} | {[_describe(x) for x in r[:3]]}")

    # E5 supersede: both v1 and v2 present.
    r = _search(user_id, "what is the current ingestion latency budget end to end?", lab_ids)
    v1_at = _rank_doc(r, "latency-budget-v1.md")
    v2_at = _rank_doc(r, "latency-budget-v2.md")
    ok = v1_at is not None and v2_at is not None
    check("E5 supersede-both-versions", ok, f"v1@{v1_at} v2@{v2_at}")

    # E6 pseudo-vs-real: behavioral query ranks real code above the spec doc.
    r = _search(user_id, "reconnect with exponential backoff after the connection drops")
    real_at = _rank_code_file(r, "ResilientEventSource")
    spec_at = _rank_doc(r, "pseudo-backoff-spec.md")
    ok = real_at is not None and (spec_at is None or real_at < spec_at)
    check("E6 real-code-beats-pseudo-spec", ok, f"real@{real_at} spec@{spec_at}")

    # ── SCOPE ─────────────────────────────────────────────────────────
    # S1 cosm scope: only cosm-repo code, no kioku code, no lab docs.
    if cosm_ids:
        r = _search(user_id, "where do we render lead scoring in the UI", cosm_ids)
        code_hits = [x for x in r if _is_code(x)]
        oos = [_src(x) for x in code_hits if _folder(x) not in cosm_ids]
        leak = [_src(x) for x in r if _src(x) in LAB_DOC_NAMES]
        ok = bool(code_hits) and not oos and not leak
        check("S1 cosm-scope-isolated", ok, f"n={len(code_hits)} oos={oos} leak={leak}")
    else:
        print("SKIP  S1 cosm-scope — no cosm root")

    # S2 kioku scope: only kioku code, no cosm code, no lab docs.
    if kioku_ids:
        r = _search(user_id, "how does recency decay ranking work in retrieval", kioku_ids)
        code_hits = [x for x in r if _is_code(x)]
        oos = [_src(x) for x in code_hits if _folder(x) not in kioku_ids]
        leak = [_src(x) for x in r if _src(x) in LAB_DOC_NAMES]
        ok = bool(code_hits) and not oos and not leak
        check("S2 kioku-scope-isolated", ok, f"n={len(code_hits)} oos={oos} leak={leak}")
    else:
        print("SKIP  S2 kioku-scope — no kioku repo")

    # S3 lab scope: code-flavored query returns ZERO code (lab has none).
    r = _search(user_id, "exponential backoff retry with jitter implementation", lab_ids)
    code_hits = [x for x in r if _is_code(x)]
    ok = not code_hits and bool(r)
    check("S3 lab-scope-no-code-leak", ok, f"n_code={len(code_hits)}")

    # S4 no doc leak: a lab-only term in cosm scope returns no lab doc.
    if cosm_ids:
        r = _search(user_id, "employee vacation policy days per year", cosm_ids)
        leak = [_src(x) for x in r if _src(x) in LAB_DOC_NAMES]
        ok = not leak
        check("S4 no-lab-doc-leak-into-cosm", ok, f"leak={leak}")

    failures = stats["fail"]
    print(f"\n{'ALL CASES PASS' if failures == 0 else f'{failures} FAILURE(S)'}")
    return 1 if failures else 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python -m eval.edge_lab <user_id>")
        sys.exit(2)
    sys.exit(run(sys.argv[1]))
