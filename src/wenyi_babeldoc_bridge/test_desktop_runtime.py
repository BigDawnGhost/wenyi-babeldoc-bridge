"""Private protocol boundary tests, without loading BabelDOC or downloading models."""

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from wenyi_babeldoc_bridge.desktop_runtime import (
    PrivateBoundary,
    force_shutdown,
    wait_for_owner_pipe,
)


class PrivateBoundaryTests(unittest.TestCase):
    def test_windows_owner_watch_never_blocks_reading_inherited_stdin(self):
        stream = Mock()
        stream.fileno.return_value = 5
        peek = Mock(side_effect=[(0, 0), (0, 0), OSError("broken owner pipe")])
        handle = Mock(return_value=123)
        with (
            patch("sys.platform", "win32"),
            patch.dict(
                "sys.modules",
                {
                    "_winapi": SimpleNamespace(PeekNamedPipe=peek),
                    "msvcrt": SimpleNamespace(get_osfhandle=handle),
                },
            ),
            patch("time.sleep") as sleep,
        ):
            wait_for_owner_pipe(stream)
        stream.read.assert_not_called()
        handle.assert_called_once_with(5)
        self.assertEqual(peek.call_count, 3)
        self.assertEqual(sleep.call_count, 2)

    def test_windows_owner_signal_stops_without_reading(self):
        stream = Mock()
        with (
            patch("sys.platform", "win32"),
            patch.dict(
                "sys.modules",
                {
                    "_winapi": SimpleNamespace(PeekNamedPipe=Mock(return_value=(1, 0))),
                    "msvcrt": SimpleNamespace(get_osfhandle=Mock(return_value=123)),
                },
            ),
            patch("time.sleep") as sleep,
        ):
            wait_for_owner_pipe(stream)
        stream.read.assert_not_called()
        sleep.assert_not_called()

    def test_posix_owner_watch_reads_until_signal_or_eof(self):
        stream = Mock()
        with patch("sys.platform", "linux"):
            wait_for_owner_pipe(stream)
        stream.read.assert_called_once_with(1)

    def test_owner_deadline_reaps_pdf_subprocesses(self):
        children = [Mock(), Mock()]
        with (
            patch("multiprocessing.active_children", return_value=children),
            patch("os._exit") as exit_process,
        ):
            force_shutdown()
        for child in children:
            child.kill.assert_called_once_with()
            child.join.assert_called_once_with(timeout=1)
        exit_process.assert_called_once_with(0)

    def request(self, headers):
        sent = []
        called = []

        async def app(scope, receive, send):
            called.append(True)

        async def send(message):
            sent.append(message)

        asyncio.run(
            PrivateBoundary(app, 1234, "synthetic")(
                {"type": "http", "headers": headers}, None, send
            )
        )
        return called, sent

    def test_only_authenticated_non_browser_loopback_is_allowed(self):
        allowed = [
            (b"host", b"127.0.0.1:1234"),
            (b"authorization", b"Bearer synthetic"),
        ]
        self.assertTrue(self.request(allowed)[0])
        for headers in [
            [],
            allowed[:1],
            allowed + [(b"origin", b"null")],
            allowed + [(b"origin", b"https://evil.example")],
            allowed + [allowed[0]],
            allowed + [allowed[1]],
            [(b"host", b"evil.example"), allowed[1]],
            [allowed[0], (b"authorization", b"Bearer wrong")],
        ]:
            called, sent = self.request(headers)
            self.assertFalse(called)
            self.assertEqual(sent[0]["status"], 403)
