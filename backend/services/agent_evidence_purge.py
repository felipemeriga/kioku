"""Retry Storage deletion after database cascades, including while capture is disabled."""

import logging
from datetime import datetime, timezone

from services.agent_evidence_models import BUCKET

log = logging.getLogger(__name__)


def purge_evidence_outbox(sb):
    rows = (
        sb.table("agent_evidence_purge_outbox")
        .select("id,storage_paths,attempts")
        .lte("not_before", datetime.now(timezone.utc).isoformat())
        .order("created_at")
        .limit(10)
        .execute()
        .data
    )
    for row in rows:
        try:
            paths = row["storage_paths"]
            for start in range(0, len(paths), 1000):
                sb.storage.from_(BUCKET).remove(paths[start : start + 1000])
            sb.table("agent_evidence_purge_outbox").delete().eq("id", row["id"]).execute()
        except Exception as exc:
            # Repeating successful chunks is safe; retain the complete receipt
            # until every object is gone, without logging private object keys.
            log.warning("evidence purge retry code=%s", type(exc).__name__)
            sb.table("agent_evidence_purge_outbox").update({"attempts": row["attempts"] + 1}).eq(
                "id", row["id"]
            ).execute()
