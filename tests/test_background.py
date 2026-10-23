import os
import sys
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app"))

from partyline_android.background import BackgroundSession


class FakeBackend:
    def __init__(self, start_result=True, update_result=True):
        self.start_result = start_result
        self.update_result = update_result
        self.calls = []
        self.is_running = False

    def start(self, title, text):
        self.calls.append(("start", title, text))
        self.is_running = bool(self.start_result)
        return self.start_result

    def update(self, title, text):
        self.calls.append(("update", title, text))
        return self.update_result

    def stop(self):
        self.calls.append(("stop",))
        self.is_running = False

    def running(self):
        return self.is_running


class FailingBackend(FakeBackend):
    def start(self, title, text):
        self.calls.append(("start", title, text))
        raise RuntimeError("foreground service rejected")


class BackgroundSessionTests(unittest.TestCase):
    def test_non_android_is_unavailable(self):
        session = BackgroundSession(android=False)
        self.assertFalse(session.available())
        self.assertFalse(session.start("Partyline", "Sala Lobby"))
        self.assertFalse(session.update("Partyline", "Sala Lobby"))
        self.assertFalse(session.stop())
        self.assertIsNotNone(session.last_error)

    def test_fake_backend_lifecycle(self):
        backend = FakeBackend()
        session = BackgroundSession(backend=backend, android=True)
        self.assertTrue(session.available())
        self.assertTrue(session.start("Partyline", "Conectando…"))
        self.assertTrue(session.update("Partyline", "Sala Lobby"))
        self.assertTrue(session.running())
        self.assertTrue(session.stop())
        self.assertEqual(
            backend.calls,
            [
                ("start", "Partyline", "Conectando…"),
                ("update", "Partyline", "Sala Lobby"),
                ("stop",),
            ],
        )

    def test_start_failure_allows_fallback(self):
        session = BackgroundSession(backend=FailingBackend(), android=True)
        self.assertFalse(session.start("Partyline", "Conectando…"))
        self.assertIsNotNone(session.last_error)
        self.assertFalse(session.update("Partyline", "Sala Lobby"))

    def test_update_before_start_is_noop(self):
        backend = FakeBackend()
        session = BackgroundSession(backend=backend, android=True)
        self.assertFalse(session.update("Partyline", "Sala Lobby"))
        self.assertEqual(backend.calls, [])

    def test_stop_without_start_is_noop(self):
        backend = FakeBackend()
        session = BackgroundSession(backend=backend, android=True)
        self.assertFalse(session.stop())
        self.assertEqual(backend.calls, [])

    def test_missing_android_backend_allows_fallback(self):
        with patch(
            "partyline_android.background._AndroidBackend",
            side_effect=RuntimeError("no jnius"),
        ):
            session = BackgroundSession(android=True)
            self.assertFalse(session.available())
            self.assertFalse(session.start("Partyline", "Conectando…"))
            self.assertIn("RuntimeError", str(session.last_error))


if __name__ == "__main__":
    unittest.main()
