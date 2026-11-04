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
        body = response.json()
        if body["status"] != "completed":
            error = body.get("error") or {}
            raise ExecutionError(error.get("code", body["status"]), error.get("message", ""))
        result = body.get("result")
        if not isinstance(result, dict) or not isinstance(result.get("text"), str):
            raise ExecutionError("invalid_result")
        structured = result.get("structured")
        if isinstance(structured, dict) and "outcome" in structured:
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
            result.get("structured"),
            result.get("usage"),
            result.get("native_session_id"),
            result.get("attempt_id"),
        )

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
