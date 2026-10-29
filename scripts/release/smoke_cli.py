#!/usr/bin/env python3
"""Exercise the compiled CLI and real Manabi reconnects without installing a service."""

import base64
import hashlib
import json
import os
import struct
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4


def read_exact(stream, size):
    data = b""
    while len(data) < size:
        chunk = stream.read(size - len(data))
        if not chunk:
            raise EOFError("WebSocket closed early")
        data += chunk
    return data


def client_message(stream):
    first, second = read_exact(stream, 2)
    if first != 0x81 or not second & 0x80:
        raise ValueError("Expected one masked text frame")
    size = second & 0x7F
    if size == 126:
        size = struct.unpack("!H", read_exact(stream, 2))[0]
    if size > 1024:
        raise ValueError("Unexpected large smoke-test frame")
    mask = read_exact(stream, 4)
    payload = read_exact(stream, size)
    return json.loads(bytes(value ^ mask[i % 4] for i, value in enumerate(payload)))


def smoke_manabi(binary, env, tmp):
    connected_twice = threading.Event()
    stopping = threading.Event()
    lock = threading.Lock()
    connections = 0
    errors = []
    machine_id, fixture_secret = str(uuid4()), "a" * 64

    class Backend(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            nonlocal connections
            try:
                if self.path != "/api/remotes/connect":
                    raise ValueError("Wrong Manabi endpoint")
                key = self.headers["Sec-WebSocket-Key"]
                accept = base64.b64encode(
                    hashlib.sha1(
                        (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()
                    ).digest()
                ).decode()
                self.send_response(101)
                self.send_header("Upgrade", "websocket")
                self.send_header("Connection", "Upgrade")
                self.send_header("Sec-WebSocket-Accept", accept)
                self.end_headers()
                self.wfile.flush()
                self.connection.settimeout(8)
                hello = client_message(self.rfile)
                if (
                    hello.get("type") != "hello"
                    or hello.get("id") != machine_id
                    or hello.get("secret") != fixture_secret
                    or not isinstance(hello.get("version"), str)
                ):
                    raise ValueError("Incorrect Manabi hello")
                ready = b'{"type":"ready"}'
                self.wfile.write(bytes([0x81, len(ready)]) + ready)
                self.wfile.flush()
                with lock:
                    connections += 1
                    count = connections
                if count == 1:
                    # Force a real reconnect through the packaged ws dependency.
                    self.wfile.write(b"\x88\x02\x03\xe9")
                    self.wfile.flush()
                else:
                    connected_twice.set()
                    stopping.wait(15)
            except (OSError, EOFError, ValueError, KeyError, TypeError) as exc:
                errors.append(type(exc).__name__)
            finally:
                self.close_connection = True

    server = ThreadingHTTPServer(("127.0.0.1", 0), Backend)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    config = Path(tmp) / "manabi.json"
    config.write_text(
        json.dumps(
            {
                "id": machine_id,
                "secret": fixture_secret,
                "api_base": f"http://127.0.0.1:{server.server_port}",
            }
        )
    )
    process = subprocess.Popen(
        [binary, "internal-manabi-run", str(config)],
        cwd=tmp,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    succeeded = False
    try:
        succeeded = connected_twice.wait(12)
    finally:
        process.terminate()
        try:
            _stdout, stderr = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            _stdout, stderr = process.communicate()
        stopping.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    if not succeeded or errors:
        raise RuntimeError(
            "Standalone Manabi connection/reconnect failed: "
            + str(errors)
            + " "
            + stderr[-500:]
        )
    if os.name != "nt" and process.returncode != 0:
        raise RuntimeError("Standalone Manabi did not stop cleanly")
    print(
        "Standalone Manabi authenticated, reconnected, and stopped; no OS service installed"
    )


def main():
    binary = str(Path(sys.argv[1]).resolve())
    with tempfile.TemporaryDirectory() as tmp:
        env = {
            **os.environ,
            "HOME": tmp,
            "USERPROFILE": tmp,
            "XDG_CONFIG_HOME": tmp,
            "KIOKU_NO_UPDATE_CHECK": "1",
        }
        for command in (["--version"], ["--help"], ["session-start"]):
            subprocess.run([binary, *command], cwd=tmp, env=env, check=True, timeout=15)
        if Path("cli/src/lib/manabi.ts").exists():
            smoke_manabi(binary, env, tmp)


if __name__ == "__main__":
    main()
