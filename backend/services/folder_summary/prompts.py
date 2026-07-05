"""Prompt templates and Anthropic tool-schemas for folder summarization.

Two operations, three prompts:
- DOC_SUMMARY: distill a single document to a compact JSON (~150 tokens).
- FULL_ROLLUP: build a folder summary from all per-doc summaries + subfolder summaries.
- DELTA_ROLLUP: patch a previous folder summary using only the docs that changed.

We use Anthropic's tool-use to force structured JSON output. Each rollup declares
one "emit" tool whose input schema mirrors FolderSummary.
"""

from __future__ import annotations

import json
from typing import Any

# ---------- Anthropic tool schemas (JSON Schema subset) ----------

DOC_SUMMARY_TOOL: dict[str, Any] = {
    "name": "emit_document_summary",
    "description": "Emit a compact structured summary of a single document.",
    "input_schema": {
        "type": "object",
        "required": ["gist", "highlights", "entities"],
        "properties": {
            "gist": {
                "type": "string",
                "description": "One sentence describing what this document is about.",
            },
            "highlights": {
                "type": "array",
                "items": {"type": "string"},
                "description": "3-6 key facts, findings, or topics from the document.",
            },
            "entities": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Named people, projects, systems, or concepts referenced.",
            },
        },
    },
}


_FOLDER_SUMMARY_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["title", "purpose", "overview"],
    "properties": {
        "title": {"type": "string", "description": "Short human-readable folder title."},
        "purpose": {"type": "string", "description": "One sentence: what this folder is for."},
        "overview": {"type": "string", "description": "2-4 sentence longer description."},
        "themes": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name", "description"],
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                },
            },
        },
        "key_documents": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["filename", "role"],
                "properties": {
                    "filename": {"type": "string"},
                    "role": {"type": "string"},
                },
            },
        },
        "key_facts": {"type": "array", "items": {"type": "string"}},
        "entities": {"type": "array", "items": {"type": "string"}},
        "gotchas": {"type": "array", "items": {"type": "string"}},
    },
}


FULL_ROLLUP_TOOL: dict[str, Any] = {
    "name": "emit_folder_summary",
    "description": "Emit the structured summary for the folder.",
    "input_schema": _FOLDER_SUMMARY_INPUT_SCHEMA,
}


DELTA_ROLLUP_TOOL: dict[str, Any] = {
    "name": "emit_folder_summary",
    "description": (
        "Emit the UPDATED structured summary for the folder, incorporating the "
        "changes described in the user message. Preserve accurate content from "
        "the previous summary; remove anything that referenced deleted files; "
        "integrate new material from added/modified files."
    ),
    "input_schema": _FOLDER_SUMMARY_INPUT_SCHEMA,
}


# Workspace rollup: same emit shape as leaf rollups, but the model composes it
# from CHILD-FOLDER summaries rather than doc summaries. Keeping the schema
# identical means MCP + frontend see the same top-level fields; the extra
# `subfolders[]` metadata is attached at persistence time from the child rows
# themselves (no LLM needed for structured drilldown).
WORKSPACE_ROLLUP_TOOL: dict[str, Any] = {
    "name": "emit_folder_summary",
    "description": (
        "Emit a workspace-level structured summary of a container folder, "
        "synthesized from the summaries of its direct subfolders. The result "
        "should read as a workspace briefing — what this workspace is, how the "
        "subfolders fit together, and what an agent should know to navigate."
    ),
    "input_schema": _FOLDER_SUMMARY_INPUT_SCHEMA,
}


# ---------- System prompts ----------

DOC_SUMMARY_SYSTEM = (
    "You are compressing a single document into a compact structured summary that "
    "will be composed with dozens of others into a folder-level orientation for a "
    "coding agent.\n\n"
    "Rules:\n"
    "- Prefer specifics over generalities. Real entities, real facts, real numbers.\n"
    "- Skip boilerplate, filler, and repetition.\n"
    "- If the document is a codebase file, mention its role (entry point, config, "
    "test, module) rather than restating the code.\n"
    "- 3-6 highlights is the sweet spot. Do not pad.\n"
    "- Call the emit_document_summary tool exactly once."
)


FULL_ROLLUP_SYSTEM = (
    "You are producing a structured folder summary that will be loaded at the "
    "start of every Claude Code session in a related project. The summary must "
    "give a fresh agent the 'big picture' of what's in this folder without "
    "having to read every document.\n\n"
    "Rules:\n"
    "- Be dense and skimmable. This is a briefing, not an essay.\n"
    "- Prefer specifics: real filenames, real entity names, real facts. Never say "
    "'various documents' — name them.\n"
    "- key_documents should surface 3-8 files an agent would want to open first.\n"
    "- gotchas should list non-obvious things that would trip up a fresh agent — "
    "not generic warnings.\n"
    "- Do not hallucinate content not present in the per-document summaries.\n\n"
    "FORMATTING RULES:\n"
    "- key_facts, entities, gotchas are ARRAYS of strings. Emit them as JSON "
    "arrays, NOT as one long string with <item> tags or newlines.\n"
    "- themes is an ARRAY of {name, description} objects.\n"
    "- key_documents is an ARRAY of {filename, role} objects.\n\n"
    "Call the emit_folder_summary tool exactly once."
)


WORKSPACE_ROLLUP_SYSTEM = (
    "You are producing a WORKSPACE briefing for a container folder — one whose "
    "direct content is nearly empty but which contains subfolders that are the "
    "real projects, teams, or areas of work. Think of it like a company handbook "
    "root, a monorepo root, or a Notion workspace root.\n\n"
    "You will be given the folder metadata and the compact summary of EACH "
    "direct subfolder (purpose, overview, key facts). Your job is to synthesize "
    "a unified briefing that:\n\n"
    "- purpose: one sentence saying what this workspace is for as a whole.\n"
    "- overview: 2-4 sentences describing how the subfolders fit together — what "
    "they collectively represent, and any obvious grouping.\n"
    "- key_facts: 4-8 concrete facts that span the workspace. Prefer cross-cutting "
    "observations (e.g. 'all projects use Python 3.10+', 'three of the five "
    "subfolders are internal tools, two are public') over per-subfolder trivia.\n"
    "- gotchas: things a fresh agent should know before diving in — conventions, "
    "known drift, integration boundaries. Not generic warnings.\n"
    "- key_documents: ONLY populate if there are documents directly in this "
    "folder (rare for containers). Otherwise emit an empty array.\n"
    "- themes: an ARRAY of {name, description} objects — top themes across the "
    "workspace.\n\n"
    "Rules:\n"
    "- Name the subfolders by their real names. Never say 'various subfolders'.\n"
    "- Do not invent content that isn't in a child summary.\n"
    "- If two child summaries contradict, prefer the more specific/recent one.\n\n"
    "FORMATTING RULES:\n"
    "- key_facts, entities, gotchas are ARRAYS of strings, not <item> XML.\n"
    "- Call the emit_folder_summary tool exactly once."
)


DELTA_ROLLUP_SYSTEM = (
    "You are patching an existing folder summary to reflect changes. The previous "
    "summary is provided as JSON; you also receive lists of added, modified, and "
    "removed files. Your job is to output an UPDATED folder summary that:\n\n"
    "1. Removes any content that referenced the removed files (do not preserve "
    "stale references).\n"
    "2. Integrates new highlights and entities from added and modified files.\n"
    "3. Preserves everything from the previous summary that is still accurate.\n"
    "4. Does not invent content that isn't in the previous summary or the change "
    "lists.\n\n"
    "FORMATTING RULES — these are strict:\n"
    "- key_facts, entities, gotchas are ARRAYS of strings. Emit them as JSON "
    "arrays, NOT as one long string with <item> tags or newlines inside.\n"
    "- themes is an ARRAY of {name, description} objects.\n"
    "- key_documents is an ARRAY of {filename, role} objects.\n"
    "- Never emit `<item>...</item>` XML — use real JSON arrays.\n\n"
    "Call the emit_folder_summary tool exactly once."
)


# ---------- Message builders ----------


def build_doc_summary_message(filename: str, content: str, max_chars: int = 12000) -> list[dict]:
    """User message for the per-doc summary call. Truncates very large docs."""
    if len(content) > max_chars:
        head = content[: max_chars // 2]
        tail = content[-max_chars // 2 :]
        content = f"{head}\n\n... [truncated: middle omitted] ...\n\n{tail}"
    return [
        {
            "role": "user",
            "content": (
                f"Filename: {filename}\n\n---BEGIN DOCUMENT---\n{content}\n---END DOCUMENT---"
            ),
        }
    ]


def build_workspace_rollup_message(
    folder_name: str,
    folder_path: str,
    subfolder_summaries: list[dict],
    pooled_activity: dict | None = None,
) -> list[dict]:
    """User message for the workspace-rollup call.

    subfolder_summaries: list of {name, purpose, overview, key_facts,
      key_documents, doc_count, has_mem0, has_github, has_notion}.
    pooled_activity: optional {recent_commits: [...], recent_learnings: [...]}
      pooled across the entire subtree so the model can mention momentum.
    """
    payload = {
        "folder": {"name": folder_name, "path": folder_path},
        "subfolders": subfolder_summaries,
        "recent_activity_pool": pooled_activity or {},
    }
    return [
        {
            "role": "user",
            "content": (
                f"Compose a workspace briefing for '{folder_name}'. It contains "
                f"{len(subfolder_summaries)} direct subfolders, each with its own "
                f"summary. Synthesize a unified overview that shows how they fit "
                f"together.\n\n"
                + json.dumps(payload, ensure_ascii=False, indent=2)
            ),
        }
    ]


def build_full_rollup_message(
    folder_name: str,
    folder_path: str,
    doc_summaries: list[dict],
    subfolder_summaries: list[dict] | None = None,
) -> list[dict]:
    """User message for the full-regen rollup call."""
    subfolder_summaries = subfolder_summaries or []
    payload = {
        "folder": {"name": folder_name, "path": folder_path},
        "documents": doc_summaries,
        "subfolders": subfolder_summaries,
    }
    return [
        {
            "role": "user",
            "content": (
                f"Produce a fresh folder summary. Here is the folder metadata plus "
                f"a compact summary of each document ({len(doc_summaries)} docs) "
                f"and each subfolder ({len(subfolder_summaries)} subfolders):\n\n"
                + json.dumps(payload, ensure_ascii=False, indent=2)
            ),
        }
    ]


def build_delta_rollup_message(
    folder_name: str,
    folder_path: str,
    previous_summary: dict,
    added_summaries: list[dict],
    modified_summaries: list[dict],
    removed_filenames: list[str],
) -> list[dict]:
    """User message for the delta rollup call."""
    payload = {
        "folder": {"name": folder_name, "path": folder_path},
        "previous_summary": previous_summary,
        "changes": {
            "added_documents": added_summaries,
            "modified_documents": modified_summaries,
            "removed_filenames": removed_filenames,
        },
    }
    return [
        {
            "role": "user",
            "content": (
                "Patch the previous summary to reflect these changes. Remember: "
                "content referencing removed files must be dropped.\n\n"
                + json.dumps(payload, ensure_ascii=False, indent=2)
            ),
        }
    ]
