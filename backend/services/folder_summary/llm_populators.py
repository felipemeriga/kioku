"""LLM populators for the auto-generated briefing sections that aren't
purely mechanical.

Five populators, one per section:

    - overview          : README + top-level manifests
    - architecture      : README + directory listing + key entry points
    - important_files   : README + directory listing
    - how_it_runs       : README + package.json/Makefile/docker-compose
    - deployment        : Dockerfile + .github/workflows + deploy/ + README

Each populator:
    1. Fetches the material it needs via the existing GitHub API client
       (no clone). Missing files are silently skipped — a repo without
       a Dockerfile just gets an empty deployment section.
    2. Calls Anthropic with a focused tool schema matching the section's
       shape (see services/folder_summary/briefing.py for shapes).
    3. Returns a section dict with status='auto', provenance='auto'.

All five are fired in parallel via asyncio + a ThreadPoolExecutor so a
full briefing regen finishes in the wall-time of the slowest single call
(~2s), not the sum. Failures are per-section — one populator failing
doesn't take down the others.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any

from services.folder_summary.briefing import new_section
from services.crypto import decrypt_secret
from services.github_sync import GitHubClient
from services.llm import Task, complete

log = logging.getLogger(__name__)

# Keep small — each LLM call adds latency. 800 is enough for a rich
# structured section without producing runaway prose.
_MAX_TOKENS = 800


# ── Section tool schemas — one per populator ─────────────────────────────

_OVERVIEW_TOOL: dict[str, Any] = {
    "name": "emit_overview",
    "description": "Emit the overview section of the repo briefing.",
    "input_schema": {
        "type": "object",
        "required": ["purpose", "description"],
        "properties": {
            "purpose": {
                "type": "string",
                "description": "One sentence — what this repo produces or does.",
            },
            "description": {
                "type": "string",
                "description": "2-4 sentence what/why. Real context, not marketing.",
            },
        },
    },
}

_ARCHITECTURE_TOOL: dict[str, Any] = {
    "name": "emit_architecture",
    "description": "Emit the architecture section of the repo briefing.",
    "input_schema": {
        "type": "object",
        "required": ["summary", "components", "data_flow"],
        "properties": {
            "summary": {
                "type": "string",
                "description": "How the system fits together — subsystems + boundaries.",
            },
            "components": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["name", "role", "path"],
                    "properties": {
                        "name": {"type": "string"},
                        "role": {"type": "string"},
                        "path": {"type": "string"},
                    },
                },
                "description": "3-8 major components. Path is repo-relative.",
            },
            "data_flow": {
                "type": "string",
                "description": (
                    "One paragraph describing the primary data flow through the "
                    "system (user input → processing → storage / output)."
                ),
            },
        },
    },
}

_IMPORTANT_FILES_TOOL: dict[str, Any] = {
    "name": "emit_important_files",
    "description": "Emit the important_files section — files a fresh agent should open first.",
    "input_schema": {
        "type": "object",
        "required": ["files"],
        "properties": {
            "files": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["path", "role", "why"],
                    "properties": {
                        "path": {"type": "string"},
                        "role": {"type": "string"},
                        "why": {"type": "string"},
                    },
                },
                "description": "3-8 files. Prefer entry points, core services, config.",
            },
        },
    },
}

_HOW_IT_RUNS_TOOL: dict[str, Any] = {
    "name": "emit_how_it_runs",
    "description": "Emit the how_it_runs section — local dev setup.",
    "input_schema": {
        "type": "object",
        "required": ["requirements", "local_dev"],
        "properties": {
            "requirements": {
                "type": "array",
                "items": {"type": "string"},
                "description": "System requirements: language versions, package manager, external services.",
            },
            "local_dev": {
                "type": "string",
                "description": "Concrete shell commands to get the app running locally.",
            },
        },
    },
}

_DEPLOYMENT_TOOL: dict[str, Any] = {
    "name": "emit_deployment",
    "description": "Emit the deployment section — where it runs + how deploys happen.",
    "input_schema": {
        "type": "object",
        "required": ["environments", "how_to_deploy", "ci_cd_notes"],
        "properties": {
            "environments": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Named environments (prod, staging, etc).",
            },
            "how_to_deploy": {
                "type": "string",
                "description": "The path from a green build to prod.",
            },
            "ci_cd_notes": {
                "type": "string",
                "description": "Any CI/CD workflows or automation that matter.",
            },
        },
    },
}


# ── System prompts ──────────────────────────────────────────────────────

_BASE_SYSTEM = (
    "You are producing one section of a coding-agent briefing about a "
    "repo. The briefing is loaded at the start of every Claude Code / "
    "Codex session in that repo so the agent has grounded context.\n\n"
    "Rules:\n"
    "- Only use facts present in the provided files. Do NOT invent.\n"
    "- Prefer specifics: real filenames, real commands, real service names.\n"
    "- Be dense and skimmable. A briefing is not documentation.\n"
    "- If the material is thin, emit a shorter section rather than padding.\n"
    "- Call the emit tool exactly once."
)

_OVERVIEW_SYSTEM = _BASE_SYSTEM + (
    "\n\nFor this section (overview):\n"
    "- purpose: one clear sentence.\n"
    "- description: 2-4 sentences. What does this repo produce/do? Who uses it? "
    "What's the tech stack in one phrase?"
)

_ARCHITECTURE_SYSTEM = _BASE_SYSTEM + (
    "\n\nFor this section (architecture):\n"
    "- summary: 2-3 sentences on how the system fits together.\n"
    "- components: 3-8 top-level pieces — service names, their role, their path.\n"
    "- data_flow: one paragraph tracing the primary data flow."
)

_IMPORTANT_FILES_SYSTEM = _BASE_SYSTEM + (
    "\n\nFor this section (important_files):\n"
    "- 3-8 files a fresh agent would want to open first.\n"
    "- Prefer entry points, core services, config, test entry.\n"
    "- 'role' is what the file does; 'why' is why it matters — non-obvious things."
)

_HOW_IT_RUNS_SYSTEM = _BASE_SYSTEM + (
    "\n\nFor this section (how_it_runs):\n"
    "- requirements: system reqs. Language versions, package managers, services.\n"
    "- local_dev: concrete shell commands. If there's a `dev` npm script, "
    "point to it. If there's a Makefile target, name it. Multi-line ok."
)

_DEPLOYMENT_SYSTEM = _BASE_SYSTEM + (
    "\n\nFor this section (deployment):\n"
    "- environments: real named environments (prod, staging, dev).\n"
    "- how_to_deploy: the actual command / workflow that ships to prod.\n"
    "- ci_cd_notes: any relevant CI/CD automation or gates."
)


# ── Fetch helpers ──────────────────────────────────────────────────────

def _get_repo_config(sb, folder_id: str, user_id: str) -> dict | None:
    r = (
        sb.table("github_sync_configs").select("*")
        .eq("root_folder_id", folder_id).eq("user_id", user_id)
        .limit(1).execute().data
    )
    return r[0] if r else None


def _github_client_for_folder(sb, folder_id: str, user_id: str):
    """Return a client for the repo bound to this folder.

    Priority (matches the new sync architecture):
      1. Local clone (LocalRepoClient) — preferred; zero API traffic.
         Kicks in whenever the config row points to a valid clone on
         disk, regardless of sync_mode.
      2. PAT-backed GitHubClient — legacy fallback for rows that
         still have a token_encrypted but never got a local clone.
      3. None — no config, nothing to do.
    """
    from pathlib import Path
    from services.github_sync.local_repo import LocalRepoClient

    cfg = _get_repo_config(sb, folder_id, user_id)
    if not cfg:
        return None

    # Prefer local clone if the row has one and it still exists on disk.
    clone_path = cfg.get("local_clone_path")
    if clone_path and Path(clone_path).exists():
        return LocalRepoClient(
            owner=cfg["repo_owner"],
            repo=cfg["repo_name"],
            clone_path=clone_path,
        )

    # Legacy PAT path — logs a deprecation warning so we can spot which
    # configs still need migration to local clones.
    enc = cfg.get("token_encrypted")
    if enc:
        import logging as _logging
        _logging.getLogger(__name__).warning(
            "populator: falling back to PAT-based GitHubClient for "
            "folder=%s repo=%s/%s — migrate to local clone",
            folder_id, cfg["repo_owner"], cfg["repo_name"],
        )
        try:
            token = decrypt_secret(enc)
        except Exception:  # noqa: BLE001
            token = None
        return GitHubClient(owner=cfg["repo_owner"], repo=cfg["repo_name"], token=token)

    return None


def _list_root_files(gh: GitHubClient) -> list[str]:
    """Names of files (not dirs) at the repo root."""
    return [e["name"] for e in gh.list_dir("") if e.get("type") == "file"]


def _list_root_dirs(gh: GitHubClient) -> list[str]:
    return [e["name"] for e in gh.list_dir("") if e.get("type") == "dir"]


def _try_files(gh: GitHubClient, paths: list[str]) -> dict[str, str]:
    """Fetch each path; skip missing ones. Returns {path: content}."""
    out: dict[str, str] = {}
    for p in paths:
        content = gh.fetch_file(p)
        if content:
            out[p] = content
    return out


# ── Runner — one LLM call, one section ───────────────────────────────

def _run_populator(
    *,
    tool: dict,
    system: str,
    payload: dict,
    section_notes: str,
) -> dict:
    """Call Haiku with the section's emit-tool. Returns section content
    dict on success. On failure returns an empty content shape derived
    from the tool schema."""
    user_message = (
        f"{section_notes}\n\nHere is the material to work from:\n\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )
    msg = complete(
        task=Task.FOLDER_SUMMARY_ROLLUP,
        system=system,
        messages=[{"role": "user", "content": user_message}],
        tools=[tool],
        max_tokens=_MAX_TOKENS,
    )
    for block in msg.content:
        if block.type == "tool_use" and block.name == tool["name"]:
            return dict(block.input)
    log.warning("LLM populator emitted no tool call for %s", tool["name"])
    return {}


# ── Public populator functions — one per section ─────────────────────

def populate_overview(sb, *, folder_id: str, user_id: str) -> dict:
    gh = _github_client_for_folder(sb, folder_id, user_id)
    if gh is None:
        return new_section({"purpose": "", "description": ""})
    with gh:
        files = _try_files(gh, [
            "README.md", "README.rst", "README",
            "package.json", "pyproject.toml", "Cargo.toml", "go.mod",
        ])
        if not files:
            return new_section({"purpose": "", "description": ""})
        try:
            payload = {"files": files}
            content = _run_populator(
                tool=_OVERVIEW_TOOL,
                system=_OVERVIEW_SYSTEM,
                payload=payload,
                section_notes="Write the overview section.",
            )
            if not content:
                return new_section({"purpose": "", "description": ""})
            return new_section(content)
        except Exception:  # noqa: BLE001
            log.exception("overview populator failed")
            return new_section({"purpose": "", "description": ""})


def populate_architecture(sb, *, folder_id: str, user_id: str) -> dict:
    gh = _github_client_for_folder(sb, folder_id, user_id)
    if gh is None:
        return new_section({"summary": "", "components": [], "data_flow": ""})
    with gh:
        readme = _try_files(gh, ["README.md", "README.rst"])
        root_entries = gh.list_dir("")
        # Sample the top 2 levels of dirs so the model can see the shape
        # without walking the whole tree.
        subdir_listings: dict[str, list[dict]] = {}
        for e in root_entries:
            if e.get("type") == "dir":
                subdir_listings[e["name"]] = gh.list_dir(e["name"])[:20]
        payload = {
            "readme": readme,
            "root_entries": [{"name": e["name"], "type": e["type"]} for e in root_entries],
            "subdir_listings": subdir_listings,
        }
        try:
            content = _run_populator(
                tool=_ARCHITECTURE_TOOL,
                system=_ARCHITECTURE_SYSTEM,
                payload=payload,
                section_notes="Write the architecture section.",
            )
            if not content:
                return new_section({"summary": "", "components": [], "data_flow": ""})
            return new_section(content)
        except Exception:  # noqa: BLE001
            log.exception("architecture populator failed")
            return new_section({"summary": "", "components": [], "data_flow": ""})


def populate_important_files(sb, *, folder_id: str, user_id: str) -> dict:
    gh = _github_client_for_folder(sb, folder_id, user_id)
    if gh is None:
        return new_section([])
    with gh:
        readme = _try_files(gh, ["README.md", "README.rst"])
        root_entries = gh.list_dir("")
        subdir_listings: dict[str, list[dict]] = {}
        for e in root_entries:
            if e.get("type") == "dir":
                subdir_listings[e["name"]] = gh.list_dir(e["name"])[:15]
        payload = {
            "readme": readme,
            "root_entries": [
                {"name": e["name"], "type": e["type"]}
                for e in root_entries
            ],
            "subdir_listings": subdir_listings,
        }
        try:
            content = _run_populator(
                tool=_IMPORTANT_FILES_TOOL,
                system=_IMPORTANT_FILES_SYSTEM,
                payload=payload,
                section_notes="Pick 3-8 files a fresh agent should open first.",
            )
            files = (content or {}).get("files") or []
            # The section content shape is the array itself, not {files: [...]}.
            return new_section(files)
        except Exception:  # noqa: BLE001
            log.exception("important_files populator failed")
            return new_section([])


def populate_how_it_runs(sb, *, folder_id: str, user_id: str) -> dict:
    gh = _github_client_for_folder(sb, folder_id, user_id)
    if gh is None:
        return new_section({"requirements": [], "local_dev": ""})
    with gh:
        files = _try_files(gh, [
            "README.md",
            "package.json",
            "pyproject.toml",
            "Makefile",
            "docker-compose.yml",
            "docker-compose.yaml",
            "compose.yml",
            ".tool-versions",
            ".nvmrc",
        ])
        if not files:
            return new_section({"requirements": [], "local_dev": ""})
        try:
            content = _run_populator(
                tool=_HOW_IT_RUNS_TOOL,
                system=_HOW_IT_RUNS_SYSTEM,
                payload={"files": files},
                section_notes="Write the how_it_runs section from these files.",
            )
            if not content:
                return new_section({"requirements": [], "local_dev": ""})
            return new_section(content)
        except Exception:  # noqa: BLE001
            log.exception("how_it_runs populator failed")
            return new_section({"requirements": [], "local_dev": ""})


def populate_deployment(sb, *, folder_id: str, user_id: str) -> dict:
    gh = _github_client_for_folder(sb, folder_id, user_id)
    if gh is None:
        return new_section({
            "environments": [], "how_to_deploy": "", "ci_cd_notes": "",
        })
    with gh:
        files = _try_files(gh, [
            "README.md",
            "Dockerfile",
            "docker-compose.yml",
            "fly.toml",
            "Procfile",
            "vercel.json",
            "netlify.toml",
        ])
        # Sample workflow files
        workflow_entries = gh.list_dir(".github/workflows")
        workflow_files: dict[str, str] = {}
        for e in workflow_entries[:5]:
            if e.get("type") == "file":
                content = gh.fetch_file(e["path"], max_bytes=8_000)
                if content:
                    workflow_files[e["path"]] = content
        deploy_entries = gh.list_dir("deploy") or gh.list_dir("infra")
        payload = {
            "files": files,
            "workflow_files": workflow_files,
            "deploy_entries": [e["path"] for e in deploy_entries[:20]],
        }
        if not files and not workflow_files and not deploy_entries:
            return new_section({
                "environments": [], "how_to_deploy": "", "ci_cd_notes": "",
            })
        try:
            content = _run_populator(
                tool=_DEPLOYMENT_TOOL,
                system=_DEPLOYMENT_SYSTEM,
                payload=payload,
                section_notes="Write the deployment section.",
            )
            if not content:
                return new_section({
                    "environments": [], "how_to_deploy": "", "ci_cd_notes": "",
                })
            return new_section(content)
        except Exception:  # noqa: BLE001
            log.exception("deployment populator failed")
            return new_section({
                "environments": [], "how_to_deploy": "", "ci_cd_notes": "",
            })


# ── Fan-out orchestrator ────────────────────────────────────────────

@dataclass
class LLMPopulatorResult:
    """Return shape of run_llm_populators — one section dict per key."""
    overview: dict
    architecture: dict
    important_files: dict
    how_it_runs: dict
    deployment: dict


async def run_llm_populators(
    sb, *, folder_id: str, user_id: str
) -> LLMPopulatorResult:
    """Run all 5 LLM populators in parallel via to_thread. Each is
    fault-tolerant — one failure returns an empty section for that key
    while others complete."""
    loop = asyncio.get_running_loop()

    async def _run(fn):
        try:
            return await loop.run_in_executor(
                None, lambda: fn(sb, folder_id=folder_id, user_id=user_id)
            )
        except Exception:  # noqa: BLE001
            log.exception("populator crashed: %s", fn.__name__)
            return None

    overview, architecture, important_files, how_it_runs, deployment = \
        await asyncio.gather(
            _run(populate_overview),
            _run(populate_architecture),
            _run(populate_important_files),
            _run(populate_how_it_runs),
            _run(populate_deployment),
        )
    return LLMPopulatorResult(
        overview=overview or new_section({"purpose": "", "description": ""}),
        architecture=architecture or new_section({
            "summary": "", "components": [], "data_flow": "",
        }),
        important_files=important_files or new_section([]),
        how_it_runs=how_it_runs or new_section({
            "requirements": [], "local_dev": "",
        }),
        deployment=deployment or new_section({
            "environments": [], "how_to_deploy": "", "ci_cd_notes": "",
        }),
    )
