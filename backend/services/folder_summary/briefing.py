"""Briefing schema re-exports for Kioku doc-folder briefings.

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
        "updated_by": free-form label ("mem0", email, api_key_id)
    }

Regen behavior:
- Sections with status=='pinned' are NEVER overwritten by auto-regen.
- status=='hybrid' means user notes are appended to auto content.
  (Phase 4 wires this; MVP treats hybrid == pinned.)
- Provenance is set on write. Auto writes leave `updated_by=null`; UI
  writes stamp the user email; MCP writes stamp the API key label.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

# Re-export pure-schema helpers so existing importers keep working.
from .briefing_schema import (  # noqa: F401, E402
    BRIEFING_SCHEMA_VERSION,
    SECTION_KEYS,
    SectionStatus,
    Provenance,
    new_section,
    empty_briefing,
    merge_briefing,
    _now_iso,
)
