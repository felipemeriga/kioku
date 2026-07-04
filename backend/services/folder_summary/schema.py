"""Pydantic schemas for folder-summary payloads.

Two schemas: the compact per-document summary (fan-out step) and the folder-level
rollup that gets stored in folder_summaries.content and served to Claude Code.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class DocumentSummary(BaseModel):
    """Compact per-doc summary used as input to the folder rollup."""

    filename: str
    gist: str = Field(description="One-sentence what this document is about.")
    highlights: list[str] = Field(default_factory=list, description="3-6 key facts or topics.")
    entities: list[str] = Field(
        default_factory=list,
        description="Named people, projects, systems, or concepts referenced.",
    )


class FolderTheme(BaseModel):
    name: str
    description: str


class FolderKeyDocument(BaseModel):
    filename: str
    role: str = Field(description="Why this document matters in the folder's context.")


class FolderSummary(BaseModel):
    """Structured summary served at session-start via the MCP orientation tool."""

    title: str = Field(description="Short human-readable name for this folder.")
    purpose: str = Field(description="One sentence: what this folder is for.")
    overview: str = Field(description="2-4 sentence longer description.")
    themes: list[FolderTheme] = Field(
        default_factory=list, description="Major themes or areas covered by the folder."
    )
    key_documents: list[FolderKeyDocument] = Field(
        default_factory=list,
        description="The most important documents an agent should know about.",
    )
    key_facts: list[str] = Field(
        default_factory=list,
        description="Standalone facts an agent should carry across sessions.",
    )
    entities: list[str] = Field(
        default_factory=list,
        description="People, projects, systems, or concepts that recur.",
    )
    gotchas: list[str] = Field(
        default_factory=list,
        description="Non-obvious things that would trip up a fresh agent.",
    )


class ChangedFiles(BaseModel):
    """Sidecar diff stored alongside each summary row (jsonb changed_files)."""

    added: list[str] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)
    modified: list[str] = Field(default_factory=list)


class HashManifestEntry(BaseModel):
    filename: str
    hash: str
