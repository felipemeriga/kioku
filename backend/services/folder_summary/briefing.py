"""Schema re-export shim — re-exports briefing_schema symbols for backward compatibility."""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

# Load-bearing: mcp_server.py imports these schema names from here.
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
