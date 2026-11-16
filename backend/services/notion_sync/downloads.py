"""Bounded public HTTP downloads with DNS-pinned connections on every redirect."""

import http.client
import ipaddress
import socket
import ssl
import time
from urllib.parse import urljoin, urlsplit, urlunsplit

MAX_ATTACHMENT_BYTES = 50 * 1024 * 1024
MAX_REDIRECTS = 3
DOWNLOAD_SECONDS = 30


def download_attachment(url: str) -> bytes:
    deadline = time.monotonic() + DOWNLOAD_SECONDS
    for _ in range(MAX_REDIRECTS + 1):
        parts = urlsplit(url)
        if (
            parts.scheme not in {"http", "https"}
            or not parts.hostname
            or parts.username is not None
            or parts.password is not None
            or any(ord(c) < 33 or ord(c) == 127 for c in url)
        ):
            raise ValueError("Attachment URL must be public HTTP(S)")
        port = parts.port or (443 if parts.scheme == "https" else 80)
        addresses = socket.getaddrinfo(parts.hostname, port, type=socket.SOCK_STREAM)
        if not addresses or any(
            not ipaddress.ip_address(address[4][0]).is_global for address in addresses
        ):
            raise ValueError("Attachment destination is not public")
        timeout = deadline - time.monotonic()
        if timeout <= 0:
            raise TimeoutError("Attachment download deadline exceeded")
        context = ssl.create_default_context()
        connection = (
            http.client.HTTPSConnection(parts.hostname, port, timeout=timeout, context=context)
            if parts.scheme == "https"
            else http.client.HTTPConnection(parts.hostname, port, timeout=timeout)
        )
        response = None
        try:
            # Connect to the validated numeric address, never resolve the hostname again.
            # Keep the original hostname for Host, TLS SNI and certificate verification.
            connection.sock = socket.create_connection((addresses[0][4][0], port), timeout)
            if parts.scheme == "https":
                connection.sock = context.wrap_socket(
                    connection.sock, server_hostname=parts.hostname
                )
            active_socket = connection.sock
            target = urlunsplit(("", "", parts.path or "/", parts.query, ""))
            connection.request("GET", target, headers={"User-Agent": "kioku-notion-sync/1.0"})
            response = connection.getresponse()
            if response.status in {301, 302, 303, 307, 308}:
                location = response.getheader("Location")
                if not location:
                    raise ValueError("Attachment redirect has no destination")
                url = urljoin(url, location)
                continue
            if response.status != 200:
                raise ValueError("Attachment server returned an unsuccessful status")
            length = response.getheader("Content-Length")
            if length is not None and (
                not length.isdecimal() or int(length) > MAX_ATTACHMENT_BYTES
            ):
                raise ValueError("Attachment exceeds download limit")
            chunks = []
            size = 0
            while True:
                if response.isclosed():
                    return b"".join(chunks)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Attachment download deadline exceeded")
                active_socket.settimeout(remaining)
                chunk = response.read1(min(65536, MAX_ATTACHMENT_BYTES + 1 - size))
                if not chunk:
                    return b"".join(chunks)
                size += len(chunk)
                if size > MAX_ATTACHMENT_BYTES:
                    raise ValueError("Attachment exceeds download limit")
                chunks.append(chunk)
        finally:
            if response is not None:
                response.close()
            connection.close()
    raise ValueError("Attachment redirect limit exceeded")
