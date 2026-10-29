"""Regression checks for slow full-chat exports and collector isolation."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import time
import unittest
from unittest.mock import Mock, patch

import requests

import exporter
from collectors import chats, client
from metrics import CHATS_TOTAL, EXPORTER_SCRAPE_ERRORS_TOTAL, EXPORTER_SCRAPE_SUCCESS


class TimeoutTests(unittest.TestCase):
    def test_default_request_preserves_params_and_short_timeouts(self):
        session = Mock()
        session.get.return_value.json.return_value = {"items": []}
        with patch.object(client, "REQUEST_TIMEOUT_SECONDS", 5):
            result = client.get_json(session, "http://example", "/users", {"page": 2})
        session.get.assert_called_once_with(
            "http://example/users", params={"page": 2}, timeout=(5, 5),
        )
        session.get.return_value.raise_for_status.assert_called_once_with()
        self.assertEqual(result, {"items": []})

    def test_chat_export_uses_longer_read_timeout(self):
        session = Mock()
        session.get.return_value.json.return_value = []
        with patch.object(client, "REQUEST_TIMEOUT_SECONDS", 5), patch.object(
            chats, "CHATS_REQUEST_TIMEOUT_SECONDS", 60,
        ):
            chats.collect_chats_stats(session, "http://example")
        session.get.assert_called_once_with(
            "http://example/api/v1/chats/all/db", params=None, timeout=(5, 60),
        )

    def test_slow_chunked_body_succeeds_with_longer_read_timeout(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                self.wfile.flush()
                time.sleep(0.2)
                try:
                    self.wfile.write(b"2\r\n[]\r\n0\r\n\r\n")
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass

            def log_message(self, *args):
                pass

        with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with requests.Session() as session, patch.object(
                    client, "REQUEST_TIMEOUT_SECONDS", 0.05,
                ):
                    url = f"http://127.0.0.1:{server.server_port}"
                    # Requests wraps timeouts during body consumption as
                    # ConnectionError, matching the user's traceback.
                    with self.assertRaises(requests.ConnectionError):
                        client.get_json(session, url, "/")
                    self.assertEqual(client.get_json(session, url, "/", read_timeout=2), [])
            finally:
                server.shutdown()
                thread.join()

    def test_failed_chat_export_preserves_metrics_and_runs_remaining_steps(self):
        session = Mock()
        session.get.side_effect = requests.ConnectionError("Read timed out")
        next_step = Mock()
        CHATS_TOTAL.set(42)
        errors = EXPORTER_SCRAPE_ERRORS_TOTAL.labels(endpoint="chats_stats")
        before = errors._value.get()
        with patch.object(exporter, "collect_models", return_value={}), patch.object(
            exporter, "collect_model_analytics",
        ), patch.object(exporter, "collect_user_analytics", return_value={}), patch.object(
            exporter, "STEPS", [("next", next_step)],
        ), patch.object(exporter.log, "exception"):
            exporter.poll_once(session)
        self.assertEqual(CHATS_TOTAL._value.get(), 42)
        self.assertEqual(EXPORTER_SCRAPE_SUCCESS._value.get(), 0)
        self.assertEqual(errors._value.get(), before + 1)
        next_step.assert_called_once_with(session, exporter.BASE_URL)

    def test_timeout_settings_accept_overrides_and_reject_invalid_values(self):
        for value in ("0", "-1", "nan", "inf", "invalid"):
            with self.subTest(value=value), patch.dict(client.os.environ, {"TEST_TIMEOUT": value}):
                with self.assertRaises(ValueError):
                    client._timeout_setting("TEST_TIMEOUT", "5")
        with patch.dict(client.os.environ, {"TEST_TIMEOUT": "120.5"}):
            self.assertEqual(client._timeout_setting("TEST_TIMEOUT", "5"), 120.5)


if __name__ == "__main__":
    unittest.main()
