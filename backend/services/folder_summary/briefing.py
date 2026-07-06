"""Briefing schema + mechanical populators for repo folders.

A briefing has 8 fixed sections. Each section is a small structured
record with content + status + provenance so the UI editor and the
`update_folder_briefing_section` MCP tool can operate atomically on
one section at a time without stomping on user edits elsewhere.

Section shape:

    {
        "status": "auto" | "pinned" | "hybrid",
        "content": <section-specific structured payload>,
        "provenance": "auto" | "user_ui" | "agent_mcp",
        "updated_at": ISO 8601 string,
        "updated_by": free-form label ("mem0", "github_sync", email, api_key_id)
    }

Populators come in two flavors:
- **mechanical**: pure functions that read Supabase data and produce a
  section. No LLM. Fast. Idempotent. Used for preferences, activity,
  dependencies.
- **llm**: async functions that fetch raw material (README, manifests,
  etc. via GitHub raw API) and call Anthropic. Used for overview,
  architecture, important_files, how_it_runs, deployment. Landed in
  Phase 4.

Regen behavior:
- Sections with status=='pinned' are NEVER overwritten by auto-regen.
- status=='hybrid' means user notes are appended to auto content.
  (Phase 4 wires this; MVP treats hybrid == pinned.)
- Provenance is set on write. Auto writes leave `updated_by=null`; UI
  writes stamp the user email; MCP writes stamp the API key label.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Literal

log = logging.getLogger(__name__)

BRIEFING_SCHEMA_VERSION = 1

SectionStatus = Literal["auto", "pinned", "hybrid"]
Provenance = Literal["auto", "user_ui", "agent_mcp"]


# ── Section keys — fixed order for stable rendering ────────────────────────
SECTION_KEYS: list[str] = [
    "overview",
    "architecture",
    "preferences",
    "important_files",
    "how_it_runs",
    "deployment",
    "dependencies",
    "activity",
]


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def new_section(
    content: Any,
    *,
    status: SectionStatus = "auto",
    provenance: Provenance = "auto",
    updated_by: str | None = None,
) -> dict:
    return {
        "status": status,
        "content": content,
        "provenance": provenance,
        "updated_at": _now_iso(),
        "updated_by": updated_by,
    }


def empty_briefing() -> dict[str, dict]:
    """Skeleton briefing with every section marked auto + empty. Used as
    the base when a new repo hasn't had any populators run yet."""
    return {
        "overview": new_section({"purpose": "", "description": ""}),
        "architecture": new_section({
            "summary": "",
            "components": [],
            "data_flow": "",
        }),
        "preferences": new_section({"rules": []}),
        "important_files": new_section([]),
        "how_it_runs": new_section({
            "requirements": [],
            "local_dev": "",
        }),
        "deployment": new_section({
            "environments": [],
            "how_to_deploy": "",
            "ci_cd_notes": "",
        }),
        "dependencies": new_section({
            "runtime": [],
            "services": [],
        }),
        "activity": new_section({
            "recent_commits": [],
            "recent_prs": [],
            "recent_learnings": [],
        }),
    }


# ═══════════════════════════════════════════════════════════════════════
#  Mechanical populators — no LLM
# ═══════════════════════════════════════════════════════════════════════


def populate_preferences(sb, *, folder_id: str, user_id: str) -> dict:
    """Pull [preference]-category memories from Mem0 as verbatim rules.

    Cheap: uses the same fetch the orientation call already does.
    Returns a section dict (status=auto)."""
    from services.mem0_sync import get_client_for_folder  # local: avoid cycle
    rules: list[str] = []
    try:
        client = get_client_for_folder(sb, folder_id, user_id)
        if client:
            for m in client.list_eternal(limit=100):
                # Only [preference]-category entries — Mem0 filter API doesn't
                # let us filter by category directly, so we grep post-hoc.
                md = m.get("metadata") or {}
                if (md.get("category") or "").lower() != "preference":
                    continue
                text = (m.get("memory") or m.get("content") or "").strip()
                if text:
                    rules.append(text)
    except Exception:  # noqa: BLE001
        log.exception("preferences populator: mem0 fetch failed for %s", folder_id)
    return new_section({"rules": rules})


def populate_activity(sb, *, folder_id: str, user_id: str) -> dict:
    """Assemble recent commits/PRs/issues from github_sync docs +
    recent [finding]/[decision]/[session] memories from Mem0."""
    recent_commits: list[dict] = []
    recent_prs: list[dict] = []
    try:
        gh_rows = (
            sb.table("documents").select(
                "source_filename, source_type, metadata, content, created_at"
            )
            .eq("user_id", user_id)
            .eq("root_folder_id", folder_id)
            .in_("source_type", ["github_commit", "github_pr", "github_issue"])
            .order("created_at", desc=True)
            .limit(30)
            .execute()
            .data
            or []
        )
        for g in gh_rows:
            entry = {
                "kind": g.get("source_type"),
                "ref": g.get("source_filename"),
                "title": (g.get("metadata") or {}).get("title")
                        or (g.get("content") or "")[:120],
                "url": (g.get("metadata") or {}).get("url"),
                "created_at": g.get("created_at"),
            }
            if g.get("source_type") == "github_commit":
                recent_commits.append(entry)
            else:
                recent_prs.append(entry)
    except Exception:  # noqa: BLE001
        log.exception("activity populator: github docs fetch failed")

    recent_learnings: list[dict] = []
    try:
        from services.mem0_sync import get_client_for_folder
        client = get_client_for_folder(sb, folder_id, user_id)
        if client:
            for m in client.list_recent_episodic(limit=60):
                md = m.get("metadata") or {}
                cat = (md.get("category") or "").lower()
                if cat not in ("finding", "decision", "session"):
                    continue
                recent_learnings.append({
                    "category": cat,
                    "content": (m.get("memory") or m.get("content") or "")[:400],
                    "created_at": m.get("created_at") or md.get("created_at"),
                })
            recent_learnings.sort(
                key=lambda x: x.get("created_at") or "", reverse=True
            )
            recent_learnings = recent_learnings[:15]
    except Exception:  # noqa: BLE001
        log.exception("activity populator: mem0 fetch failed")

    return new_section({
        "recent_commits": recent_commits[:15],
        "recent_prs": recent_prs[:10],
        "recent_learnings": recent_learnings,
    })


# ── Dependency parsers ────────────────────────────────────────────────
_MANIFEST_TO_PARSER: dict[str, str] = {
    # relative file basename → parser key
    "package.json": "package_json",
    "pyproject.toml": "pyproject_toml",
    "requirements.txt": "requirements_txt",
    "Cargo.toml": "cargo_toml",
    "go.mod": "go_mod",
}


def _parse_package_json(text: str) -> dict:
    try:
        data = json.loads(text)
    except Exception:
        return {"runtime": [], "build": []}
    runtime = list((data.get("dependencies") or {}).keys())
    build = list((data.get("devDependencies") or {}).keys())
    return {"runtime": runtime, "build": build}


def _parse_pyproject_toml(text: str) -> dict:
    """Naive but works for uv/poetry/setuptools style manifests."""
    runtime: list[str] = []
    # [project] dependencies = [ "foo>=1", ... ]
    in_project = False
    in_deps = False
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            in_project = line == "[project]"
            in_deps = False
            continue
        if in_project and line.startswith("dependencies"):
            in_deps = True
            # single-line?
            m = re.search(r'dependencies\s*=\s*\[(.+)\]', line)
            if m:
                for tok in _extract_string_tokens(m.group(1)):
                    runtime.append(_dep_name(tok))
                in_deps = False
                continue
        elif in_deps:
            if "]" in line:
                for tok in _extract_string_tokens(line.split("]", 1)[0]):
                    runtime.append(_dep_name(tok))
                in_deps = False
            else:
                for tok in _extract_string_tokens(line):
                    runtime.append(_dep_name(tok))
    return {"runtime": [r for r in runtime if r]}


def _extract_string_tokens(text: str) -> list[str]:
    return re.findall(r'"([^"]+)"|\'([^\']+)\'', text) and \
           [a or b for a, b in re.findall(r'"([^"]+)"|\'([^\']+)\'', text)] or []


def _dep_name(spec: str) -> str:
    # 'foo>=1.2', 'foo[extra]', 'foo (>=1.2)' → 'foo'
    return re.split(r"[\[\s<>=!;\(]", spec, 1)[0].strip()


def _parse_requirements_txt(text: str) -> dict:
    runtime = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        name = _dep_name(line)
        if name:
            runtime.append(name)
    return {"runtime": runtime}


def _parse_cargo_toml(text: str) -> dict:
    runtime: list[str] = []
    in_deps = False
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            in_deps = line == "[dependencies]"
            continue
        if in_deps and "=" in line and not line.startswith("#"):
            name = line.split("=", 1)[0].strip()
            if name:
                runtime.append(name)
    return {"runtime": runtime}


def _parse_go_mod(text: str) -> dict:
    runtime: list[str] = []
    in_require = False
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("require ("):
            in_require = True
            continue
        if line == ")":
            in_require = False
            continue
        if line.startswith("require "):
            parts = line.split()
            if len(parts) >= 2:
                runtime.append(parts[1])
            continue
        if in_require and line and not line.startswith("//"):
            parts = line.split()
            if parts:
                runtime.append(parts[0])
    return {"runtime": runtime}


_PARSERS = {
    "package_json": _parse_package_json,
    "pyproject_toml": _parse_pyproject_toml,
    "requirements_txt": _parse_requirements_txt,
    "cargo_toml": _parse_cargo_toml,
    "go_mod": _parse_go_mod,
}


def populate_dependencies(sb, *, folder_id: str, user_id: str) -> dict:
    """Parse manifest files that have been ingested as documents in this
    folder. Works whether the file came via GitHub sync or a raw upload —
    we look for the basename.

    Returns a section with {runtime, services}. `services` is Phase 4
    territory (harder to detect — needs Dockerfile / docker-compose
    parsing). Phase 2 leaves it empty."""
    runtime: set[str] = set()
    try:
        for basename in _MANIFEST_TO_PARSER.keys():
            hits = (
                sb.table("documents").select("content, source_filename")
                .eq("user_id", user_id).eq("folder_id", folder_id)
                .ilike("source_filename", f"%{basename}")
                .limit(5).execute().data
                or []
            )
            for h in hits:
                parser = _PARSERS[_MANIFEST_TO_PARSER[basename]]
                parsed = parser(h.get("content") or "")
                for name in parsed.get("runtime", []):
                    if name:
                        runtime.add(name)
    except Exception:  # noqa: BLE001
        log.exception("dependencies populator: parse loop failed")

    return new_section({
        "runtime": sorted(runtime),
        "services": [],
    })


# ═══════════════════════════════════════════════════════════════════════
#  Merge — respect pinned sections during regen
# ═══════════════════════════════════════════════════════════════════════


def merge_briefing(*, existing: dict | None, refresh: dict) -> dict:
    """Return a new briefing where each section is either the pinned
    existing section (untouched) or the refreshed auto section.

    `existing` may be None on first population. Missing sections in
    either input use the empty skeleton so the shape is stable."""
    base = existing or empty_briefing()
    out: dict[str, dict] = {}
    for key in SECTION_KEYS:
        e = base.get(key)
        r = refresh.get(key)
        if e and (e.get("status") in ("pinned", "hybrid")):
            # Keep the user/agent's edit.
            out[key] = e
            continue
        # Fall back to the refresh; if refresh missing the key, keep empty.
        out[key] = r or e or empty_briefing()[key]
    return out


def generate_briefing_for_repo(sb, *, folder_id: str, user_id: str) -> dict:
    """Assemble the auto part of a briefing using ONLY mechanical
    populators. Fast; safe to call on every regen.

    Use generate_full_briefing_for_repo (async) for a first-time bootstrap
    or an explicit Full-mode regen — that also runs the 5 LLM populators.
    """
    _refresh_local_clone(sb, folder_id, user_id)
    briefing = empty_briefing()
    briefing["preferences"] = populate_preferences(sb, folder_id=folder_id, user_id=user_id)
    briefing["activity"] = populate_activity(sb, folder_id=folder_id, user_id=user_id)
    briefing["dependencies"] = populate_dependencies(sb, folder_id=folder_id, user_id=user_id)
    return briefing


def _refresh_local_clone(sb, folder_id: str, user_id: str) -> None:
    """Best-effort `git fetch` for the repo bound to this folder.

    Silent on any failure — populators degrade gracefully to stale data
    if the fetch times out or the clone is missing. Records
    `last_fetched_at` on success so the UI can surface staleness.
    """
    from pathlib import Path
    from datetime import datetime, timezone
    from services.github_sync.local_repo import fetch as _git_fetch

    try:
        cfg = (
            sb.table("github_sync_configs").select("id, local_clone_path")
            .eq("root_folder_id", folder_id).eq("user_id", user_id)
            .limit(1).execute().data
        )
    except Exception:  # noqa: BLE001
        return
    if not cfg:
        return
    row = cfg[0]
    clone = row.get("local_clone_path")
    if not clone or not Path(clone).exists():
        return
    if _git_fetch(Path(clone), timeout=30):
        try:
            sb.table("github_sync_configs").update({
                "last_fetched_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", row["id"]).execute()
        except Exception:  # noqa: BLE001
            pass


async def generate_full_briefing_for_repo(sb, *, folder_id: str, user_id: str) -> dict:
    """Full briefing including the 5 LLM populators. Fired on:
      - first-time briefing (no previous row exists), OR
      - explicit mode='full' regen from the user.

    Runs mechanical + LLM populators in parallel. Wall time ≈ slowest
    single Haiku call (~1.5-3s) rather than the sum.
    """
    from services.folder_summary.llm_populators import run_llm_populators  # local: cycle-free

    _refresh_local_clone(sb, folder_id, user_id)
    briefing = empty_briefing()
    # Mechanical populators are cheap — run inline first so the rest of
    # the merge logic sees them in place.
    briefing["preferences"] = populate_preferences(sb, folder_id=folder_id, user_id=user_id)
    briefing["activity"] = populate_activity(sb, folder_id=folder_id, user_id=user_id)
    briefing["dependencies"] = populate_dependencies(sb, folder_id=folder_id, user_id=user_id)
    # LLM populators — fan out concurrently.
    llm = await run_llm_populators(sb, folder_id=folder_id, user_id=user_id)
    briefing["overview"] = llm.overview
    briefing["architecture"] = llm.architecture
    briefing["important_files"] = llm.important_files
    briefing["how_it_runs"] = llm.how_it_runs
    briefing["deployment"] = llm.deployment
    return briefing
