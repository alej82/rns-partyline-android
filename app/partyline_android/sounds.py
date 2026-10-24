"""Local audio cues for messages and push-to-talk."""

import os
import threading

from .paths import is_android

LOG_TAG = "PARTYLINE_SOUND"
KINDS = ("message", "ptt_start", "ptt_stop")
ASSET_NAMES = {
    "message": "message.wav",
    "ptt_start": "ptt_start.wav",
    "ptt_stop": "ptt_stop.wav",
}
_JAVA_METHODS = {
    "message": "playMessage",
    "ptt_start": "playPttStart",
    "ptt_stop": "playPttStop",
}


def _log(message):
    print(f"{LOG_TAG} {message}", flush=True)


def default_asset_dir():
    package_dir = os.path.dirname(os.path.abspath(__file__))
    app_dir = os.path.dirname(package_dir)
    return os.path.join(app_dir, "assets", "sounds")


class NullBackend:
    def play(self, _kind, _path=None):
        return False

    def release(self):
        pass


class JavaSoundBackend:
    def __init__(self, asset_dir=None):
        from jnius import autoclass

        self.asset_dir = asset_dir or default_asset_dir()
        self._helper = autoclass("com.hume4ever.partydroid.SoundCues")
        for kind in KINDS:
            path = os.path.join(self.asset_dir, ASSET_NAMES[kind])
            if not os.path.isfile(path):
                _log(f"missing asset kind={kind} path={path}")
        self._helper.initialize(str(self.asset_dir))
        _log(f"android backend initialized directory={self.asset_dir}")

    def play(self, kind, path=None):
        getattr(self._helper, _JAVA_METHODS[kind])()
        return True

    def release(self):
        self._helper.release()


class SoundCues:
    """Plays the enabled cues and never raises into the caller."""

    def __init__(self, backend=None, asset_dir=None, enabled=None):
        self._lock = threading.RLock()
        self.asset_dir = asset_dir or default_asset_dir()
        self._enabled = {kind: True for kind in KINDS}
        self._released = False
        if enabled:
            for kind, value in enabled.items():
                if kind in self._enabled:
                    self._enabled[kind] = bool(value)
        if backend is None:
            backend = self._android_backend()
        self._backend = backend

    def _android_backend(self):
        if not is_android():
            return NullBackend()
        try:
            return JavaSoundBackend(self.asset_dir)
        except Exception as error:
            _log(f"android backend unavailable: {type(error).__name__}: {error}")
            return NullBackend()

    def enabled(self, kind):
        with self._lock:
            return bool(self._enabled.get(kind, False))

    def set_enabled(self, kind, value):
        with self._lock:
            if kind in self._enabled:
                self._enabled[kind] = bool(value)
        return self

    def play(self, kind):
        with self._lock:
            if self._released or not self._enabled.get(kind, False):
                return False
            backend = self._backend
        path = os.path.join(self.asset_dir, ASSET_NAMES.get(kind, ""))
        try:
            result = backend.play(kind, path)
        except Exception as error:
            _log(f"play failed kind={kind}: {type(error).__name__}: {error}")
            return False
        return True if result is None else bool(result)

    def release(self):
        with self._lock:
            if self._released:
                return
            self._released = True
            backend = self._backend
            self._backend = NullBackend()
        try:
            backend.release()
        except Exception as error:
            _log(f"release failed: {type(error).__name__}: {error}")
