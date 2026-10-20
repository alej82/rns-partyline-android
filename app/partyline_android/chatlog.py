import collections
import time

LINE_LIMIT = 500

CALL_OUTCOMES = {
    "answered": "fue contestada",
    "rejected": "fue rechazada",
    "timeout": "no fue contestada a tiempo",
    "gone": "se colgó",
}

IGNORED_EVENTS = {
    "channel",
    "room_spec",
    "self_state",
    "transport",
    "synced",
    "connected",
    "disconnected",
}


class ChatLog:
    """Turns serialized engine events into bounded, display-ready chat lines."""

    def __init__(self, limit=LINE_LIMIT):
        self._limit = limit
        self._lines = collections.deque(maxlen=limit)
        self._rooms = {}
        self._synced = False
        self._own_room = None
        self._me_identity = None

    def ingest(self, event, me_sid=None, me_identity=None):
        if not isinstance(event, dict):
            return []
        self._me_identity = me_identity
        kind = event.get("type")
        if kind in IGNORED_EVENTS or str(kind or "").startswith("retry_"):
            if kind == "connected":
                self._synced = False
                self._rooms = {}
                self._own_room = None
            elif kind == "synced":
                self._synced = True
            elif kind == "channel":
                self._track_channel(event.get("channel"))
            return []
        handler = getattr(self, f"_event_{kind}", None)
        if handler is None:
            return []
        return handler(event, me_sid) or []

    def lines(self):
        return list(self._lines)

    def clear(self):
        self._lines.clear()
        self._rooms = {}
        self._synced = False
        self._own_room = None
        self._me_identity = None

    def _add(self, event, kind, text, who=None, own=False):
        line = {
            "seq": event.get("seq"),
            "ts": event.get("ts") if event.get("ts") is not None else time.time(),
            "kind": kind,
            "who": who,
            "text": text,
            "own": own,
        }
        self._lines.append(line)
        return line

    def _track_channel(self, channel):
        if not isinstance(channel, dict) or channel.get("id") is None:
            return
        try:
            room_id = int(channel["id"])
        except (TypeError, ValueError):
            return
        self._rooms[room_id] = {
            "name": channel.get("name"),
            "profile": channel.get("profile"),
            "frame_ms": channel.get("frame_ms"),
        }

    def _room_name(self, room_id):
        if room_id is None:
            return None
        try:
            room_id = int(room_id)
        except (TypeError, ValueError):
            return str(room_id)
        room = self._rooms.get(room_id) or {}
        return room.get("name") or f"sala {room_id}"

    def _user_name(self, user):
        if not isinstance(user, dict):
            return "Desconocido"
        return user.get("name") or "Desconocido"

    def _is_self(self, user, me_sid):
        if not isinstance(user, dict):
            return False
        if me_sid is not None and user.get("sid") == me_sid:
            return True
        return bool(self._me_identity and user.get("identity") == self._me_identity)

    ### EVENT MAPPING ###
    def _event_text(self, event, me_sid):
        user = event.get("user")
        who = self._user_name(user)
        own = self._is_self(user, me_sid)
        return [self._add(event, "chat", str(event.get("text") or ""), who=who, own=own)]

    def _event_notice(self, event, me_sid):
        return [self._add(event, "warning", f"*** {event.get('value') or ''}".rstrip())]

    def _event_info(self, event, me_sid):
        value = event.get("value")
        text = f"... {value}" if value else "..."
        return [self._add(event, "system", text)]

    def _event_motd(self, event, me_sid):
        value = event.get("value")
        text = f"Mensaje del día: {value}" if value else "Mensaje del día borrado."
        return [self._add(event, "system", text)]

    def _event_version(self, event, me_sid):
        value = event.get("value") or "desconocida"
        text = f"El servidor usa Partyline {value}; actualiza para que coincidan."
        return [self._add(event, "warning", text)]

    def _event_room(self, event, me_sid):
        room_id = event.get("value")
        if room_id is None:
            self._own_room = None
            return [self._add(event, "system", "Saliste de la sala")]
        lines = []
        if self._own_room is not None and self._own_room != room_id:
            lines.append(self._add(event, "system", "----------"))
        self._own_room = room_id
        try:
            details = self._rooms.get(int(room_id)) or {}
        except (TypeError, ValueError):
            details = {}
        name = details.get("name")
        profile = details.get("profile")
        frame_ms = details.get("frame_ms")
        if name:
            text = f"Entraste en «{name}»"
            if profile and frame_ms is not None:
                text += f" ({profile}, {frame_ms} ms)"
        else:
            text = f"Entraste en la sala {room_id}"
        if event.get("can_speak") is False:
            text += " · solo escucha"
        lines.append(self._add(event, "system", text))
        return lines

    def _event_denied(self, event, me_sid):
        reason = event.get("reason") or "sin motivo"
        room_id = event.get("room_id")
        if room_id is None:
            text = f"Rechazado: {reason}"
        else:
            text = f"No puedes entrar en «{self._room_name(room_id)}»: {reason}"
        return [self._add(event, "error", text)]

    def _event_channel_gone(self, event, me_sid):
        channel = event.get("channel") or {}
        name = channel.get("name") or self._room_name(channel.get("id")) or "desconocida"
        return [self._add(event, "system", f"La sala «{name}» fue eliminada")]

    def _event_user_joined(self, event, me_sid):
        user = event.get("user")
        if not self._synced or not isinstance(user, dict) or self._is_self(user, me_sid):
            return []
        return [self._add(event, "system", f"{self._user_name(user)} se conectó")]

    def _event_user_left(self, event, me_sid):
        user = event.get("user")
        if not isinstance(user, dict) or self._is_self(user, me_sid):
            return []
        return [self._add(event, "system", f"{self._user_name(user)} se desconectó")]

    def _event_user_moved(self, event, me_sid):
        user = event.get("user")
        if not isinstance(user, dict) or self._is_self(user, me_sid):
            return []
        room_id = user.get("room")
        if room_id is None:
            text = f"{self._user_name(user)} salió de la sala"
        else:
            text = f"{self._user_name(user)} se movió a «{self._room_name(room_id)}»"
        return [self._add(event, "system", text)]

    def _event_user_state(self, event, me_sid):
        user = event.get("user")
        previous = event.get("previous")
        if not isinstance(user, dict) or not isinstance(previous, dict):
            return []
        if self._is_self(user, me_sid):
            return []
        if bool(user.get("operator")) == bool(previous.get("operator")):
            return []
        name = self._user_name(user)
        text = f"{name} ahora es operador" if user.get("operator") else f"{name} ya no es operador"
        return [self._add(event, "system", text)]

    def _event_call_waiting(self, event, me_sid):
        identity = event.get("identity") or "desconocido"
        return [self._add(event, "warning", f"Llamada de {identity} en espera")]

    def _event_call_done(self, event, me_sid):
        identity = event.get("identity") or "desconocido"
        outcome = event.get("outcome")
        text = CALL_OUTCOMES.get(outcome, str(outcome or "terminó"))
        return [self._add(event, "system", f"La llamada de {identity} {text}")]

    def _event_poke(self, event, me_sid):
        text = f"{self._user_name(event.get('user'))} te hizo un toque: {event.get('text') or ''}"
        return [self._add(event, "warning", text.rstrip())]

    def _event_poked(self, event, me_sid):
        text = f"Tú le hiciste un toque a {self._user_name(event.get('user'))}: {event.get('text') or ''}"
        return [self._add(event, "system", text.rstrip())]

    def _event_error(self, event, me_sid):
        value = event.get("value")
        return [self._add(event, "error", f"Error: {value}" if value else "Error")]

    def _event_closed(self, event, me_sid):
        value = event.get("value")
        text = f"Conexión perdida: {value}" if value else "Conexión perdida"
        return [self._add(event, "error", text)]
