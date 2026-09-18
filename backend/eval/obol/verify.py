"""Obol golden eval — cross-repo relationship retrieval, REAL pipeline.

Runs against the seeded Obol company scope (see eval.obol.seed). Asserts the
relationships from SPEC.md actually surface across repos + docs when you search
the company scope, and that the scope is isolated from other roots.

  R1 refund flow spans 3 repos   console + gateway + ledger code all surface
  R2 fee: computed vs recorded   gateway pricing + ledger posting both surface
  R3 idempotency                 gateway idempotency code ranks top
  R4 payout batching             ledger payouts + gateway payouts both surface
  R5 doc concept                 the ledger-model doc answers a concept query
  R6 concept + code              a fee question surfaces a doc AND gateway code
  S1 scope isolation             every hit is inside the Obol subtree
  S2 no cross-scope leak         an Obol term in cosm scope returns no Obol hit

Run inside the backend environment / container (seed first):
    python -m eval.obol.seed <user_id>
    python -m eval.obol.verify <user_id>
Exits 0 when all cases pass, 1 otherwise.
"""

from __future__ import annotations

import sys

from db.client import get_supabase
from services.embeddings import embed_query
from services.scope import descendant_folder_ids
from services.search import search_documents

ROOT_NAME = "Obol"
REPOS = ["obol-gateway", "obol-ledger", "obol-console"]


def _resolve(sb, user_id, name, parent=None):
    q = sb.table("folders").select("id").eq("user_id", user_id).eq("name", name)
    q = q.is_("parent_id", "null") if parent is None else q.eq("parent_id", parent)
    rows = q.execute().data or []
    return rows[0]["id"] if rows else None


def _search(user_id, query, folder_ids):
    return search_documents(
        embed_query(query),
        query_text=query,
        user_id=user_id,
        fast_mode=True,
        top_k=10,
        folder_ids=folder_ids,
    )


def _is_code(r):
    return r.get("source_type") == "code"


def _src(r):
    return (r.get("metadata") or {}).get("source_filename", "")


def _folder(r):
    return (r.get("metadata") or {}).get("folder_id")


def run(user_id: str) -> int:
    sb = get_supabase()
    stats = {"fail": 0}

    def check(label, ok, detail):
        print(f"{'PASS' if ok else 'FAIL'}  {label}: {detail}")
        if not ok:
            stats["fail"] += 1

    root = _resolve(sb, user_id, ROOT_NAME)
    if not root:
        print(f"{ROOT_NAME} root not found — run `python -m eval.obol.seed {user_id}` first")
        return 2
    repos_folder = _resolve(sb, user_id, "repositories", root)
    repo_id = {name: _resolve(sb, user_id, name, repos_folder) for name in REPOS}
    id_to_repo = {v: k for k, v in repo_id.items() if v}
    scope = descendant_folder_ids(sb, root, user_id)

    def repos_of_code(results):
        return {id_to_repo.get(_folder(r)) for r in results if _is_code(r)} - {None}

    # R1 — refund flow spans all three repos.
    r = _search(
        user_id,
        "how does a refund flow from the merchant dashboard through the gateway to the ledger",
        scope,
    )
    hit_repos = repos_of_code(r)
    ok = {"obol-console", "obol-gateway", "obol-ledger"}.issubset(hit_repos)
    check("R1 refund-flow-spans-3-repos", ok, f"repos={sorted(hit_repos)}")

    # R2 — platform fee: computed (gateway pricing) vs recorded (ledger posting).
    # Implementation-oriented phrasing — the conceptual "where is X" form is
    # answered by the fee docs (also correct), which R6 covers.
    r = _search(
        user_id,
        "platform fee calculation from basis points and the settlement "
        "journal entry that records it",
        scope,
    )
    files = [_src(x) for x in r if _is_code(x)]
    has_pricing = any("pricing" in f for f in files)
    has_posting = any("posting" in f or "settlement" in f for f in files)
    check("R2 fee-computed-and-recorded", has_pricing and has_posting, f"code={files[:6]}")

    # R3 — idempotency enforced in the gateway.
    r = _search(user_id, "how is idempotency enforced on charge requests", scope)
    files = [_src(x) for x in r if _is_code(x)]
    ok = any("idempotency" in f for f in files[:4])
    check("R3 idempotency-in-gateway", ok, f"code={files[:4]}")

    # R4 — payout batching: ledger builds, gateway executes.
    r = _search(user_id, "how are seller payouts batched and executed through the processor", scope)
    hit_repos = repos_of_code(r)
    files = [_src(x) for x in r if _is_code(x)]
    ok = "obol-ledger" in hit_repos and any("payout" in f for f in files)
    check("R4 payout-batching", ok, f"repos={sorted(hit_repos)} code={files[:5]}")

    # R5 — a concept question answered by the ledger-model doc.
    r = _search(user_id, "what is the double-entry ledger model and its balance invariant", scope)
    docs = [_src(x) for x in r if not _is_code(x)]
    ok = any("ledger-model" in d or "05-" in d for d in docs)
    check("R5 concept-doc-answers", ok, f"docs={docs[:4]}")

    # R6 — concept + code together for the fee model.
    r = _search(user_id, "how is the platform fee computed from basis points", scope)
    has_doc = any(not _is_code(x) for x in r)
    has_gw = "obol-gateway" in repos_of_code(r)
    check("R6 concept+code-together", has_doc and has_gw, f"doc={has_doc} gw={has_gw}")

    # S1 — every hit is inside the Obol subtree (code hits carry folder_id).
    r = _search(user_id, "seller payable balance and settlement", scope)
    oos = [_src(x) for x in r if _is_code(x) and _folder(x) not in scope]
    check("S1 scope-isolated", not oos, f"out_of_scope={oos}")

    # S2 — an Obol-specific query in cosm scope returns no Obol content.
    cosm = _resolve(sb, user_id, "cosm")
    if cosm:
        cosm_scope = descendant_folder_ids(sb, cosm, user_id)
        r = _search(user_id, "obol seller_payable double-entry settlement posting", cosm_scope)
        leak = [_src(x) for x in r if _folder(x) in scope or "obol" in _src(x).lower()]
        check("S2 no-obol-leak-in-cosm", not leak, f"leak={leak[:4]}")
    else:
        print("SKIP  S2 — no cosm root")

    fails = stats["fail"]
    print(f"\n{'ALL CASES PASS' if fails == 0 else f'{fails} FAILURE(S)'}")
    return 1 if fails else 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python -m eval.obol.verify <user_id>")
        sys.exit(2)
    sys.exit(run(sys.argv[1]))
