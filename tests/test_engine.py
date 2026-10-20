import collections
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app"))

os.environ.setdefault("PARTYLINE_CONFIG_DIR", "/tmp/partyline-android-tests/config")
os.environ.setdefault("PARTYLINE_RNS_DIR", "/tmp/partyline-android-tests/rns")

from partyline_android.engine import Engine, RETRY_DELAYS


class FakeClient:
    def __init__(self):
        self.state = "idle"
        self.error = "connection failed"
        self.kicked = False
        self.connected = False
        self.events = collections.deque()
        self.connect_calls = []
        self.identity = SimpleNamespace(hash=b"\x01\x02\x03\x04\x05\x06")
        self.name = "tester"

    def connect(self, *args, **kwargs):
        self.connect_calls.append((args, kwargs))

    def disconnect(self):
        self.state = "idle"

    def cancel_transmit(self):
        pass


def _channel(room_id=1, profile="opus-high", frame_ms=20):
    return SimpleNamespace(
        id=room_id,
        name="Lobby",
        profile=profile,
        frame_ms=frame_ms,
        access=None,
        description="",
        dialin_number=None,
        ptt_jitter_ms=0,
        flags=0,
        ptt=False,
        broadcast=False,
        music=False,
        locked=False,
    )


class FakeAudioClient(FakeClient):
    def __init__(self):
        super().__init__()
        self.state = "connected"
        self.error = None
        self.kicked = False
        self.connected = True
        self.synced = True
        self.server_hash = None
        self.server_name = "Server"
        self.server_version = "1"
        self.motd = ""
        self.channels = {1: _channel()}
        self.users = {}
        self.last_heard = {}
        self.local_muted = set()
        self.gains = {}
        self.me = None
        self.my_sid = None
        self.my_room = 1
        self.can_speak_here = True
        self.playout = object()
        self.tx_pipe = object()
        self.transmitting = False
        self.ptt_down = False
        self.muted = False
        self.deaf = False
        self.level = -42.5
        self.audio_profile = "opus-high"
        self.frame_ms = 20
        self.rx_packets = 7
        self.heard = {1, 2}
        self.tx_packets = 3
        self.cfg = SimpleNamespace(listen=False, text_only=False)
        self.calls = []
        self.text_sent = []

    def stop_audio(self):
        self.calls.append("stop_audio")
        self.playout = None
        self.tx_pipe = None
        self.audio_profile = None
        self.frame_ms = None

    def configure(self, profile, frame_ms):
        self.calls.append(("configure", profile, frame_ms))
        self.playout = object()
        self.tx_pipe = None if self.cfg.listen else object()
        self.audio_profile = profile
        self.frame_ms = frame_ms

    def apply_transport(self):
        self.calls.append("apply_transport")

    def apply_mode(self):
        self.calls.append("apply_mode")

    def cancel_transmit(self):
        self.calls.append("cancel_transmit")
        self.ptt_down = False
        self.transmitting = False

    def set_transmit(self, down):
        self.calls.append(("transmit", down))
        self.ptt_down = bool(down)
        self.transmitting = bool(down)

    def tx_totals(self):
        return (self.tx_packets, 0, 0)

    def send_text(self, text):
        self.text_sent.append(text)

    def set_tx_gain(self, decibels):
        self.calls.append(("tx_gain", decibels))
        self.tx_gain_db = decibels

    def set_mic_agc(self, enabled):
        self.calls.append(("mic_agc", enabled))
        self.mic_agc = enabled

    def set_devices(self, input_name, output_name):
        self.calls.append(("set_devices", input_name, output_name))
        self.cfg.input = input_name
        self.cfg.output = output_name
        if self.playout:
            profile = self.audio_profile
            frame_ms_value = self.frame_ms
            self.stop_audio()
            self.configure(profile, frame_ms_value)


class EngineAudioTests(unittest.TestCase):
    def make_engine(self):
        engine = Engine()
        engine.client = FakeAudioClient()
        return engine

    def test_audio_snapshot_fields(self):
        engine = self.make_engine()
        engine._refresh_snapshot()
        audio = engine.snapshot()["audio"]
        self.assertTrue(audio["rx_ready"])
        self.assertTrue(audio["tx_ready"])
        self.assertFalse(audio["transmit"])
        self.assertFalse(audio["ptt_down"])
        self.assertTrue(audio["can_speak"])
        self.assertEqual(audio["level_db"], -42.5)
        self.assertEqual(audio["profile"], "opus-high")
        self.assertEqual(audio["frame_ms"], 20)
        self.assertEqual(audio["rx_packets"], 7)
        self.assertEqual(audio["tx_packets"], 3)
        self.assertEqual(audio["heard"], 2)
        self.assertFalse(audio["suspended"])
        self.assertIsNone(audio["error"])

    def test_audio_error_is_state_not_connection_failure(self):
        engine = self.make_engine()
        engine.client.tx_pipe = None
        engine._handle_event(("error", "micrófono no disponible"))
        engine._refresh_snapshot()
        self.assertEqual(engine.snapshot()["audio"]["error"], "micrófono no disponible")
        self.assertIsNone(engine.snapshot()["connection"]["error"])
        self.assertTrue(engine.snapshot()["connection"]["connected"])

    def test_successful_audio_clears_error(self):
        engine = self.make_engine()
        engine._audio_error = "micrófono no disponible"
        engine._refresh_snapshot()
        self.assertIsNone(engine.snapshot()["audio"]["error"])

    def test_refresh_audio_uses_current_room_profile(self):
        engine = self.make_engine()
        client = engine.client
        client.audio_profile = None
        client.frame_ms = None
        client.tx_pipe = None
        client.channels = {1: _channel(profile="codec2-3200", frame_ms=200)}
        self.assertTrue(engine.refresh_audio())
        self.assertIn("stop_audio", client.calls)
        self.assertIn(("configure", "codec2-3200", 200), client.calls)
        self.assertIn("apply_transport", client.calls)

    def test_microphone_denied_builds_listen_only(self):
        engine = self.make_engine()
        client = engine.client
        engine.set_microphone_allowed(False)
        self.assertTrue(client.cfg.listen)
        self.assertIn("cancel_transmit", client.calls)
        self.assertIn(("configure", "opus-high", 20), client.calls)
        self.assertFalse(engine.snapshot()["audio"]["mic_allowed"])
        self.assertFalse(engine.snapshot()["audio"]["tx_ready"])

    def test_microphone_granted_rebuilds_transmit(self):
        engine = self.make_engine()
        client = engine.client
        engine.set_microphone_allowed(False)
        client.calls.clear()
        engine.set_microphone_allowed(True)
        self.assertFalse(client.cfg.listen)
        self.assertIn(("configure", "opus-high", 20), client.calls)
        self.assertTrue(engine.snapshot()["audio"]["mic_allowed"])
        self.assertTrue(engine.snapshot()["audio"]["tx_ready"])

    def test_refresh_audio_is_noop_when_already_ready(self):
        engine = self.make_engine()
        client = engine.client
        self.assertFalse(engine.refresh_audio())
        self.assertEqual(client.calls, [])

    def test_pause_cancels_ptt_and_stops_audio(self):
        engine = self.make_engine()
        client = engine.client
        client.ptt_down = True
        client.transmitting = True
        engine.pause_audio()
        self.assertIn("cancel_transmit", client.calls)
        self.assertIn("stop_audio", client.calls)
        self.assertFalse(client.ptt_down)
        self.assertFalse(client.transmitting)
        self.assertTrue(engine.snapshot()["audio"]["suspended"])

    def test_resume_rebuilds_audio(self):
        engine = self.make_engine()
        client = engine.client
        engine.pause_audio()
        client.calls.clear()
        self.assertTrue(engine.resume_audio())
        self.assertFalse(engine._audio_suspended)
        self.assertIn(("configure", "opus-high", 20), client.calls)

    def test_room_change_while_suspended_stops_audio(self):
        engine = self.make_engine()
        client = engine.client
        engine.pause_audio()
        client.playout = object()
        client.tx_pipe = object()
        client.calls.clear()
        engine._handle_event(("room", 1))
        self.assertIn("stop_audio", client.calls)

    def test_set_transmit_gating(self):
        engine = self.make_engine()
        client = engine.client
        self.assertTrue(engine.set_transmit(True))
        self.assertIn(("transmit", True), client.calls)
        self.assertTrue(engine.set_transmit(False))
        client.calls.clear()
        client.muted = True
        self.assertFalse(engine.set_transmit(True))
        client.muted = False
        client.can_speak_here = False
        self.assertFalse(engine.set_transmit(True))
        client.can_speak_here = True
        client.tx_pipe = None
        self.assertFalse(engine.set_transmit(True))
        self.assertEqual(client.calls, [])


class EngineTextTests(unittest.TestCase):
    def make_engine(self):
        engine = Engine()
        engine.client = FakeAudioClient()
        return engine

    def test_send_text_while_connected_and_in_room(self):
        engine = self.make_engine()
        self.assertTrue(engine.send_text("hola"))
        self.assertEqual(engine.client.text_sent, ["hola"])

    def test_send_text_does_not_publish_a_second_echo(self):
        engine = self.make_engine()
        self.assertTrue(engine.send_text("hola"))
        echoed = [event for event in engine.drain_events() if event["type"] == "text"]
        self.assertEqual(echoed, [])

    def test_send_text_is_dropped_when_disconnected(self):
        engine = self.make_engine()
        engine.client.connected = False
        self.assertFalse(engine.send_text("hola"))
        self.assertEqual(engine.client.text_sent, [])

    def test_send_text_is_dropped_without_a_room(self):
        engine = self.make_engine()
        engine.client.my_room = None
        self.assertFalse(engine.send_text("hola"))
        self.assertEqual(engine.client.text_sent, [])

    def test_send_text_is_dropped_for_whitespace(self):
        engine = self.make_engine()
        self.assertFalse(engine.send_text("   \n\t"))
        self.assertFalse(engine.send_text(""))
        self.assertFalse(engine.send_text(None))
        self.assertEqual(engine.client.text_sent, [])

    def test_send_text_works_when_listen_only(self):
        engine = self.make_engine()
        engine.client.cfg.listen = True
        engine.client.tx_pipe = None
        self.assertTrue(engine.send_text("hola"))
        self.assertEqual(engine.client.text_sent, ["hola"])


    def test_client_send_text_truncates_on_a_character_boundary(self):
        from partyline.client import Client, Config
        from partyline.common import MAX_TEXT

        client = Client(Config(), SimpleNamespace(hash=b"\x00"), "tester")
        client.state = "connected"
        client.my_room = 1
        sent = []
        client.send = lambda payload: sent.append(payload)
        client.send_text("á" * 400)
        kind, _user, text = client.events.popleft()
        self.assertEqual(kind, "text")
        self.assertEqual(len(sent), 1)
        self.assertTrue(text)
        self.assertLessEqual(len(text.encode("utf-8")), MAX_TEXT)
        self.assertEqual(text, "á" * (MAX_TEXT // 2))


class EngineSettingsTests(unittest.TestCase):
    def make_engine(self, **kwargs):
        engine = Engine(**kwargs)
        engine.client = FakeAudioClient()
        return engine

    def test_set_display_name_updates_client_and_uses_next_connection(self):
        engine = self.make_engine()
        engine.set_display_name("Nueva")
        self.assertEqual(engine.display_name, "Nueva")
        self.assertEqual(engine.client.name, "Nueva")

    def test_empty_display_name_falls_back_to_guest(self):
        engine = self.make_engine()
        engine.set_display_name("Nueva")
        engine.set_display_name("")
        self.assertIsNone(engine.display_name)
        self.assertEqual(engine.client.name, "guest-010203")

    def test_startup_audio_options_are_client_options(self):
        engine = Engine(
            client_options={"input": "Mic", "output": "Spk", "tx_gain_db": 6.0, "mic_agc": True}
        )
        self.assertEqual(engine.client_options["input"], "Mic")
        self.assertEqual(engine.client_options["output"], "Spk")
        self.assertEqual(engine.client_options["tx_gain_db"], 6.0)
        self.assertTrue(engine.client_options["mic_agc"])

    def test_apply_audio_settings_applies_gain_and_agc_live(self):
        engine = self.make_engine()
        client = engine.client
        engine.apply_audio_settings(tx_gain_db=4.5, mic_agc=True)
        self.assertIn(("tx_gain", 4.5), client.calls)
        self.assertIn(("mic_agc", True), client.calls)
        self.assertNotIn("set_devices", [call[0] for call in client.calls if isinstance(call, tuple)])
        self.assertEqual(engine.client_options["tx_gain_db"], 4.5)
        self.assertTrue(engine.client_options["mic_agc"])

    def test_device_change_cancels_transmit_before_rebuild(self):
        engine = self.make_engine()
        client = engine.client
        client.ptt_down = True
        client.transmitting = True
        engine.apply_audio_settings(input="Mic", output="Spk")
        names = [call[0] if isinstance(call, tuple) else call for call in client.calls]
        self.assertIn("cancel_transmit", names)
        self.assertIn("set_devices", names)
        self.assertLess(names.index("cancel_transmit"), names.index("set_devices"))
        self.assertIn(("set_devices", "Mic", "Spk"), client.calls)
        self.assertFalse(client.ptt_down)
        self.assertTrue(engine.snapshot()["connection"]["connected"])

    def test_default_device_is_applied_when_previously_set(self):
        engine = self.make_engine()
        client = engine.client
        engine.client_options["input"] = "Mic"
        engine.apply_audio_settings(input=None)
        self.assertIsNone(engine.client_options["input"])
        self.assertIn(("set_devices", None, None), client.calls)

    def test_audio_settings_without_client_are_stored(self):
        engine = Engine()
        self.assertFalse(engine.apply_audio_settings(input="Mic", tx_gain_db=2.0))
        self.assertEqual(engine.client_options["input"], "Mic")
        self.assertEqual(engine.client_options["tx_gain_db"], 2.0)


class ClientTransmitTests(unittest.TestCase):
    class Packetizer:
        def __init__(self):
            self.squelched = True
            self.edge_guard = False

        def squelch(self):
            self.squelched = True

        def unsquelch(self):
            self.squelched = False

    def test_welcome_clears_stale_session_state(self):
        from partyline.client import Client, Config

        client = Client(Config(), SimpleNamespace(hash=b"\x00"), "tester")
        client.users[99] = object()
        client.channels[1] = object()
        client.last_heard[99] = 1.0
        client.local_muted.add(99)
        client.gains[99] = 3
        client._reorder[99] = 1
        client.welcome({"ver": 1, "sid": 5, "name": "Server", "app": "1.0.5"})
        self.assertEqual(client.users, {})
        self.assertEqual(client.channels, {})
        self.assertEqual(client.last_heard, {})
        self.assertEqual(client.local_muted, set())
        self.assertEqual(client.gains, {})
        self.assertEqual(client._reorder, {})
        self.assertEqual(client.my_sid, 5)

    def test_release_uses_hang_and_cancel_is_immediate(self):
        from partyline.client import Client, Config

        client = Client(Config(), SimpleNamespace(hash=b"\x00"), "tester")
        self.assertFalse(client.muted)
        self.assertFalse(client.deaf)
        client.packetizer = self.Packetizer()
        client.tx_pipe = object()
        client.set_transmit(True)
        self.assertTrue(client.ptt_down)
        self.assertFalse(client.packetizer.squelched)
        client.set_transmit(False)
        self.assertTrue(client.ptt_down)
        client.cancel_transmit()
        self.assertFalse(client.ptt_down)
        self.assertTrue(client.packetizer.squelched)


class EngineBackoffTests(unittest.TestCase):
    def make_engine(self):
        engine = Engine()
        engine.client = FakeClient()
        engine._wanted_connected = True
        engine._last_connect = {"hash": "00" * 16, "room": None, "password": None, "server_password": None}
        return engine

    def test_retry_delays(self):
        engine = self.make_engine()
        now = [1000.0]
        delays = []
        with patch("partyline_android.engine.time.time", side_effect=lambda: now[0]):
            for attempt in range(len(RETRY_DELAYS) + 1):
                engine._check_retry()
                self.assertIsNotNone(engine._retry_at)
                delays.append(round(engine._retry_at - now[0], 1))
                now[0] = engine._retry_at + 0.01
                engine._check_retry()
                self.assertEqual(len(engine.client.connect_calls), attempt + 1)
                engine.client.state = "idle"
                engine.client.error = "connection failed"
                engine.client.kicked = False
        self.assertEqual(delays, [3, 5, 10, 20, 30, 30])

    def test_kicked_stops_retries(self):
        engine = self.make_engine()
        engine.client.kicked = True
        engine.client.error = "you are banned from this server"
        engine._check_retry()
        self.assertFalse(engine._wanted_connected)
        self.assertIsNone(engine._retry_at)
        self.assertEqual(engine.client.connect_calls, [])
        events = engine.drain_events()
        self.assertTrue(any(event["type"] == "retry_stopped" for event in events))

    def test_invalid_hash_is_rejected_before_network(self):
        engine = self.make_engine()
        with self.assertRaises(ValueError):
            engine.connect("not-a-hash")
        self.assertEqual(engine.client.connect_calls, [])

    def test_connected_resets_backoff(self):
        engine = self.make_engine()
        engine._retry_index = 3
        engine.client.connected = True
        engine._check_retry()
        self.assertEqual(engine._retry_index, 0)
        self.assertIsNone(engine._retry_at)


if __name__ == "__main__":
    unittest.main()
