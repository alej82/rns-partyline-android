import json
import os


DEFAULTS = {
    "name": "",
    "input": None,
    "output": None,
    "tx_gain_db": 0.0,
    "mic_agc": False,
    "keep_screen_on": True,
}


def config_dir():
    return os.environ.get("PARTYLINE_CONFIG_DIR") or os.path.expanduser("~/.config/partyline")


def _coerce(key, value):
    if key in ("input", "output"):
        text = str(value or "").strip()
        return text or None
    if key == "name":
        return str(value or "").strip()
    if key == "tx_gain_db":
        try:
            return float(value)
        except (TypeError, ValueError):
            return DEFAULTS[key]
    if key in ("mic_agc", "keep_screen_on"):
        return bool(value)
    return value


def _write_json(path, data):
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    temporary = path + ".tmp"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as output:
        os.chmod(temporary, 0o600)
        json.dump(data, output, indent=2)
    os.replace(temporary, path)


class MobileSettings(dict):
    def __init__(self, path=None):
        super().__init__(DEFAULTS)
        self.path = path or os.path.join(config_dir(), "settings.json")
        self.load()

    def load(self):
        try:
            with open(self.path) as stored_file:
                stored = json.load(stored_file)
        except (OSError, ValueError):
            stored = {}
        if not isinstance(stored, dict):
            stored = {}
        for key in DEFAULTS:
            if key in stored:
                self[key] = _coerce(key, stored[key])
        return self

    def save(self):
        _write_json(self.path, {key: self[key] for key in DEFAULTS})

    def apply(self, **fields):
        for key, value in fields.items():
            if key in DEFAULTS:
                self[key] = _coerce(key, value)
        return self

    def audio_options(self):
        return {
            "input": self["input"],
            "output": self["output"],
            "tx_gain_db": self["tx_gain_db"],
            "mic_agc": self["mic_agc"],
        }
