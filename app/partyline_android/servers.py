import json
import os
import time

from partyline import prefs

FIELDS = prefs.ServerList.FIELDS


def _normalise(raw_entry):
    entry = {}
    for field in FIELDS:
        value = raw_entry.get(field)
        entry[field] = value if isinstance(value, str) else ("" if value is None else str(value))
    try:
        entry["last_used"] = float(raw_entry.get("last_used") or 0)
    except (TypeError, ValueError):
        entry["last_used"] = 0.0
    return entry


def default_path():
    return prefs.SERVERS_FILE


class SavedServers:
    def __init__(self, path=None):
        self.path = path or default_path()
        self.entries = []
        self.load()

    def load(self):
        try:
            with open(self.path) as stored_file:
                stored = json.load(stored_file)
        except (OSError, ValueError):
            stored = []
        entries = []
        if isinstance(stored, list):
            for raw_entry in stored:
                if isinstance(raw_entry, dict) and isinstance(raw_entry.get("hash"), str):
                    entries.append(_normalise(raw_entry))
        self.entries = entries
        return self

    def save(self):
        directory = os.path.dirname(self.path) or "."
        os.makedirs(directory, exist_ok=True)
        temporary = self.path + ".tmp"
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w") as output:
            os.chmod(temporary, 0o600)
            json.dump(self.entries, output, indent=2)
        os.replace(temporary, self.path)

    def find(self, destination_hash):
        text = str(destination_hash or "").strip().lower()
        if not text:
            return None
        for entry in self.entries:
            if entry["hash"].lower() == text:
                return entry
        return None

    def label_for(self, entry):
        if entry is None:
            return ""
        name = (entry.get("name") or "").strip()
        room = (entry.get("room") or "").strip()
        prefix = entry["hash"][:8]
        title = name or prefix
        return f"{title} · {room}" if room else title

    def ordered(self):
        return sorted(self.entries, key=lambda entry: entry["last_used"], reverse=True)

    def most_recent(self):
        entries = self.ordered()
        return entries[0] if entries else None

    def upsert(
        self,
        destination_hash,
        room=None,
        password=None,
        server_password=None,
        name=None,
        label=None,
        last_used=None,
    ):
        text = str(destination_hash or "").strip().lower()
        entry = self.find(text)
        if entry is None:
            entry = _normalise({"hash": text})
            self.entries.append(entry)
        if room is not None:
            entry["room"] = room or ""
        if password is not None:
            entry["password"] = password or ""
        if server_password is not None:
            entry["server_password"] = server_password or ""
        if name is not None:
            entry["name"] = name or ""
        if label is not None:
            entry["label"] = label or ""
        else:
            entry["label"] = self.label_for(entry)
        entry["last_used"] = time.time() if last_used is None else float(last_used)
        self.save()
        return entry

    def remove(self, entry):
        self.entries = [existing for existing in self.entries if existing is not entry]
        self.save()
