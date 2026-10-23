import collections
import copy
import os
import queue
import threading
import time

from .i18n import t
from .paths import is_android, prepare_environment
from .reticulum import SharedInstanceUnavailable, start_reticulum

RETRY_DELAYS = (3, 5, 10, 20, 30)
CONNECT_WATCHDOG = 45
SPEAKING_WINDOW = 0.35
_UNSET = object()


def _channel_dict(channel):
    return {
        "id": channel.id,
        "name": channel.name,
        "profile": channel.profile,
        "frame_ms": channel.frame_ms,
        "access": channel.access,
        "description": channel.description,
        "dialin_number": channel.dialin_number,
        "ptt_jitter_ms": channel.ptt_jitter_ms,
        "flags": channel.flags,
        "ptt": channel.ptt,
        "broadcast": channel.broadcast,
        "music": channel.music,
        "locked": channel.locked,
    }


def _jsonable(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, set):
        return sorted(_jsonable(item) for item in value)
    return repr(value)


class Engine:
    def __init__(self, rns_dir=None, config_dir=None, identity_path=None, display_name=None, client_options=None):
        prepare_environment()
        self.rns_dir = rns_dir or os.environ.get("PARTYLINE_RNS_DIR") or os.path.expanduser("~/.reticulum")
        self.config_dir = config_dir or os.environ.get("PARTYLINE_CONFIG_DIR")
        self.identity_path = identity_path or os.path.join(self.config_dir, "identity")
        self.display_name = display_name

        self.client_options = {"text_only": False, "mode": "ptt"}
        if client_options:
            self.client_options.update(client_options)
        self._audio_error = None
        self._audio_suspended = False
        self._microphone_allowed = True

        self.rns = None
        self.client = None
        self.identity_hash = None
        self.shared_instance = False

        self._lock = threading.RLock()
        self._events = queue.Queue()
        self._history = collections.deque(maxlen=500)
        self._sequence = 0
        self._snapshot = self._empty_snapshot("starting")

        self._wanted_connected = False
        self._last_connect = None
        self._retry_index = 0
        self._retry_at = None
        self._retry_in = None
        self._kicked_reported = False
        self._attempt_at = None

        self._stop = threading.Event()
        self._thread = None

    def start(self):
        with self._lock:
            if self.client is not None:
                return self
            self.rns = start_reticulum(self.rns_dir)
            self.shared_instance = bool(getattr(self.rns, "is_connected_to_shared_instance", False))

            from partyline.client import Client, Config, default_name
            from partyline.common import load_identity

            identity = load_identity(self.identity_path)
            name = self.display_name or default_name(identity)
            self.identity_hash = identity.hash.hex()
            self.client = Client(Config(**self.client_options), identity, name)
            self.client.cfg.listen = not self._microphone_allowed
            print(
                f"PARTYLINE_TRANSPORT shared_instance={self.shared_instance} identity={self.identity_hash}",
                flush=True,
            )

        self._thread = threading.Thread(target=self._dispatch_loop, name="partyline-engine", daemon=True)
        self._thread.start()
        self._publish({"type": "transport", "shared_instance": self.shared_instance})
        self._refresh_snapshot()
        return self

    def stop(self):
        self._stop.set()
        with self._lock:
            self._wanted_connected = False
            self._retry_at = None
            self._retry_in = None
            if self.client is not None:
                self.client.cancel_transmit()
                self.client.disconnect()
        if self._thread is not None:
            self._thread.join(timeout=2)
        self._refresh_snapshot()

    def connect(self, destination_hash, room=None, password=None, server_password=None):
        text = str(destination_hash or "").strip().lower()
        if len(text) != 32 or any(character not in "0123456789abcdef" for character in text):
            raise ValueError(t("engine.error.invalid_hash"))

        with self._lock:
            if self.client is None:
                raise RuntimeError(t("engine.error.not_started"))
            params = {
                "hash": text,
                "room": room or None,
                "password": password or None,
                "server_password": server_password or None,
            }
            self._last_connect = params
            self._wanted_connected = True
            self._retry_index = 0
            self._retry_at = None
            self._retry_in = None
            self._kicked_reported = False
            self._attempt_at = time.time()
            self._audio_error = None
            self._audio_suspended = False
            self.client.kicked = False
            self.client.error = None
            self.client.cancel_transmit()
            if self.client.state not in ("idle", "closed"):
                self.client.disconnect()
            self.client.connect(
                bytes.fromhex(text),
                room=params["room"],
                password=params["password"],
                server_password=params["server_password"],
            )
        self._refresh_snapshot()

    def disconnect(self):
        with self._lock:
            self._wanted_connected = False
            self._retry_at = None
            self._retry_in = None
            self._audio_error = None
            self._audio_suspended = False
            if self.client is not None:
                self.client.cancel_transmit()
                self.client.disconnect()
        self._publish({"type": "disconnected"})
        self._refresh_snapshot()

    def move(self, room_id, password=None):
        with self._lock:
            if self.client is not None:
                self.client.move(int(room_id), password=password)

    def send_text(self, text):
        with self._lock:
            client = self.client
            if client is None or not getattr(client, "connected", False):
                return False
            if getattr(client, "my_room", None) is None:
                return False
            if not str(text or "").strip():
                return False
            client.send_text(text)
            return True

    def poke(self, member_id, text):
        with self._lock:
            if self.client is not None:
                self.client.poke(int(member_id), text)

    def set_display_name(self, name):
        clean = str(name or "").strip()
        with self._lock:
            self.display_name = clean or None
            client = self.client
            if client is None:
                return
            from partyline.client import default_name

            client.name = self.display_name or default_name(client.identity)

    def apply_audio_settings(self, input=_UNSET, output=_UNSET, tx_gain_db=_UNSET, mic_agc=_UNSET):
        with self._lock:
            options = self.client_options
            device_changed = False
            if input is not _UNSET:
                value = str(input or "").strip() or None
                device_changed = device_changed or options.get("input") != value
                options["input"] = value
            if output is not _UNSET:
                value = str(output or "").strip() or None
                device_changed = device_changed or options.get("output") != value
                options["output"] = value
            if tx_gain_db is not _UNSET:
                options["tx_gain_db"] = float(tx_gain_db)
            if mic_agc is not _UNSET:
                options["mic_agc"] = bool(mic_agc)

            client = self.client
            if client is None:
                return False
            if tx_gain_db is not _UNSET:
                client.set_tx_gain(float(tx_gain_db))
            if mic_agc is not _UNSET:
                client.set_mic_agc(bool(mic_agc))
            if not device_changed:
                return True
            client.cancel_transmit()
            client.set_devices(options.get("input"), options.get("output"))
        self._refresh_snapshot()
        return True

    def set_muted(self, muted):
        with self._lock:
            if self.client is not None:
                self.client.set_muted(bool(muted))

    def set_deaf(self, deaf):
        with self._lock:
            if self.client is not None:
                self.client.set_deaf(bool(deaf))

    def set_mode(self, mode):
        with self._lock:
            if self.client is not None:
                self.client.set_mode(mode)

    def set_transmit(self, down):
        with self._lock:
            client = self.client
            if client is None or self._audio_suspended:
                return False
            if down and (
                getattr(client, "muted", False)
                or not getattr(client, "can_speak_here", True)
                or getattr(client, "tx_pipe", None) is None
            ):
                return False
            client.set_transmit(bool(down))
            return True

    def set_microphone_allowed(self, allowed):
        allowed = bool(allowed)
        with self._lock:
            changed = allowed != self._microphone_allowed
            self._microphone_allowed = allowed
            client = self.client
            if client is not None:
                client.cfg.listen = not allowed
                if not allowed:
                    client.cancel_transmit()
        if self._audio_suspended:
            if changed:
                self._refresh_snapshot()
            return False
        if not changed:
            return False
        return self.refresh_audio(force=True)

    def refresh_audio(self, force=False):
        with self._lock:
            client = self.client
            if client is None or self._audio_suspended or not getattr(client, "connected", False):
                return False
            if not force and getattr(client, "playout", None) is not None:
                if getattr(client, "tx_pipe", None) is not None:
                    return False
                if getattr(client.cfg, "listen", False):
                    return False
            my_room = getattr(client, "my_room", None)
            if my_room is None:
                return False
            room = getattr(client, "channels", {}).get(my_room)
            profile = getattr(client, "audio_profile", None) or getattr(room, "profile", None)
            frame_ms = getattr(client, "frame_ms", None) or getattr(room, "frame_ms", None)
            if not profile or not frame_ms:
                return False
            self._audio_error = None
            client.stop_audio()
            client.configure(profile, int(frame_ms))
            client.apply_transport()
            client.apply_mode()
        self._refresh_snapshot()
        return True

    def pause_audio(self):
        with self._lock:
            self._audio_suspended = True
            client = self.client
            if client is not None:
                client.cancel_transmit()
                client.stop_audio()
            self._audio_error = None
        self._refresh_snapshot()

    def resume_audio(self):
        with self._lock:
            self._audio_suspended = False
        rebuilt = self.refresh_audio()
        if not rebuilt:
            self._refresh_snapshot()
        return rebuilt

    def snapshot(self):
        with self._lock:
            return copy.deepcopy(self._snapshot)

    def drain_events(self):
        events = []
        while True:
            try:
                events.append(self._events.get_nowait())
            except queue.Empty:
                return events

    def history(self):
        with self._lock:
            return list(self._history)

    def _empty_snapshot(self, state):
        return {
            "identity": self.identity_hash,
            "server": {"hash": None, "name": None, "version": None, "motd": ""},
            "connection": {
                "state": state,
                "error": None,
                "kicked": False,
                "connected": False,
                "synced": False,
                "wanted": False,
                "retry_in": None,
                "retry_attempt": 0,
            },
            "me": None,
            "rooms": [],
            "users": [],
            "counts": {"rooms": 0, "users": 0},
            "audio": self._audio_dict(None),
            "transport": {"shared_instance": self.shared_instance},
        }

    def _refresh_snapshot(self):
        with self._lock:
            client = self.client
            if client is None:
                self._snapshot = self._empty_snapshot("starting")
                return
            retry_in = None
            if self._retry_at is not None:
                retry_in = max(0, int(round(self._retry_at - time.time())))
            self._retry_in = retry_in
            server_hash = client.server_hash
            if isinstance(server_hash, bytes):
                server_hash = server_hash.hex()
            rooms = [_channel_dict(channel) for channel in sorted(client.channels.values(), key=lambda item: item.id)]
            users = [
                self._user_dict(client, user)
                for user in sorted(client.users.values(), key=lambda item: (item.name.lower(), item.sid))
            ]
            me = self._user_dict(client, client.me)
            if getattr(client, "tx_pipe", None) is not None:
                self._audio_error = None
            self._snapshot = {
                "identity": self.identity_hash,
                "server": {
                    "hash": server_hash,
                    "name": client.server_name,
                    "version": client.server_version,
                    "motd": client.motd,
                },
                "connection": {
                    "state": client.state,
                    "error": client.error,
                    "kicked": bool(client.kicked),
                    "connected": bool(client.connected),
                    "synced": bool(client.synced),
                    "wanted": self._wanted_connected,
                    "retry_in": retry_in,
                    "retry_attempt": self._retry_index,
                },
                "me": me,
                "rooms": rooms,
                "users": users,
                "counts": {"rooms": len(rooms), "users": len(users)},
                "audio": self._audio_dict(client),
                "transport": {"shared_instance": self.shared_instance},
            }

    def _audio_dict(self, client):
        if client is None:
            return {
                "rx_ready": False,
                "tx_ready": False,
                "transmit": False,
                "ptt_down": False,
                "can_speak": False,
                "mic_allowed": self._microphone_allowed,
                "muted": False,
                "deaf": False,
                "level_db": -120.0,
                "profile": None,
                "frame_ms": None,
                "rx_packets": 0,
                "tx_packets": 0,
                "heard": 0,
                "suspended": self._audio_suspended,
                "error": self._audio_error,
            }
        my_room = getattr(client, "my_room", None)
        channels = getattr(client, "channels", None) or {}
        room = channels.get(my_room) if my_room is not None else None
        profile = getattr(client, "audio_profile", None) or (getattr(room, "profile", None) if room else None)
        frame_ms = getattr(client, "frame_ms", None) or (getattr(room, "frame_ms", None) if room else None)
        try:
            level_db = float(getattr(client, "level", -120.0))
        except (TypeError, ValueError):
            level_db = -120.0
        try:
            tx_packets = client.tx_totals()[0]
        except Exception:
            tx_packets = getattr(client, "tx_packets", 0)
        return {
            "rx_ready": getattr(client, "playout", None) is not None,
            "tx_ready": getattr(client, "tx_pipe", None) is not None,
            "transmit": bool(getattr(client, "transmitting", False)),
            "ptt_down": bool(getattr(client, "ptt_down", False)),
            "can_speak": bool(getattr(client, "can_speak_here", True)),
            "mic_allowed": self._microphone_allowed,
            "muted": bool(getattr(client, "muted", False)),
            "deaf": bool(getattr(client, "deaf", False)),
            "level_db": round(level_db, 1),
            "profile": profile,
            "frame_ms": frame_ms,
            "rx_packets": int(getattr(client, "rx_packets", 0)),
            "tx_packets": int(tx_packets),
            "heard": len(getattr(client, "heard", ()) or ()),
            "suspended": self._audio_suspended,
            "error": self._audio_error,
        }

    def _user_dict(self, client, user):
        if user is None:
            return None
        last_heard = client.last_heard.get(user.sid, 0)
        return {
            "sid": user.sid,
            "name": user.name,
            "identity": user.identity,
            "room": user.room,
            "muted": bool(user.muted),
            "deaf": bool(user.deaf),
            "hops": user.hops,
            "rtt": user.rtt,
            "operator": bool(user.operator),
            "server_muted": bool(user.server_muted),
            "text_only": bool(user.text_only),
            "speaker": bool(user.speaker),
            "speaking": bool(last_heard and time.time() - last_heard < SPEAKING_WINDOW),
            "local_muted": user.sid in client.local_muted,
            "gain_db": client.gains.get(user.sid, 0),
        }

    def _publish(self, payload):
        with self._lock:
            self._sequence += 1
            payload = dict(payload)
            payload["seq"] = self._sequence
            payload["ts"] = time.time()
            self._history.append(payload)
        self._events.put(payload)

    def _serialize_event(self, event):
        kind = event[0]
        if kind in ("channel", "channel_gone"):
            return {"type": kind, "channel": _channel_dict(event[1])}
        if kind in ("user_joined", "user_left"):
            return {"type": kind, "user": self._user_dict(self.client, event[1])}
        if kind in ("user_moved", "user_state"):
            return {
                "type": kind,
                "user": self._user_dict(self.client, event[1]),
                "previous": _jsonable(event[2]) if kind == "user_moved" else self._user_dict(self.client, event[2]),
            }
        if kind in ("text", "poke", "poked"):
            return {
                "type": kind,
                "user": self._user_dict(self.client, event[1]) if event[1] is not None else None,
                "text": _jsonable(event[2]),
            }
        if kind == "room":
            return {
                "type": kind,
                "value": _jsonable(event[1]) if len(event) > 1 else None,
                "can_speak": bool(getattr(self.client, "can_speak_here", True)),
            }
        if kind in ("notice", "info", "motd", "error", "closed", "version"):
            return {"type": kind, "value": _jsonable(event[1]) if len(event) > 1 else None}
        if kind == "denied":
            return {"type": kind, "room_id": _jsonable(event[1]), "reason": _jsonable(event[2])}
        if kind == "room_spec":
            return {"type": kind, "room_id": _jsonable(event[1]), "spec": _jsonable(event[2])}
        if kind == "call_waiting":
            return {"type": kind, "identity": _jsonable(event[1])}
        if kind == "call_done":
            return {"type": kind, "identity": _jsonable(event[1]), "outcome": _jsonable(event[2])}
        if kind in ("connected", "synced", "self_state"):
            return {"type": kind}
        return {"type": kind, "payload": _jsonable(event[1:])}

    def _handle_event(self, event):
        payload = self._serialize_event(event)
        self._publish(payload)
        if payload["type"] == "error" and self.client is not None and self.client.connected:
            with self._lock:
                self._audio_error = str(payload.get("value") or t("engine.error.audio_unavailable"))
        if payload["type"] == "room" and self._audio_suspended and self.client is not None:
            with self._lock:
                self.client.stop_audio()
        if payload["type"] == "connected":
            with self._lock:
                self._retry_index = 0
                self._retry_at = None
                self._retry_in = None
                self._kicked_reported = False

    def _check_retry(self):
        with self._lock:
            if self.client is None or not self._wanted_connected:
                return
            if self.client.connected:
                self._retry_index = 0
                self._retry_at = None
                self._retry_in = None
                self._attempt_at = None
                return
            if (
                self._attempt_at is not None
                and self.client.state in ("connecting", "waiting for server")
                and time.time() - self._attempt_at > CONNECT_WATCHDOG
            ):
                self.client.error = t("engine.error.connect_timeout")
                self.client.disconnect()
                self._attempt_at = None
                return
            if self.client.kicked:
                if not self._kicked_reported:
                    self._kicked_reported = True
                    self._wanted_connected = False
                    self._retry_at = None
                    self._retry_in = None
                    reason = self.client.error or t("engine.error.server_rejected")
                    self._publish({"type": "retry_stopped", "reason": reason})
                return
            if self._retry_at is not None:
                if time.time() >= self._retry_at:
                    self._retry_at = None
                    self._retry_in = None
                    self._reconnect()
                return
            if self.client.state == "closed" or (self.client.state == "idle" and self.client.error):
                delay = RETRY_DELAYS[min(self._retry_index, len(RETRY_DELAYS) - 1)]
                self._retry_index += 1
                self._retry_at = time.time() + delay
                self._publish({"type": "retry_scheduled", "delay": delay, "attempt": self._retry_index})

    def _reconnect(self):
        params = self._last_connect
        if not params:
            return
        self._audio_error = None
        self.client.kicked = False
        self.client.error = None
        self.client.cancel_transmit()
        self._attempt_at = time.time()
        self.client.connect(
            bytes.fromhex(params["hash"]),
            room=params["room"],
            password=params["password"],
            server_password=params["server_password"],
        )

    def _dispatch_loop(self):
        while not self._stop.is_set():
            while True:
                try:
                    event = self.client.events.popleft()
                except IndexError:
                    break
                self._handle_event(event)
            self._check_retry()
            self._refresh_snapshot()
            time.sleep(0.05)
