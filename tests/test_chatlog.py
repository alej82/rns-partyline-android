import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app"))

from partyline_android import i18n
from partyline_android.chatlog import ChatLog


def setUpModule():
    i18n.reset_for_tests("es")


def tearDownModule():
    i18n.reset_for_tests("es")


def _user(sid=1, name="Ana", operator=False, room=1):
    return {"sid": sid, "name": name, "room": room, "operator": operator}


def _channel(room_id=1, name="Lobby", profile="opus-high", frame_ms=20):
    return {"id": room_id, "name": name, "profile": profile, "frame_ms": frame_ms}


def _event(kind, seq=1, ts=1000.0, **fields):
    return {"type": kind, "seq": seq, "ts": ts, **fields}


class ChatLogMessageTests(unittest.TestCase):
    def test_text_message_rendering(self):
        log = ChatLog()
        lines = log.ingest(_event("text", user=_user(), text="hola"), me_sid=2)
        self.assertEqual(len(lines), 1)
        line = lines[0]
        self.assertEqual(line["kind"], "chat")
        self.assertEqual(line["who"], "Ana")
        self.assertEqual(line["text"], "hola")
        self.assertFalse(line["own"])
        self.assertEqual(line["ts"], 1000.0)
        self.assertEqual(line["seq"], 1)

    def test_own_message_detection(self):
        log = ChatLog()
        lines = log.ingest(_event("text", user=_user(sid=7), text="mío"), me_sid=7)
        self.assertTrue(lines[0]["own"])

    def test_unknown_sender(self):
        log = ChatLog()
        lines = log.ingest(_event("text", user=None, text="hola"), me_sid=7)
        self.assertEqual(lines[0]["who"], "Desconocido")
        self.assertFalse(lines[0]["own"])

    def test_notice_and_info(self):
        log = ChatLog()
        notice = log.ingest(_event("notice", value="reinicio"))[0]
        self.assertEqual((notice["kind"], notice["text"]), ("warning", "*** reinicio"))
        info = log.ingest(_event("info", seq=2, value="buscando ruta"))[0]
        self.assertEqual((info["kind"], info["text"]), ("system", "... buscando ruta"))

    def test_motd_present_and_empty(self):
        log = ChatLog()
        present = log.ingest(_event("motd", value="Bienvenidos"))[0]
        self.assertEqual(present["text"], "Mensaje del día: Bienvenidos")
        empty = log.ingest(_event("motd", seq=2, value=""))[0]
        self.assertEqual(empty["text"], "Mensaje del día borrado.")

    def test_version_mismatch_is_warning(self):
        line = ChatLog().ingest(_event("version", value="1.0.4"))[0]
        self.assertEqual(line["kind"], "warning")
        self.assertIn("1.0.4", line["text"])


class ChatLogRoomTests(unittest.TestCase):
    def test_room_entry_uses_channel_details(self):
        log = ChatLog()
        log.ingest(_event("channel", channel=_channel()))
        lines = log.ingest(_event("room", seq=2, value=1))
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["text"], "Entraste en «Lobby» (opus-high, 20 ms)")

    def test_room_entry_unknown_room(self):
        lines = ChatLog().ingest(_event("room", value=9))
        self.assertEqual(lines[0]["text"], "Entraste en la sala 9")

    def test_room_entry_listen_only_suffix(self):
        log = ChatLog()
        log.ingest(_event("channel", channel=_channel()))
        lines = log.ingest(_event("room", seq=2, value=1, can_speak=False))
        self.assertIn("solo escucha", lines[0]["text"])

    def test_room_exit(self):
        log = ChatLog()
        lines = log.ingest(_event("room", value=None))
        self.assertEqual(lines[0]["text"], "Saliste de la sala")

    def test_room_change_adds_separator(self):
        log = ChatLog()
        log.ingest(_event("channel", channel=_channel(1, "Lobby")))
        log.ingest(_event("channel", seq=2, channel=_channel(2, "Café")))
        log.ingest(_event("room", seq=3, value=1))
        lines = log.ingest(_event("room", seq=4, value=2))
        self.assertEqual([line["text"] for line in lines], ["----------", "Entraste en «Café» (opus-high, 20 ms)"])

    def test_first_room_has_no_separator(self):
        log = ChatLog()
        log.ingest(_event("channel", channel=_channel()))
        lines = log.ingest(_event("room", seq=2, value=1))
        self.assertEqual(len(lines), 1)

    def test_room_removal(self):
        line = ChatLog().ingest(_event("channel_gone", channel=_channel(name="Lobby")))[0]
        self.assertEqual(line["text"], "La sala «Lobby» fue eliminada")

    def test_denied_with_known_room(self):
        log = ChatLog()
        log.ingest(_event("channel", channel=_channel(3, "Privada")))
        line = log.ingest(_event("denied", seq=2, room_id=3, reason="contraseña incorrecta"))[0]
        self.assertEqual(line["kind"], "error")
        self.assertEqual(line["text"], "No puedes entrar en «Privada»: contraseña incorrecta")

    def test_denied_without_room(self):
        line = ChatLog().ingest(_event("denied", room_id=None, reason="baneado"))[0]
        self.assertEqual(line["text"], "Rechazado: baneado")


class ChatLogMemberTests(unittest.TestCase):
    def test_joins_are_suppressed_until_synced(self):
        log = ChatLog()
        self.assertEqual(log.ingest(_event("user_joined", user=_user(sid=2, name="Luis")), me_sid=1), [])
        log.ingest(_event("synced", seq=2))
        lines = log.ingest(_event("user_joined", seq=3, user=_user(sid=2, name="Luis")), me_sid=1)
        self.assertEqual(lines[0]["text"], "Luis se conectó")

    def test_own_join_is_ignored(self):
        log = ChatLog()
        log.ingest(_event("synced"))
        self.assertEqual(log.ingest(_event("user_joined", seq=2, user=_user(sid=1)), me_sid=1), [])

    def test_connected_resets_sync_gate(self):
        log = ChatLog()
        log.ingest(_event("synced"))
        log.ingest(_event("connected", seq=2))
        self.assertEqual(log.ingest(_event("user_joined", seq=3, user=_user(sid=2)), me_sid=1), [])

    def test_leave(self):
        line = ChatLog().ingest(_event("user_left", user=_user(sid=2, name="Luis")))[0]
        self.assertEqual(line["text"], "Luis se desconectó")

    def test_self_leave_with_stale_sid_is_ignored(self):
        user = dict(_user(sid=99, name="Ana"), identity="self-identity")
        lines = ChatLog().ingest(_event("user_left", user=user), me_sid=1, me_identity="self-identity")
        self.assertEqual(lines, [])

    def test_self_join_with_stale_sid_is_ignored_after_sync(self):
        log = ChatLog()
        log.ingest(_event("synced"))
        user = dict(_user(sid=99, name="Ana"), identity="self-identity")
        lines = log.ingest(_event("user_joined", seq=2, user=user), me_sid=1, me_identity="self-identity")
        self.assertEqual(lines, [])

    def test_move(self):
        log = ChatLog()
        log.ingest(_event("channel", channel=_channel(2, "Música")))
        lines = log.ingest(_event("user_moved", seq=2, user=_user(sid=2, name="Luis", room=2)), me_sid=1)
        self.assertEqual(lines[0]["text"], "Luis se movió a «Música»")

    def test_own_move_is_ignored(self):
        log = ChatLog()
        lines = log.ingest(_event("user_moved", user=_user(sid=1, room=2)), me_sid=1)
        self.assertEqual(lines, [])

    def test_operator_promotion_and_demotion(self):
        log = ChatLog()
        promoted = log.ingest(
            _event("user_state", user=_user(sid=2, operator=True), previous=_user(sid=2, operator=False)),
            me_sid=1,
        )
        self.assertEqual(promoted[0]["text"], "Ana ahora es operador")
        demoted = log.ingest(
            _event("user_state", seq=2, user=_user(sid=2, operator=False), previous=_user(sid=2, operator=True)),
            me_sid=1,
        )
        self.assertEqual(demoted[0]["text"], "Ana ya no es operador")

    def test_unchanged_operator_state_is_ignored(self):
        log = ChatLog()
        lines = log.ingest(
            _event("user_state", user=_user(sid=2, operator=True), previous=_user(sid=2, operator=True)),
            me_sid=1,
        )
        self.assertEqual(lines, [])


class ChatLogCallAndErrorTests(unittest.TestCase):
    def test_call_waiting_and_done(self):
        log = ChatLog()
        waiting = log.ingest(_event("call_waiting", identity="ab" * 16))[0]
        self.assertEqual(waiting["kind"], "warning")
        self.assertIn("en espera", waiting["text"])
        done = log.ingest(_event("call_done", seq=2, identity="ab" * 16, outcome="timeout"))[0]
        self.assertEqual(done["text"], f"La llamada de {'ab' * 16} no fue contestada a tiempo")

    def test_incoming_and_outgoing_pokes(self):
        log = ChatLog()
        poke = log.ingest(_event("poke", user=_user(name="Luis"), text="eh"))[0]
        self.assertEqual((poke["kind"], poke["text"]), ("warning", "Luis te hizo un toque: eh"))
        poked = log.ingest(_event("poked", seq=2, user=_user(name="Luis"), text="eh"))[0]
        self.assertEqual(poked["text"], "Tú le hiciste un toque a Luis: eh")

    def test_error_and_connection_loss(self):
        log = ChatLog()
        error = log.ingest(_event("error", value="enlace roto"))[0]
        self.assertEqual((error["kind"], error["text"]), ("error", "Error: enlace roto"))
        closed = log.ingest(_event("closed", seq=2, value="timeout"))[0]
        self.assertEqual((closed["kind"], closed["text"]), ("error", "Conexión perdida: timeout"))


class ChatLogEnglishTests(unittest.TestCase):
    def setUp(self):
        i18n.set_language("en")

    def tearDown(self):
        i18n.set_language("es")

    def test_english_system_lines(self):
        log = ChatLog()
        log.ingest(_event("channel", channel=_channel()))
        joined = log.ingest(_event("room", seq=2, value=1))[0]
        self.assertEqual(joined["text"], "You joined “Lobby” (opus-high, 20 ms)")

        log.ingest(_event("synced", seq=3))
        member = log.ingest(_event("user_joined", seq=4, user=_user(sid=2, name="Luis")), me_sid=1)[0]
        self.assertEqual(member["text"], "Luis connected")

    def test_data_names_are_not_translated(self):
        log = ChatLog()
        log.ingest(_event("channel", channel=_channel(2, "Música")))
        line = log.ingest(
            _event("user_moved", seq=2, user=_user(sid=2, name="Luis", room=2)),
            me_sid=1,
        )[0]
        self.assertIn("Luis", line["text"])
        self.assertIn("Música", line["text"])

    def test_english_call_and_poke(self):
        log = ChatLog()
        done = log.ingest(_event("call_done", identity="ab" * 16, outcome="timeout"))[0]
        self.assertEqual(done["text"], f"The call from {'ab' * 16} was not answered in time")
        poke = log.ingest(_event("poke", seq=2, user=_user(name="Luis"), text="hey"))[0]
        self.assertEqual(poke["text"], "Luis poked you: hey")


class ChatLogLifecycleTests(unittest.TestCase):
    def test_ignored_events_do_not_create_lines(self):
        log = ChatLog()
        for seq, kind in enumerate(
            ["channel", "room_spec", "self_state", "transport", "synced", "connected",
             "retry_scheduled", "retry_stopped", "disconnected"],
            start=1,
        ):
            event = _event(kind, seq=seq)
            if kind == "channel":
                event["channel"] = _channel()
            self.assertEqual(log.ingest(event, me_sid=1), [], kind)

    def test_history_is_bounded(self):
        log = ChatLog(limit=3)
        for seq in range(1, 6):
            log.ingest(_event("text", seq=seq, user=_user(), text=f"m{seq}"))
        self.assertEqual([line["text"] for line in log.lines()], ["m3", "m4", "m5"])

    def test_clear_removes_lines_and_state(self):
        log = ChatLog()
        log.ingest(_event("channel", channel=_channel()))
        log.ingest(_event("synced", seq=2))
        log.ingest(_event("room", seq=3, value=1))
        log.ingest(_event("text", seq=4, user=_user(), text="hola"))
        log.clear()
        self.assertEqual(log.lines(), [])
        self.assertEqual(log.ingest(_event("user_joined", seq=5, user=_user(sid=2)), me_sid=1), [])
        lines = log.ingest(_event("room", seq=6, value=1))
        self.assertEqual(lines[0]["text"], "Entraste en la sala 1")


if __name__ == "__main__":
    unittest.main()
