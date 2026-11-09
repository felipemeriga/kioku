"""Authenticated Tsukai v1 client; transport retries never resubmit inference."""

import json
import time
from dataclasses import dataclass
from typing import Callable, Iterator

import httpx


class ExecutionError(RuntimeError):
    def __init__(self, code: str, detail: str = ""):
        self.code = code
        super().__init__(f"{code}: {detail}")


@dataclass(frozen=True)
class ExecutionResult:
    job_id: str
    text: str
    structured: dict | None
    usage: dict | None
    native_session_id: str | None
    attempt_id: str | None = None


def parse_execution_result(
    job_id: str, body: dict, *, attempt_id: str | None = None
) -> ExecutionResult:
    """One fail-closed result contract for authenticated GET and durable events."""
    if not isinstance(body, dict) or body.get("job_id") != job_id:
        raise ExecutionError("foreign_result")
    status = body.get("status")
    if not isinstance(status, str):
        raise ExecutionError("invalid_result")
    error = body.get("error")
    if error is not None and not isinstance(error, dict):
        raise ExecutionError("invalid_result")
    if error and (
        ("code" in error and not isinstance(error["code"], str))
        or ("message" in error and not isinstance(error["message"], str))
    ):
        raise ExecutionError("invalid_result")
    if status != "completed":
        raise ExecutionError((error or {}).get("code", status), (error or {}).get("message", ""))
    result = body.get("result")
    if error is not None or not isinstance(result, dict) or not isinstance(result.get("text"), str):
        raise ExecutionError("invalid_result")
    for key in ("structured", "usage"):
        if result.get(key) is not None and not isinstance(result[key], dict):
            raise ExecutionError("invalid_result")
    for key in ("native_session_id", "attempt_id"):
        if result.get(key) is not None and (not isinstance(result[key], str) or not result[key]):
            raise ExecutionError("invalid_result")
    if attempt_id is not None and result.get("attempt_id") != attempt_id:
        raise ExecutionError("attempt_mismatch")
    structured = result.get("structured")
    if isinstance(structured, dict) and "outcome" in structured:
        if not isinstance(structured["outcome"], str) or structured["outcome"] not in {
            "completed",
            "needs_input",
            "failed",
        }:
            raise ExecutionError("invalid_outcome")
        if structured["outcome"] != "completed":
            raise ExecutionError(
                structured["outcome"], "completion did not produce publishable data"
            )
        if (
            structured.get("data") is None
            or structured.get("missing_inputs")
            or structured.get("failure")
        ):
            raise ExecutionError("invalid_outcome")
    return ExecutionResult(
        job_id,
        result["text"],
        structured,
        result.get("usage"),
        result.get("native_session_id"),
        result.get("attempt_id"),
    )


def completed_event_result(job_id: str, event: dict) -> ExecutionResult | None:
    """Use only a bound durable terminal payload; legacy replay still requires GET."""
    if not isinstance(event, dict) or event.get("job_id") != job_id:
        raise ExecutionError("foreign_event")
    if not isinstance(event.get("type"), str) or event["type"] not in {
        "job.completed",
        "replay.expired",
    }:
        raise ExecutionError("invalid_result_event")
    data = event.get("data")
    if not isinstance(data, dict):
        raise ExecutionError("invalid_result_event")
    if data.get("error") is not None or data.get("status", "completed") != "completed":
        raise ExecutionError("invalid_result")
    if data.get("job_id", job_id) != job_id:
        raise ExecutionError("foreign_event")
    event_attempt = event.get("attempt_id")
    if event_attempt is not None and (not isinstance(event_attempt, str) or not event_attempt):
        raise ExecutionError("invalid_result_event")
    if "result" not in data:
        return None
    if not isinstance(data["result"], dict):
        raise ExecutionError("invalid_result")
    if event["type"] == "replay.expired":
        # Older adapters synthesize only a text/structured fragment on HTTP410.
        # It is not the authoritative durable completion envelope.
        parse_execution_result(job_id, {"job_id": job_id, "status": "completed", **data})
        return None
    attempt_id = event.get("attempt_id")
    if not isinstance(attempt_id, str) or not attempt_id:
        raise ExecutionError("missing_attempt")
    return parse_execution_result(
        job_id, {"job_id": job_id, "status": "completed", **data}, attempt_id=attempt_id
    )


class TsukaiClient:
    def __init__(
        self,
        url: str,
        service_token: str,
        capability: str | Callable[[], str],
        *,
        transport=None,
        deadline_seconds: float = 900,
        admission_capability: Callable[[dict], str] | None = None,
    ):
        self.last_job_id: str | None = None
        self._admission_capability = admission_capability
        self._capability = capability
        self._deadline = time.monotonic() + deadline_seconds
        self._http = httpx.Client(
            base_url=url.rstrip("/"),
            headers={
                "Authorization": f"Bearer {service_token}",
                "X-Tsukai-Capability": capability() if callable(capability) else capability,
            },
            timeout=httpx.Timeout(30, read=45),
            transport=transport,
        )

    def close(self):
        self._http.close()

    def _authorize(self):
        if time.monotonic() >= self._deadline:
            raise ExecutionError("client_deadline")
        if callable(self._capability):
            self._http.headers["X-Tsukai-Capability"] = self._capability()

    def submit(self, request: dict) -> str:
        self._authorize()
        if self._admission_capability:
            self._http.headers["X-Tsukai-Capability"] = self._admission_capability(request)
        response = self._http.post("/v1/jobs", json=request)
        response.raise_for_status()
        self.last_job_id = response.json()["job_id"]
        return self.last_job_id

    def status(self, job_id: str) -> dict:
        self._authorize()
        response = self._http.get(f"/v1/jobs/{job_id}")
        response.raise_for_status()
        return response.json()

    def models(self) -> dict:
        self._authorize()
        response = self._http.get("/v1/models")
        response.raise_for_status()
        return response.json()

    def active_attempt(self, job_id: str, attempt_id: str) -> dict:
        self._authorize()
        response = self._http.get(f"/v1/jobs/{job_id}/attempts/{attempt_id}")
        response.raise_for_status()
        return response.json()

    def tool_event(self, job_id: str, attempt_id: str, kind: str, data: dict):
        self._authorize()
        response = self._http.post(
            f"/v1/jobs/{job_id}/tool-events",
            json={
                "attempt_id": attempt_id,
                "type": kind,
                "data": data,
            },
        )
        response.raise_for_status()

    def tool_events(self, job_id: str, attempt_id: str, events: list[tuple[str, dict]]):
        """Persist the bounded completion pair atomically before returning evidence."""
        self._authorize()
        response = self._http.post(
            f"/v1/jobs/{job_id}/tool-events/batch",
            json={
                "attempt_id": attempt_id,
                "events": [{"type": kind, "data": data} for kind, data in events],
            },
        )
        if response.status_code == 404:
            try:
                missing_route = response.json() == {"detail": "Not Found"}
            except ValueError:
                missing_route = False
            if missing_route:
                # Rolling upgrades can reach the old server before its additive
                # route exists. This exact response proves no batch was accepted.
                # Never replay after a timeout, server failure or domain rejection.
                for kind, data in events:
                    self.tool_event(job_id, attempt_id, kind, data)
                return
        response.raise_for_status()

    def events(self, job_id: str, *, cursor: int = 0, reconnects: int = 3) -> Iterator[dict]:
        """Replay contiguous events. EOF without terminal is never a success."""
        terminal = {"job.completed", "job.failed", "job.cancelled", "job.uncertain"}
        last_error = "missing_terminal"
        for retry in range(reconnects + 1):
            self._authorize()
            try:
                with self._http.stream(
                    "GET", f"/v1/jobs/{job_id}/events", headers={"Last-Event-ID": str(cursor)}
                ) as response:
                    if response.status_code == 410:
                        result = self.result(job_id)
                        yield {
                            "job_id": job_id,
                            "seq": cursor,
                            "type": "replay.expired",
                            "data": {
                                "result": {"text": result.text, "structured": result.structured}
                            },
                        }
                        return
                    response.raise_for_status()
                    data = []
                    for line in response.iter_lines():
                        if line.startswith("data:"):
                            data.append(line[5:].lstrip())
                        elif not line and data:
                            event = json.loads("\n".join(data))
                            data.clear()
                            seq = event["seq"]
                            if event["job_id"] != job_id:
                                raise ExecutionError("foreign_event")
                            if seq <= cursor:
                                continue
                            if seq != cursor + 1:
                                last_error = "event_gap"
                                break
                            cursor = seq
                            yield event
                            if event["type"] in terminal:
                                return
            except (httpx.TransportError, httpx.ReadTimeout):
                pass
            if retry < reconnects:
                time.sleep(min(0.25 * 2**retry, 2))
        raise ExecutionError(last_error, "event stream ended without a durable outcome")

    def result(self, job_id: str) -> ExecutionResult:
        self._authorize()
        response = self._http.get(f"/v1/jobs/{job_id}/result")
        response.raise_for_status()
        return parse_execution_result(job_id, response.json())

    def complete(self, request: dict) -> ExecutionResult:
        job_id = self.submit(request)
        for _ in self.events(job_id):
            pass
        return self.result(job_id)

    def cancel(self, job_id: str) -> dict:
        self._authorize()
        response = self._http.post(f"/v1/jobs/{job_id}/cancel")
        response.raise_for_status()
        return response.json()

    def acknowledge(self, job_id: str, consumer: str, reference: str):
        self._authorize()
        response = self._http.post(
            f"/v1/jobs/{job_id}/ack", json={"consumer": consumer, "reference": reference}
        )
        response.raise_for_status()

    def delete_domain(self, path: str, body: dict) -> dict:
        self._authorize()
        if self._admission_capability:
            self._http.headers["X-Tsukai-Capability"] = self._admission_capability(body)
        response = self._http.post(path, json=body)
        response.raise_for_status()
        return response.json()

    def deletion_status(self, tombstone_id: str) -> dict:
        self._authorize()
        response = self._http.get(f"/v1/deletions/{tombstone_id}")
        response.raise_for_status()
        return response.json()

    def usage(self, job_id: str) -> dict:
        self._authorize()
        response = self._http.get(f"/v1/jobs/{job_id}/usage")
        response.raise_for_status()
        return response.json()

    def active_sessions(self) -> dict:
        self._authorize()
        response = self._http.get("/v1/admin/active-sessions")
        response.raise_for_status()
        return response.json()
