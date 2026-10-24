import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app"))

os.environ.setdefault("PARTYLINE_CONFIG_DIR", "/tmp/partyline-android-tests/config")
os.environ.setdefault("PARTYLINE_RNS_DIR", "/tmp/partyline-android-tests/rns")

from partyline_android.sounds import KINDS, SoundCues


class RecorderBackend:
    def __init__(self):
        self.played = []
        self.released = False

    def play(self, kind, path=None):
        self.played.append((kind, path))
        return True

    def release(self):
        self.released = True


class FailingBackend:
    def play(self, _kind, _path=None):
        raise RuntimeError("speaker unavailable")

    def release(self):
        raise RuntimeError("release failed")


class SoundCuesTests(unittest.TestCase):
    def test_all_cues_are_enabled_by_default(self):
        backend = RecorderBackend()
        cues = SoundCues(backend=backend, asset_dir="/tmp/cues")
        for kind in KINDS:
            self.assertTrue(cues.enabled(kind))
            self.assertTrue(cues.play(kind))
        self.assertEqual([kind for kind, _path in backend.played], list(KINDS))

    def test_disabled_cue_never_reaches_the_backend(self):
        backend = RecorderBackend()
        cues = SoundCues(backend=backend, asset_dir="/tmp/cues")
        cues.set_enabled("message", False)
        self.assertFalse(cues.play("message"))
        self.assertEqual(backend.played, [])
        self.assertTrue(cues.play("ptt_start"))
        self.assertEqual([kind for kind, _path in backend.played], ["ptt_start"])

    def test_play_passes_the_expected_asset_path(self):
        backend = RecorderBackend()
        cues = SoundCues(backend=backend, asset_dir="/tmp/cues")
        self.assertTrue(cues.play("ptt_stop"))
        self.assertEqual(
            backend.played,
            [("ptt_stop", os.path.join("/tmp/cues", "ptt_stop.wav"))],
        )

    def test_backend_failure_is_isolated(self):
        cues = SoundCues(backend=FailingBackend(), asset_dir="/tmp/cues")
        self.assertFalse(cues.play("message"))

    def test_release_stops_further_playback(self):
        backend = RecorderBackend()
        cues = SoundCues(backend=backend, asset_dir="/tmp/cues")
        cues.release()
        self.assertTrue(backend.released)
        self.assertFalse(cues.play("message"))
        self.assertEqual(backend.played, [])


if __name__ == "__main__":
    unittest.main()
