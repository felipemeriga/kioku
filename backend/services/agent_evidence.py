"""Scoped evidence persistence and navigation. Storage bodies never enter inference."""

from __future__ import annotations

import base64
import json
import os
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from storage3.exceptions import StorageApiError

from services.agent_evidence_models import (
    BUCKET,
    attachment_content_type,
    canonical,
    safe_id,
    sha256,
)
from services.agent_evidence_parser import project_record


def enabled():
    return os.getenv("AGENT_EVIDENCE_ENABLED", "false").lower() in {"1", "true", "yes"}


def fail(code, status=409, **extra):
    raise HTTPException(status_code=status, detail={"code": code, **extra})


def rpc(sb, name, args):
    try:
        return sb.rpc(name, args).execute().data
    except Exception as exc:
        # Do not leak SQL inputs, source content or the provider exception body.
        message = str(exc)
        for code, status in [
            ("scope_denied", 404),
            ("not_found", 404),
            ("deleted", 410),
            ("dependency_pending", 409),
            ("invalid_ancestry", 422),
            ("object_conflict", 409),
            ("batch_conflict", 409),
            ("range_conflict", 409),
            ("stream_conflict", 409),
            ("link_conflict", 409),
        ]:
            if "evidence_" + code in message:
                fail(code, status)
        raise HTTPException(503, detail={"code": "evidence_database_unavailable"}) from None


class EvidenceStore:
    def __init__(self, sb, user_id, folder_id=None):
        self.sb, self.user_id, self.folder_id = sb, user_id, folder_id

    def _query(self, table):
        query = self.sb.table(table).select("*").eq("user_id", self.user_id)
        if self.folder_id:
            query = query.eq("folder_id", self.folder_id)
        return query

    def session(self, session_id, *, deleted=False):
        rows = self._query("agent_evidence_sessions").eq("id", session_id).limit(1).execute().data
        if not rows:
            fail("not_found", 404)
        s = rows[0]
        if s.get("deleted_at") and not deleted:
            fail("deleted", 410)
        return s

    def batch(self, batch_id):
        rows = (
            self._query("agent_evidence_batches").eq("batch_id", batch_id).limit(1).execute().data
        )
        if not rows:
            fail("not_found", 404)
        self.session(rows[0]["session_id"])
        return rows[0]

    def object(self, session_id, object_id, *, committed=True):
        self.session(session_id)
        q = (
            self._query("agent_evidence_objects")
            .eq("session_id", session_id)
            .eq("object_id", object_id)
        )
        if committed:
            q = q.not_.is_("committed_revision", "null")
        rows = q.limit(1).execute().data
        if not rows:
            fail("not_found", 404)
        return rows[0]

    def prefix(self, session, *, deleted=False):
        chain, seen = [], set()
        s = session
        while True:
            if s["id"] in seen or len(seen) >= 32:
                fail("invalid_ancestry", 422)
            seen.add(s["id"])
            chain.append(safe_id(s["native_session_id"]))
            if not s.get("parent_session_id"):
                break
            s = self.session(s["parent_session_id"], deleted=deleted)
        return "/".join(
            [
                self.user_id,
                session["folder_id"],
                session["agent"],
                chain[-1],
                *[part for child in reversed(chain[:-1]) for part in ("subagents", child)],
            ]
        )

    def prepare(self, request):
        body = request.model_dump(by_alias=True, exclude_none=True)
        result = rpc(
            self.sb, "prepare_agent_evidence", {"p_user_id": self.user_id, "p_request": body}
        )
        s = self.session(result["session_id"])
        objects = (
            self._query("agent_evidence_objects")
            .eq("session_id", s["id"])
            .in_("object_id", [o["id"] for o in body["objects"]])
            .execute()
            .data
            if body["objects"]
            else []
        )
        missing = [o["object_id"] for o in objects if not o.get("uploaded_at")]
        return {**result, "revision": s["manifest_revision"], "missing_objects": missing}

    def upload(self, batch_id, object_id, file, content_hash, length):
        b = self.batch(batch_id)
        descriptor = next((o for o in b["request_json"]["objects"] if o["id"] == object_id), None)
        if descriptor is None:
            fail("not_found", 404)
        obj = self.object(b["session_id"], object_id, committed=False)
        if content_hash != obj["sha256"] or length != obj["byte_length"]:
            fail("checksum_mismatch", 422)
        s = self.session(b["session_id"])
        claim = rpc(
            self.sb,
            "claim_agent_evidence_upload",
            {"p_user_id": self.user_id, "p_session_id": s["id"], "p_object_id": object_id},
        )
        if claim["uploaded"]:
            self.download(obj)
            return {"status": "unchanged", "object_id": object_id, "sha256": content_hash}
        suffix = safe_id(object_id) + "-" + claim["nonce"]
        path = self.prefix(s) + (
            "/segments/" + suffix + ".jsonl"
            if obj["kind"] == "segment"
            else "/attachments/" + suffix
        )
        bucket = self.sb.storage.from_(BUCKET)
        file.seek(0)
        try:
            bucket.upload(
                path, file, {"content-type": "application/octet-stream", "upsert": "false"}
            )
        except StorageApiError as exc:
            if str(exc.status) not in {"400", "409"}:
                fail("storage_unavailable", 503)
            try:
                previous = bucket.download(path)
            except StorageApiError:
                fail("storage_unavailable", 503)
            if sha256(previous) != content_hash or len(previous) != length:
                fail("object_conflict")
        # Planned paths are persisted before upload, so crash/deletion cleanup survives.
        try:
            self.session(s["id"])
            rpc(
                self.sb,
                "finish_agent_evidence_upload",
                {
                    "p_user_id": self.user_id,
                    "p_session_id": s["id"],
                    "p_object_id": object_id,
                    "p_nonce": claim["nonce"],
                    "p_path": path,
                },
            )
        except Exception:
            try:
                bucket.remove([path])
            except Exception:
                pass  # Durable delayed purge outbox still owns this planned path.
            raise
        return {"status": "stored", "object_id": object_id, "sha256": content_hash}

    def commit(self, batch_id):
        self.batch(batch_id)
        result = rpc(
            self.sb, "commit_agent_evidence", {"p_user_id": self.user_id, "p_batch_id": batch_id}
        )
        if result["status"] in {"conflict", "incomplete", "dependency_pending"}:
            fail(
                result.get("code", result["status"]),
                **{k: v for k, v in result.items() if k not in {"code", "status"}},
            )
        return result

    def download(self, obj):
        if not obj.get("storage_path"):
            fail("object_pending", 409)
        try:
            data = self.sb.storage.from_(BUCKET).download(obj["storage_path"])
        except StorageApiError:
            fail("object_unavailable", 503)
        if len(data) != obj["byte_length"] or sha256(data) != obj["sha256"]:
            fail("object_integrity_failure", 503)
        return data

    def inventory(self, session_id, cursor=None, limit=100):
        s = self.session(session_id)
        q = self._query("agent_evidence_objects").eq("session_id", session_id)
        q = q.not_.is_("committed_revision", "null")
        if cursor:
            q = q.gt("object_id", safe_id(cursor))
        rows = q.order("object_id").limit(limit + 1).execute().data
        return {
            "session_id": session_id,
            "revision": s["manifest_revision"],
            "objects": [r["descriptor"] for r in rows[:limit]],
            "next_cursor": rows[limit - 1]["object_id"] if len(rows) > limit else None,
        }

    def metadata(self, s):
        children = (
            self._query("agent_evidence_sessions")
            .eq("parent_session_id", s["id"])
            .is_("deleted_at", "null")
            .order("id")
            .limit(100)
            .execute()
            .data
        )
        return {
            k: s.get(k)
            for k in (
                "id",
                "agent",
                "native_session_id",
                "parent_session_id",
                "root_session_id",
                "first_event_at",
                "last_event_at",
                "manifest_revision",
                "indexed_revision",
                "capture_status",
                "index_status",
                "event_count",
                "gaps",
                "lifecycle",
            )
        } | {
            "title": None,
            "summary": None,
            "children": [
                {k: c.get(k) for k in ("id", "agent", "native_session_id", "event_count")}
                for c in children
            ],
        }

    def list_sessions(self, cursor=None, limit=50, agent=None):
        q = (
            self._query("agent_evidence_sessions")
            .is_("parent_session_id", "null")
            .is_("deleted_at", "null")
        )
        if agent:
            q = q.eq("agent", agent)
        if cursor:
            q = q.gt("id", cursor)
        rows = q.order("id").limit(limit + 1).execute().data
        return {
            "sessions": [self.metadata(s) for s in rows[:limit]],
            "next_cursor": rows[limit - 1]["id"] if len(rows) > limit else None,
        }

    def days(self, session_id, tz, start=None, end=None):
        s = self.session(session_id)
        try:
            ZoneInfo(tz)
        except (ValueError, ZoneInfoNotFoundError):
            fail("invalid_timezone", 422)
        end = end or date.today()
        start = start or (
            date.fromisoformat(s["first_event_at"][:10])
            if s.get("first_event_at")
            else end - timedelta(days=365)
        )
        if end < start or (end - start).days > 366:
            fail("date_range_exceeds_limit", 422)
        return {
            "timezone": tz,
            "days": rpc(
                self.sb,
                "agent_evidence_days",
                {
                    "p_user_id": self.user_id,
                    "p_folder_id": s["folder_id"],
                    "p_session_id": session_id,
                    "p_timezone": tz,
                    "p_from": start.isoformat(),
                    "p_to": end.isoformat(),
                },
            ),
        }

    def _cursor(self, s, position, mode="events"):
        snapshot = [s["manifest_revision"], s.get("index_generation", 0), mode]
        return (
            base64.urlsafe_b64encode(
                canonical([self.user_id, s["folder_id"], s["id"], snapshot, position])
            )
            .decode()
            .rstrip("=")
        )

    def _position(self, s, cursor, mode="events"):
        try:
            value = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
            if value[:3] != [self.user_id, s["folder_id"], s["id"]]:
                raise ValueError("wrong scope")
            if value[3] != [s["manifest_revision"], s.get("index_generation", 0), mode]:
                fail("snapshot_changed", 409, revision=s["manifest_revision"])
            if not isinstance(value[4], str) or len(value[4]) > 256:
                raise ValueError("invalid position")
            return value[4]
        except (ValueError, TypeError, IndexError):
            fail("invalid_cursor", 422)

    def event(self, session_id, event_id):
        self.session(session_id)
        rows = (
            self._query("agent_evidence_events")
            .eq("session_id", session_id)
            .eq("event_id", event_id)
            .limit(1)
            .execute()
            .data
        )
        if not rows:
            fail("event_pending_or_absent", 404)
        return rows[0]

    def event_raw(self, session_id, event):
        obj = self.object(session_id, event["object_id"])
        raw = self.download(obj)
        start, end = event["byte_offset"], event["byte_offset"] + event["byte_length"]
        return raw[start:end]

    def event_content(self, session_id, event):
        raw = self.event_raw(session_id, event)
        try:
            record = json.loads(raw)
            content = project_record(record, self.session(session_id)["agent"], {})["_content"]
        except (ValueError, TypeError):
            content = raw.decode("utf-8", errors="replace")
        return content

    def attachments(self, session_id, event_id=None):
        q = (
            self._query("agent_evidence_objects")
            .eq("session_id", session_id)
            .eq("kind", "attachment")
        )
        q = q.not_.is_("committed_revision", "null")
        if event_id:
            q = q.eq("descriptor->>source_event_id", event_id)
        return [
            {
                "id": o["object_id"],
                "original_name": o["descriptor"].get("original_name", "attachment"),
                "byte_length": o["byte_length"],
                "content_type": attachment_content_type(o["descriptor"].get("original_name")),
                "source_event_id": o["descriptor"].get("source_event_id"),
                "available": bool(o.get("uploaded_at")),
                "sha256": o["sha256"],
            }
            for o in q.limit(256).execute().data
        ]

    def window(
        self,
        session_id,
        *,
        before=None,
        after=None,
        around=None,
        day=None,
        tz="UTC",
        limit=50,
        raw=False,
    ):
        s = self.session(session_id)
        mode = "raw" if raw else "events"
        if sum(bool(x) for x in (before, after, around, day)) > 1:
            fail("conflicting_anchors", 422)

        def query():
            q = self._query("agent_evidence_events").eq("session_id", session_id)
            if not raw:
                q = q.eq("displayable", True).eq("inherited", False)
            return q

        if day:
            try:
                zone = ZoneInfo(tz)
                target = date.fromisoformat(day)
            except (ValueError, ZoneInfoNotFoundError):
                fail("invalid_date_or_timezone", 422)
            start = datetime.combine(target, datetime.min.time(), zone).isoformat()
            end = datetime.combine(
                target + timedelta(days=1), datetime.min.time(), zone
            ).isoformat()
            matching = (
                query()
                .gte("event_at", start)
                .lt("event_at", end)
                .order("position")
                .limit(1)
                .execute()
                .data
            )
            around = matching[0]["event_id"] if matching else None
            if not matching:
                return {
                    "events": [],
                    "records": [],
                    "previous_cursor": None,
                    "next_cursor": None,
                    "snapshot_revision": s["manifest_revision"],
                    "status": s["index_status"],
                }
        if around:
            anchor = self.event(session_id, around)["position"]
            left = (
                query()
                .lt("position", anchor)
                .order("position", desc=True)
                .limit(limit // 2)
                .execute()
                .data
            )
            right = (
                query()
                .gte("position", anchor)
                .order("position")
                .limit(limit - len(left))
                .execute()
                .data
            )
            rows = list(reversed(left)) + right
        elif before:
            rows = list(
                reversed(
                    query()
                    .lt("position", self._position(s, before, mode))
                    .order("position", desc=True)
                    .limit(limit)
                    .execute()
                    .data
                )
            )
        else:
            q = query()
            if after:
                q = q.gt("position", self._position(s, after, mode))
            rows = q.order("position").limit(limit).execute().data
        body = []
        budget = 512 * 1024
        cached_object_id, cached_raw = None, None
        children = self.metadata(s)["children"] if not raw else []
        attachment_map = {}
        if not raw and rows:
            attachment_rows = (
                self._query("agent_evidence_objects")
                .eq("session_id", session_id)
                .eq("kind", "attachment")
                .not_.is_("committed_revision", "null")
                .in_("descriptor->>source_event_id", [e["event_id"] for e in rows])
                .limit(1000)
                .execute()
                .data
            )
            for obj in attachment_rows:
                attachment_map.setdefault(obj["descriptor"].get("source_event_id"), []).append(
                    {
                        "id": obj["object_id"],
                        "original_name": obj["descriptor"].get("original_name", "attachment"),
                        "byte_length": obj["byte_length"],
                        "content_type": attachment_content_type(
                            obj["descriptor"].get("original_name")
                        ),
                        "available": bool(obj.get("uploaded_at")),
                        "sha256": obj["sha256"],
                    }
                )
        for event in rows:
            if raw:
                if cached_object_id != event["object_id"]:
                    cached_raw = self.download(self.object(session_id, event["object_id"]))
                    cached_object_id = event["object_id"]
                data = cached_raw[
                    event["byte_offset"] : event["byte_offset"] + event["byte_length"]
                ]
                try:
                    text = data.decode("utf-8") if len(data) <= 65536 else None
                    encoding = "utf-8"
                except UnicodeDecodeError:
                    text = base64.b64encode(data).decode() if len(data) <= 65536 else None
                    encoding = "base64"
                entry = {
                    "event_id": event["event_id"],
                    "source": self.source(event),
                    "byte_length": len(data),
                    "sha256": sha256(data),
                    "raw_text": text,
                    "raw_encoding": encoding,
                    "viewer_truncated": text is None,
                }
            else:
                entry = {
                    k: event.get(k)
                    for k in (
                        "event_id",
                        "role",
                        "event_type",
                        "event_at",
                        "content_preview",
                        "turn_id",
                        "call_id",
                        "source_truncated",
                        "inherited",
                    )
                }
                entry.update(
                    raw_available=True,
                    source=self.source(event),
                    viewer_truncated=event.get("content_length", 0)
                    > len(event["content_preview"].encode()),
                    attachments=attachment_map.get(event["event_id"], []),
                )
                if event["event_type"] == "tool_result":
                    for child in children:
                        if child["native_session_id"] in event["content_preview"]:
                            entry["child_session_id"] = child["id"]
                            break
            cost = len(canonical(entry))
            if cost > budget:
                break
            budget -= cost
            body.append(entry)
        rows = rows[: len(body)]
        previous = bool(
            rows and query().lt("position", rows[0]["position"]).limit(1).execute().data
        )
        following = bool(
            rows and query().gt("position", rows[-1]["position"]).limit(1).execute().data
        )
        return {
            "records" if raw else "events": body,
            "previous_cursor": self._cursor(s, rows[0]["position"], mode) if previous else None,
            "next_cursor": self._cursor(s, rows[-1]["position"], mode) if following else None,
            "snapshot_revision": s["manifest_revision"],
            "status": s["index_status"],
        }

    @staticmethod
    def source(event):
        return {k: event[k] for k in ("object_id", "stream_id", "generation", "record_sequence")}

    def resolve_entry(self, entry_id):
        rows = (
            self._query("agent_evidence_journal_links")
            .eq("journal_entry_id", entry_id)
            .limit(1)
            .execute()
            .data
        )
        if not rows:
            # The journal's stable ID encodes its source session. This proves only
            # a same-owner/folder session association, never an exact event range.
            agent, separator, remainder = entry_id.partition(":")
            native, turn_separator, turn = remainder.rpartition(":")
            if not separator or not turn_separator or agent not in {"codex", "claude_code"}:
                return {"status": "absent"}
            try:
                safe_id(native)
                safe_id(turn)
            except (ValueError, TypeError):
                return {"status": "absent"}
            candidates = (
                self._query("agent_evidence_sessions")
                .eq("agent", agent)
                .eq("native_session_id", native)
                .is_("parent_session_id", "null")
                .limit(2)
                .execute()
                .data
            )
            if len(candidates) != 1:
                return {"status": "absent"}
            session = candidates[0]
            if session.get("deleted_at"):
                return {"status": "deleted"}
            return {"status": "approximate", "session_id": session["id"]}
        link = rows[0]
        s = self.session(link["session_id"], deleted=True)
        if s.get("deleted_at"):
            return {"status": "deleted"}
        found = (
            self._query("agent_evidence_events")
            .eq("session_id", s["id"])
            .eq("event_id", link["start_event_id"])
            .limit(1)
            .execute()
            .data
        )
        return {
            "status": "available"
            if found
            and (
                not link.get("end_event_id")
                or self._query("agent_evidence_events")
                .eq("session_id", s["id"])
                .eq("event_id", link["end_event_id"])
                .limit(1)
                .execute()
                .data
            )
            else "pending",
            **{k: link.get(k) for k in ("session_id", "start_event_id", "end_event_id")},
        }

    def delete(self, session_id):
        self.session(session_id, deleted=True)
        return rpc(
            self.sb,
            "delete_agent_evidence",
            {"p_user_id": self.user_id, "p_folder_id": self.folder_id, "p_session_id": session_id},
        )
