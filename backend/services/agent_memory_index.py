"""Bounded, retryable lexical indexing of already committed original segments."""

from services.agent_evidence import rpc
from services.agent_evidence_models import PARSER_VERSION
from services.agent_evidence_parser import iter_segment

MEMORY_VERSION = 1


def chunks_for_event(event):
    if not event["displayable"] or event.get("inherited"):
        return
    text = event.get("_content", "")
    for start in range(0, len(text), 1000):
        body = text[start : start + 1400]
        yield {
            "event_id": event["event_id"],
            "char_start": start,
            "char_length": len(body),
            "text": body.replace("\x00", " "),
        }


def index_pending_memory(store, session, limit=8):
    pending = (
        store._query("agent_evidence_objects")
        .eq("session_id", session["id"])
        .eq("kind", "segment")
        .not_.is_("committed_revision", "null")
        .gte("indexed_parser_version", PARSER_VERSION)
        .lt("memory_index_version", MEMORY_VERSION)
        .order("first_record")
        .limit(limit)
        .execute()
        .data
        or []
    )
    for obj in pending:
        state = {}
        descriptor = obj["descriptor"]
        if descriptor["first_record"] > 1:
            previous = (
                store._query("agent_evidence_objects")
                .eq("session_id", session["id"])
                .eq("stream_id", obj["stream_id"])
                .eq("generation", obj["generation"])
                .eq("descriptor->>last_record", str(descriptor["first_record"] - 1))
                .gte("indexed_parser_version", PARSER_VERSION)
                .limit(1)
                .execute()
                .data
                or []
            )
            if not previous:
                continue
            state = dict(previous[0].get("parser_state") or {})
        raw = store.download(obj)
        batch = []
        reset = True
        for event in iter_segment(raw, descriptor, session, state, include_content=True):
            for chunk in chunks_for_event(event):
                batch.append(chunk)
                if len(batch) == 250:
                    rpc(
                        store.sb,
                        "publish_agent_memory_index",
                        {
                            "p_session_id": session["id"],
                            "p_object_id": obj["object_id"],
                            "p_chunks": batch,
                            "p_reset": reset,
                            "p_complete": False,
                        },
                    )
                    batch = []
                    reset = False
        rpc(
            store.sb,
            "publish_agent_memory_index",
            {
                "p_session_id": session["id"],
                "p_object_id": obj["object_id"],
                "p_chunks": batch,
                "p_reset": reset,
                "p_complete": True,
            },
        )
