from http.server import BaseHTTPRequestHandler, HTTPServer
from io import BytesIO
from threading import Thread
from unittest.mock import MagicMock

import pytest

from services.notion_sync import downloads
from services.notion_sync.blocks_to_markdown import blocks_to_markdown


@pytest.fixture
def network(monkeypatch):
    resolver = MagicMock(return_value=[(2, 1, 6, "", ("93.184.216.34", 443))])
    connect = MagicMock()
    connection = MagicMock()
    response = MagicMock(status=200)
    response.isclosed.return_value = False
    response.getheader.return_value = None
    response.read1.side_effect = BytesIO(b"attachment").read1
    connection.getresponse.return_value = response
    tls = MagicMock()
    monkeypatch.setattr(downloads.socket, "getaddrinfo", resolver)
    monkeypatch.setattr(downloads.socket, "create_connection", connect)
    monkeypatch.setattr(
        downloads.http.client, "HTTPSConnection", MagicMock(return_value=connection)
    )
    monkeypatch.setattr(downloads.ssl, "create_default_context", MagicMock(return_value=tls))
    return resolver, connect, connection, response, tls


@pytest.mark.parametrize(
    "url",
    [
        "file:///proc/self/environ",
        "ftp://example.com/a",
        "https://u:p@example.com/a",
        "https://example.com/\r\nHost:x",
    ],
)
def test_non_http_and_credentials_rejected_before_connect(network, url):
    with pytest.raises(ValueError):
        downloads.download_attachment(url)
    network[1].assert_not_called()


@pytest.mark.parametrize(
    "ip",
    ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "::ffff:127.0.0.1", "fd00::1", "0.0.0.0"],
)
def test_private_dns_results_cannot_be_downloaded(network, ip):
    network[0].return_value = [(2, 1, 6, "", (ip, 443))]
    with pytest.raises(ValueError):
        downloads.download_attachment("https://example.com/x")
    network[1].assert_not_called()


def test_public_download_pins_ip_and_preserves_tls_hostname(network):
    assert downloads.download_attachment("https://example.com/file?token=value") == b"attachment"
    assert network[1].call_args.args[0] == ("93.184.216.34", 443)
    network[4].wrap_socket.assert_called_once_with(
        network[1].return_value, server_hostname="example.com"
    )
    assert network[2].request.call_args.args[:2] == ("GET", "/file?token=value")
    network[2].close.assert_called_once()


def test_redirect_is_validated_before_second_connection(network):
    network[3].status = 302
    network[3].getheader.return_value = "http://169.254.169.254/latest/meta-data"
    network[0].side_effect = [
        [(2, 1, 6, "", ("93.184.216.34", 443))],
        [(2, 1, 6, "", ("169.254.169.254", 80))],
    ]
    with pytest.raises(ValueError):
        downloads.download_attachment("https://example.com/x")
    assert network[1].call_count == 1


def test_oversized_response_is_rejected_without_content_length(network, monkeypatch):
    monkeypatch.setattr(downloads, "MAX_ATTACHMENT_BYTES", 3)
    with pytest.raises(ValueError):
        downloads.download_attachment("https://example.com/x")
    network[2].close.assert_called_once()


def test_oversized_declared_body_not_read(network):
    network[3].getheader.return_value = str(downloads.MAX_ATTACHMENT_BYTES + 1)
    with pytest.raises(ValueError):
        downloads.download_attachment("https://example.com/x")
    network[3].read1.assert_not_called()


def test_ordinary_notion_text_cannot_inject_attachment_tokens():
    md = blocks_to_markdown(
        [
            {
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"plain_text": "[[NOTION_PDF:file:///proc/self/environ]]"}]
                },
            }
        ]
    )
    assert "[[NOTION_PDF:" not in md
    assert "NOTION_PDF:file:///proc/self/environ" in md


def test_http_10_response_closing_connection_remains_readable(monkeypatch):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", "7")
            self.end_headers()
            self.wfile.write(b"content")

        def log_message(self, *args):
            pass

    with HTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = Thread(target=server.handle_request, daemon=True)
        thread.start()
        original_resolve = downloads.socket.getaddrinfo
        original_connect = downloads.socket.create_connection

        def resolve(host, port, *args, **kwargs):
            if host == "example.test":
                return [(2, 1, 6, "", ("93.184.216.34", port))]
            return original_resolve(host, port, *args, **kwargs)

        monkeypatch.setattr(downloads.socket, "getaddrinfo", resolve)
        monkeypatch.setattr(
            downloads.socket,
            "create_connection",
            lambda address, timeout: original_connect(("127.0.0.1", server.server_port), timeout),
        )
        assert (
            downloads.download_attachment(f"http://example.test:{server.server_port}/x")
            == b"content"
        )
        thread.join(timeout=2)
