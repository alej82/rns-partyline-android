import os
import threading
import time

from partyline_android.paths import prepare_environment

prepare_environment()

from kivy.app import App
from kivy.clock import Clock
from kivy.core.text import Label as CoreLabel
from kivy.core.window import Window
from kivy.metrics import dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.behaviors.focus import FocusBehavior
from kivy.uix.checkbox import CheckBox
from kivy.uix.image import Image
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.progressbar import ProgressBar
from kivy.uix.screenmanager import NoTransition, Screen, ScreenManager
from kivy.uix.scrollview import ScrollView
from kivy.uix.slider import Slider
from kivy.uix.spinner import Spinner
from kivy.uix.textinput import TextInput
from kivy.utils import escape_markup

from partyline_android import background
from partyline_android.chatlog import LINE_LIMIT, ChatLog
from partyline_android.diagnostics import audio_sanity, codec_roundtrip, collect_versions
from partyline_android.engine import Engine
from partyline_android.i18n import available_languages, configure, current_language, resolve_language, t
from partyline_android.paths import is_android
from partyline_android.reticulum import SharedInstanceUnavailable
from partyline_android.servers import SavedServers
from partyline_android.settings import MobileSettings

SHOW_DIAGNOSTICS = False

_ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
_EMOJI_FONT = "Roboto"
_EMOJI_FONT_REGULAR = os.path.join(_ASSETS, "RobotoEmoji.ttf")
_EMOJI_FONT_BOLD = os.path.join(_ASSETS, "RobotoEmoji-Bold.ttf")
if os.path.exists(_EMOJI_FONT_REGULAR) and os.path.exists(_EMOJI_FONT_BOLD):
    try:
        CoreLabel.register("RobotoEmoji", _EMOJI_FONT_REGULAR, fn_bold=_EMOJI_FONT_BOLD)
        _EMOJI_FONT = "RobotoEmoji"
    except Exception:
        pass


def _state_label(state):
    key = {
        "idle": "session.state.idle",
        "connecting": "session.state.connecting",
        "waiting for server": "session.state.waiting_for_server",
        "connected": "session.state.connected",
        "closed": "session.state.closed",
        "starting": "session.state.starting",
    }.get(state)
    return t(key) if key else str(state)


def _set_keep_screen_on(enabled):
    if not is_android():
        return
    try:
        from android.runnable import run_on_ui_thread
        from jnius import autoclass
    except Exception as error:
        print(f"PARTYLINE_SCREEN keep_screen_on unavailable: {error}", flush=True)
        return
    try:
        activity = autoclass("org.kivy.android.PythonActivity").mActivity
        layout_params = autoclass("android.view.WindowManager$LayoutParams")

        @run_on_ui_thread
        def apply():
            window = activity.getWindow()
            if enabled:
                window.addFlags(layout_params.FLAG_KEEP_SCREEN_ON)
            else:
                window.clearFlags(layout_params.FLAG_KEEP_SCREEN_ON)

        apply()
    except Exception as error:
        print(f"PARTYLINE_SCREEN keep_screen_on failed: {error}", flush=True)


def _switch_screen(manager, name):
    """Size the target before switching so its first layout is not animated.

    Screens are only real children while current, so a never-shown Screen keeps
    its default (100, 100) size until ScreenManager lays it out. Without this
    the first entry grows from the bottom-left corner for a few frames.
    """
    target = manager.get_screen(name)
    if manager.current == name:
        return
    target.pos = manager.pos
    target.size = manager.size
    manager.current = name
    manager.transition.stop()


def _title(text):
    return Label(text=text, size_hint_y=None, height=dp(30), bold=True, color=(0.92, 0.95, 1, 1))


def _label(text="", **kwargs):
    kwargs.setdefault("color", (0.85, 0.88, 0.92, 1))
    return Label(text=text, **kwargs)


def _input(hint, password=False, input_type="null", font_name=None):
    kwargs = dict(
        hint_text=hint,
        multiline=False,
        password=password,
        input_type=input_type,
        size_hint_y=None,
        height=dp(44),
        background_color=(0.14, 0.16, 0.2, 1),
        foreground_color=(0.95, 0.96, 1, 1),
        cursor_color=(0.5, 0.8, 1, 1),
        padding=[dp(8), dp(10)],
    )
    if font_name:
        kwargs["font_name"] = font_name
    return TextInput(**kwargs)


class ConnectScreen(Screen):
    def __init__(self, app, **kwargs):
        super().__init__(**kwargs)
        self.app = app
        self._spinner_entries = []
        self._spinner_labels = []
        self._updating_spinner = False
        self._status_kind = None

        root = BoxLayout(orientation="vertical", padding=dp(16), spacing=dp(8))
        assets = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
        logo_path = os.path.join(assets, "logo-header.png")
        if not os.path.exists(logo_path):
            logo_path = os.path.join(assets, "logo.png")
        if os.path.exists(logo_path):
            root.add_widget(
                Image(
                    source=logo_path,
                    size_hint_y=None,
                    height=dp(72),
                    allow_stretch=True,
                    keep_ratio=True,
                )
            )
        root.add_widget(_title("PartyDroid"))
        root.add_widget(_label(t("connect.subtitle"), size_hint_y=None, height=dp(24)))

        form = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(8))
        form.bind(minimum_height=lambda *_: setattr(form, "height", form.minimum_height))
        root.add_widget(form)

        form.add_widget(_label(t("connect.saved.title"), size_hint_y=None, height=dp(24)))
        self.saved = Spinner(
            text=t("connect.saved.empty"),
            values=[],
            size_hint_y=None,
            height=dp(44),
            background_normal="",
            background_color=(0.16, 0.2, 0.27, 1),
        )
        self.saved.bind(text=self._server_selected)
        form.add_widget(self.saved)

        saved_actions = BoxLayout(size_hint_y=None, height=dp(52), spacing=dp(6))
        saved_actions.add_widget(self._button(t("connect.actions.save"), self.save_server, font_size=sp(17)))
        saved_actions.add_widget(
            self._button(t("connect.actions.delete"), self.delete_server, color=(0.5, 0.2, 0.25, 1), font_size=sp(17))
        )
        saved_actions.add_widget(
            self._button(t("connect.actions.new"), self.new_server, color=(0.22, 0.24, 0.3, 1), font_size=sp(17))
        )
        form.add_widget(saved_actions)

        form.add_widget(_label(t("connect.server.label"), size_hint_y=None, height=dp(24)))
        self.server = _input("00000000…")
        form.add_widget(self.server)
        form.add_widget(_label(t("connect.room.label"), size_hint_y=None, height=dp(24)))
        self.room = _input("Lobby")
        form.add_widget(self.room)
        form.add_widget(_label(t("connect.password.label"), size_hint_y=None, height=dp(24)))
        self.password = _input(t("connect.password.placeholder"), password=True)
        form.add_widget(self.password)
        form.add_widget(_label(t("connect.server_password.label"), size_hint_y=None, height=dp(24)))
        self.server_password = _input(t("connect.password.placeholder"), password=True)
        form.add_widget(self.server_password)

        root.add_widget(BoxLayout())
        self.status = _label("", size_hint_y=None, height=dp(44), halign="left", valign="middle")
        self.status.bind(size=lambda *_: setattr(self.status, "text_size", (self.status.width, None)))
        root.add_widget(self.status)

        buttons = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8))
        buttons.add_widget(self._button(t("connect.actions.connect"), self.connect))
        buttons.add_widget(self._button(t("connect.actions.settings"), lambda: self.app.show_settings("connect")))
        if SHOW_DIAGNOSTICS:
            buttons.add_widget(self._button(t("connect.actions.diagnostics"), self.show_diagnostics))
        root.add_widget(buttons)
        self.add_widget(root)

    def set_status(self, text, kind=None):
        self.status.text = text
        self._status_kind = kind

    def _button(self, text, callback, color=(0.18, 0.4, 0.62, 1), font_size=None):
        button = Button(text=text, background_normal="", background_color=color)
        if font_size is not None:
            button.font_size = font_size
        button.bind(on_release=lambda *_: callback())
        return button

    def refresh_servers(self, select=None):
        self._updating_spinner = True
        entries = self.app.servers.ordered()
        base_labels = [self.app.servers.label_for(entry) for entry in entries]
        labels = [
            f"{label} · {entry['hash'][:8]}" if base_labels.count(label) > 1 else label
            for label, entry in zip(base_labels, entries)
        ]
        self._spinner_entries = entries
        self._spinner_labels = labels
        self.saved.values = labels
        if select is not None and select in entries:
            self.saved.text = labels[entries.index(select)]
        elif self.saved.text not in labels:
            self.saved.text = labels[0] if labels else t("connect.saved.empty")
        self._updating_spinner = False

    def autofill_last(self):
        entry = self.app.servers.most_recent()
        self.refresh_servers(select=entry)
        if entry is not None:
            self._fill(entry)

    def _selected_entry(self):
        text = self.saved.text
        for index, label in enumerate(self._spinner_labels):
            if label == text:
                return self._spinner_entries[index]
        return None

    def _server_selected(self, _spinner, _text):
        if self._updating_spinner:
            return
        entry = self._selected_entry()
        if entry is not None:
            self._fill(entry)
            self.set_status("", None)

    def _fill(self, entry):
        self.server.text = entry["hash"]
        self.room.text = entry["room"]
        self.password.text = entry["password"]
        self.server_password.text = entry["server_password"]

    def save_server(self):
        text = self.server.text.strip().lower()
        error = self.app.hash_error(text)
        if error:
            self.set_status(error, "error")
            return
        entry = self.app.servers.upsert(
            text,
            room=self.room.text.strip(),
            password=self.password.text,
            server_password=self.server_password.text,
        )
        self.refresh_servers(select=entry)
        self.set_status(t("connect.status.saved"), "info")

    def delete_server(self):
        entry = self._selected_entry()
        if entry is None:
            self.set_status(t("connect.status.select_to_delete"), "error")
            return
        content = BoxLayout(orientation="vertical", spacing=dp(10), padding=dp(10))
        content.add_widget(
            _label(t("connect.delete.prompt", label=self.app.servers.label_for(entry)), halign="center")
        )
        actions = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(8))
        cancel = Button(text=t("common.cancel"), background_normal="", background_color=(0.22, 0.24, 0.3, 1))
        confirm = Button(text=t("common.delete"), background_normal="", background_color=(0.5, 0.2, 0.25, 1))
        actions.add_widget(cancel)
        actions.add_widget(confirm)
        content.add_widget(actions)
        popup = Popup(title=t("connect.delete.title"), content=content, size_hint=(0.9, 0.4))

        def remove():
            self.app.servers.remove(entry)
            popup.dismiss()
            self.refresh_servers()
            self.new_server()

        cancel.bind(on_release=lambda *_: popup.dismiss())
        confirm.bind(on_release=lambda *_: remove())
        popup.open()

    def new_server(self):
        self.server.text = ""
        self.room.text = ""
        self.password.text = ""
        self.server_password.text = ""
        self._updating_spinner = True
        self.saved.text = "" if self._spinner_entries else t("connect.saved.empty")
        self._updating_spinner = False
        self.set_status(t("connect.status.new"), "info")

    def connect(self):
        error = self.app.connect(
            self.server.text.strip(),
            self.room.text.strip() or None,
            self.password.text or None,
            self.server_password.text or None,
        )
        self.set_status(error, "error") if error else self.set_status(t("connect.status.connecting"), "transient")

    def show_diagnostics(self):
        content = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(8))
        text = _label(t("diagnostics.reading"), halign="left", valign="top")
        text.bind(width=lambda *_: setattr(text, "text_size", (text.width, None)))
        text.bind(texture_size=lambda *_: setattr(text, "height", text.texture_size[1]))
        scroll = ScrollView()
        scroll.add_widget(text)
        content.add_widget(scroll)
        popup = Popup(title=t("diagnostics.title"), content=content, size_hint=(0.95, 0.8))

        def refresh():
            threading.Thread(target=lambda: _fill_diagnostics(text), daemon=True).start()

        row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        refresh_button = Button(text=t("diagnostics.refresh"), background_normal="", background_color=(0.18, 0.4, 0.62, 1))
        refresh_button.bind(on_release=lambda *_: refresh())
        codec_button = Button(text=t("diagnostics.test_codecs"), background_normal="", background_color=(0.18, 0.4, 0.62, 1))
        codec_button.bind(on_release=lambda *_: _run_codecs(text))
        audio_button = Button(text=t("diagnostics.test_audio"), background_normal="", background_color=(0.18, 0.4, 0.62, 1))
        audio_button.bind(on_release=lambda *_: _run_audio(text, self.app))
        row.add_widget(refresh_button)
        row.add_widget(codec_button)
        row.add_widget(audio_button)
        content.add_widget(row)
        popup.open()
        refresh()


class SettingsScreen(Screen):
    def __init__(self, app, **kwargs):
        super().__init__(**kwargs)
        self.app = app
        self._return_to = "connect"
        self._inputs = []
        self._outputs = []
        self._input_values = {}
        self._output_values = {}
        self._language_code = "system"
        self._language_buttons = {}
        self._devices_requested = False

        root = BoxLayout(orientation="vertical", padding=dp(14), spacing=dp(8))
        root.add_widget(_title(t("settings.title")))
        root.add_widget(BoxLayout(size_hint_y=None, height=dp(12)))

        form = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(8))
        form.bind(minimum_height=lambda *_: setattr(form, "height", form.minimum_height))
        root.add_widget(form)

        form.add_widget(_label(t("settings.name.label"), size_hint_y=None, height=dp(24)))
        self.name_input = _input(t("settings.name.placeholder"))
        form.add_widget(self.name_input)
        self.name_note = _label("", size_hint_y=None, height=dp(34), halign="left", valign="middle")
        self.name_note.bind(size=lambda *_: setattr(self.name_note, "text_size", (self.name_note.width, None)))
        self.name_note.color = (1, 0.8, 0.4, 1)
        form.add_widget(self.name_note)

        form.add_widget(_label(t("settings.mic.label"), size_hint_y=None, height=dp(24)))
        self.input_spinner = Spinner(
            text=t("device.default"),
            values=[t("device.default")],
            size_hint_y=None,
            height=dp(44),
            background_normal="",
            background_color=(0.16, 0.2, 0.27, 1),
        )
        form.add_widget(self.input_spinner)

        form.add_widget(_label(t("settings.output.label"), size_hint_y=None, height=dp(24)))
        self.output_spinner = Spinner(
            text=t("device.default"),
            values=[t("device.default")],
            size_hint_y=None,
            height=dp(44),
            background_normal="",
            background_color=(0.16, 0.2, 0.27, 1),
        )
        form.add_widget(self.output_spinner)

        form.add_widget(_label(t("settings.gain.label"), size_hint_y=None, height=dp(24)))
        self.gain_value = _label(t("settings.gain.value", db=0), size_hint_y=None, height=dp(24), halign="left")
        self.gain = Slider(min=-24, max=24, value=0, step=1, size_hint_y=None, height=dp(40))
        self.gain.bind(value=self._gain_changed)
        form.add_widget(self.gain)
        form.add_widget(self.gain_value)

        agc_row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(6))
        self.agc = CheckBox(active=False, size_hint_x=None, width=dp(44))
        agc_row.add_widget(self.agc)
        agc_row.add_widget(_label(t("settings.agc.label"), halign="left", valign="middle"))
        form.add_widget(agc_row)

        form.add_widget(_label(t("settings.language.label"), size_hint_y=None, height=dp(24)))
        language_row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(6))
        for code, label in self._language_choices():
            button = Button(
                text=label,
                background_normal="",
                background_color=(0.18, 0.2, 0.26, 1),
                font_size=sp(15),
            )
            button.bind(on_release=lambda _button, value=code: self._select_language(value))
            self._language_buttons[code] = button
            language_row.add_widget(button)
        form.add_widget(language_row)

        root.add_widget(BoxLayout())
        buttons = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8))
        buttons.add_widget(self._action(t("settings.actions.save"), self.save))
        buttons.add_widget(
            self._action(t("settings.actions.cancel"), self.app.hide_settings, color=(0.22, 0.24, 0.3, 1))
        )
        root.add_widget(buttons)
        self.add_widget(root)

    def _action(self, text, callback, color=(0.18, 0.4, 0.62, 1)):
        button = Button(text=text, background_normal="", background_color=color)
        button.bind(on_release=lambda *_: callback())
        return button

    def _gain_changed(self, _slider, value):
        self.gain_value.text = t("settings.gain.value", db=int(round(value)))

    def show(self, return_to):
        self._return_to = return_to
        self.name_input.text = self.app.settings["name"]
        if self.app.in_session():
            self.name_note.text = t("settings.name.note_session")
        else:
            self.name_note.text = t("settings.name.note_connect")
        self.input_spinner.text = self.app.settings["input"] or t("device.default")
        self.output_spinner.text = self.app.settings["output"] or t("device.default")
        self._populate_devices()
        self._language_code = self.app.settings["language"]
        self._refresh_language_buttons()
        self.gain.value = float(self.app.settings["tx_gain_db"])
        self._gain_changed(None, self.gain.value)
        self.agc.active = bool(self.app.settings["mic_agc"])
        if not self._devices_requested:
            self._devices_requested = True
            threading.Thread(target=self._load_devices, daemon=True).start()

    def _load_devices(self):
        try:
            from partyline.audio import audio_devices

            inputs, outputs = audio_devices()
        except Exception as error:
            print(f"PARTYLINE_SETTINGS audio_devices failed: {error}", flush=True)
            inputs, outputs = [], []
        Clock.schedule_once(lambda *_: self._set_devices(inputs, outputs), 0)

    def _set_devices(self, inputs, outputs):
        self._inputs = list(inputs or [])
        self._outputs = list(outputs or [])
        self._populate_devices()

    def _populate_devices(self):
        self._fill_devices(self.input_spinner, self._inputs, self.app.settings["input"], self._input_values)
        self._fill_devices(self.output_spinner, self._outputs, self.app.settings["output"], self._output_values)

    def _fill_devices(self, spinner, devices, fallback, values_map):
        default_label = t("device.default")
        current = spinner.text or fallback or default_label
        values = [default_label]
        values_map.clear()
        values_map[default_label] = None
        for device in devices:
            if device and device not in values:
                values.append(device)
                values_map[device] = device
        if current not in values:
            values.append(current)
            values_map[current] = fallback or current
        spinner.values = values
        spinner.text = current

    def _language_choices(self):
        choices = [("system", t("settings.language.system"))]
        choices.extend((code, name) for code, name in available_languages().items())
        return choices

    def _select_language(self, code):
        self._language_code = code
        self._refresh_language_buttons()

    def _refresh_language_buttons(self):
        for code, button in self._language_buttons.items():
            active = code == self._language_code
            button.background_color = (0.2, 0.45, 0.3, 1) if active else (0.18, 0.2, 0.26, 1)

    def save(self):
        self.app.save_settings(
            name=self.name_input.text.strip(),
            language=self._language_code,
            input=self._input_values.get(self.input_spinner.text),
            output=self._output_values.get(self.output_spinner.text),
            tx_gain_db=float(self.gain.value),
            mic_agc=bool(self.agc.active),
        )
        self.app.hide_settings()


class ChatSendButton(Button):
    """Keeps the message input focused when the send button is tapped."""

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            FocusBehavior.ignored_touch.append(touch)
        return super().on_touch_down(touch)


class SessionScreen(Screen):
    def __init__(self, app, **kwargs):
        super().__init__(**kwargs)
        self.app = app
        self._room_signature = None
        self._user_signature = None
        self._speaker_signature = None
        self._tab_buttons = {}

        root = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(6))
        top = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(6))
        self.title = _label("PartyDroid", bold=True)
        top.add_widget(self.title)
        self.speaker_box, self.speaker_name = self._build_speaker()
        top.add_widget(self.speaker_box)
        self.settings_button = Button(
            text=t("session.actions.settings"),
            size_hint_x=None,
            width=dp(72),
            background_normal="",
            background_color=(0.22, 0.24, 0.3, 1),
        )
        self.settings_button.bind(on_release=lambda *_: self.app.show_settings("session"))
        top.add_widget(self.settings_button)
        if SHOW_DIAGNOSTICS:
            self.diag = Button(
                text=t("session.actions.diagnostics"),
                size_hint_x=None,
                width=dp(52),
                background_normal="",
                background_color=(0.18, 0.4, 0.62, 1),
            )
            self.diag.bind(on_release=lambda *_: self.app.connect_screen.show_diagnostics())
            top.add_widget(self.diag)
        self.leave = Button(
            text=t("session.actions.leave"),
            size_hint_x=None,
            width=dp(60),
            background_normal="",
            background_color=(0.5, 0.2, 0.25, 1),
        )
        self.leave.bind(on_release=lambda *_: self.app.leave_session())
        top.add_widget(self.leave)
        root.add_widget(top)

        self.banner = _label("", size_hint_y=None, height=dp(38), halign="left", valign="middle")
        self.banner.bind(size=lambda *_: setattr(self.banner, "text_size", (self.banner.width, None)))
        root.add_widget(self.banner)

        tab_bar = BoxLayout(size_hint_y=None, height=dp(34), spacing=dp(6))
        for tab_name, title in (
            ("chat", t("session.tabs.chat")),
            ("rooms", t("session.tabs.rooms")),
            ("members", t("session.tabs.members")),
        ):
            button = Button(text=title, background_normal="", background_color=(0.18, 0.2, 0.26, 1))
            button.bind(on_release=lambda _button, target=tab_name: self.show_tab(target))
            self._tab_buttons[tab_name] = button
            tab_bar.add_widget(button)
        root.add_widget(tab_bar)

        self.tabs = ScreenManager(size_hint_y=1, transition=NoTransition())
        chat_screen = Screen(name="chat")
        chat_root = BoxLayout(orientation="vertical", spacing=dp(4))
        self.chat_scroll = ScrollView(do_scroll_x=False, do_scroll_y=False)
        self.chat_box = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(2))
        self.chat_box.bind(minimum_height=lambda *_: setattr(self.chat_box, "height", self.chat_box.minimum_height))
        self.chat_box.bind(height=lambda *_: setattr(self.chat_scroll, "scroll_y", 0))
        self.chat_scroll.add_widget(self.chat_box)
        chat_root.add_widget(self.chat_scroll)
        self.chat_hint = _label(
            t("session.chat.hint.connect_and_join"),
            size_hint_y=None,
            height=dp(20),
            halign="left",
            valign="middle",
            color=(1, 0.8, 0.4, 1),
        )
        self.chat_hint.bind(size=lambda *_: setattr(self.chat_hint, "text_size", (self.chat_hint.width, None)))
        chat_root.add_widget(self.chat_hint)
        input_row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(6))
        self.chat_input = _input(
            t("session.chat.input_placeholder"),
            input_type="text",
            font_name=_EMOJI_FONT,
        )
        self.chat_input.bind(on_text_validate=lambda *_: self.send_message())
        self.send_button = ChatSendButton(
            text=t("session.chat.send"),
            size_hint_x=None,
            width=dp(72),
            background_normal="",
            background_color=(0.18, 0.4, 0.62, 1),
        )
        self.send_button.bind(on_press=lambda *_: self.send_message())
        input_row.add_widget(self.chat_input)
        input_row.add_widget(self.send_button)
        chat_root.add_widget(input_row)
        chat_screen.add_widget(chat_root)
        self.tabs.add_widget(chat_screen)

        rooms_screen = Screen(name="rooms")
        self.rooms_scroll = ScrollView()
        self.rooms_box = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(4))
        self.rooms_box.bind(minimum_height=lambda *_: setattr(self.rooms_box, "height", self.rooms_box.minimum_height))
        self.rooms_scroll.add_widget(self.rooms_box)
        rooms_screen.add_widget(self.rooms_scroll)
        self.tabs.add_widget(rooms_screen)

        members_screen = Screen(name="members")
        self.users_scroll = ScrollView()
        self.users = _label("", halign="left", valign="top", markup=True, size_hint_y=None)
        self.users.bind(width=lambda *_: setattr(self.users, "text_size", (self.users.width, None)))
        self.users.bind(texture_size=lambda *_: setattr(self.users, "height", self.users.texture_size[1]))
        self.users_scroll.add_widget(self.users)
        members_screen.add_widget(self.users_scroll)
        self.tabs.add_widget(members_screen)

        root.add_widget(self.tabs)
        self.show_tab("chat")

        tx_row = BoxLayout(size_hint_y=None, height=dp(28), spacing=dp(8))
        self.tx_state = _label(t("session.tx.unavailable"), size_hint_y=None, height=dp(22), bold=True)
        tx_row.add_widget(self.tx_state)
        self.keep_screen = None
        if is_android():
            self.keep_screen = Button(
                text=t("session.keep_screen.on"),
                size_hint=(None, None),
                width=dp(118),
                height=dp(26),
                font_size=sp(13),
                background_normal="",
                background_color=(0.22, 0.24, 0.3, 1),
            )
            self.keep_screen.bind(on_release=lambda *_: self.app.toggle_keep_screen_on())
            tx_row.add_widget(self.keep_screen)
        root.add_widget(tx_row)
        self.level = ProgressBar(max=1, value=0, size_hint_y=None, height=dp(10))
        root.add_widget(self.level)
        self._level_value = 0.0

        controls = BoxLayout(size_hint_y=None, height=dp(50), spacing=dp(8))
        self.mute = self._toggle(t("session.mute.off"), self.app.toggle_mute)
        self.deaf = self._toggle(t("session.deaf.off"), self.app.toggle_deaf)
        self.ptt = Button(
            text=t("session.ptt.talk"),
            background_normal="",
            background_color=(0.3, 0.3, 0.3, 1),
            halign="center",
        )
        self.ptt.bind(on_press=lambda *_: self.app.ptt_pressed())
        self.ptt.bind(on_release=lambda *_: self.app.ptt_released())
        controls.add_widget(self.mute)
        controls.add_widget(self.deaf)
        controls.add_widget(self.ptt)
        root.add_widget(controls)
        self.keyboard_spacer = BoxLayout(size_hint_y=None, height=0)
        root.add_widget(self.keyboard_spacer)
        self.add_widget(root)

    def set_keyboard_height(self, height):
        self.keyboard_spacer.height = max(0.0, float(height or 0))

    def _toggle(self, text, callback):
        button = Button(text=text, background_normal="", background_color=(0.22, 0.24, 0.3, 1))
        button.bind(on_release=lambda *_: callback())
        return button

    def _build_speaker(self):
        box = BoxLayout(size_hint_x=None, width=0, spacing=dp(2), opacity=0)
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "mic.png")
        if os.path.exists(path):
            self.mic_image = Image(
                source=path,
                size_hint_x=None,
                width=dp(18),
                size_hint_y=None,
                height=dp(18),
            )
            box.add_widget(self.mic_image)
            Clock.schedule_once(lambda *_: self._check_mic_image(box), 0.5)
        else:
            self.mic_image = None
            box.add_widget(_label("MIC", size_hint_x=None, width=dp(24), font_size=sp(11), bold=True))
        name = Label(text="", shorten=True, shorten_from="right", size_hint_x=1)
        box.add_widget(name)
        return box, name

    def _check_mic_image(self, box):
        if self.mic_image is None or self.mic_image.texture is not None:
            return
        box.remove_widget(self.mic_image)
        box.add_widget(
            _label("MIC", size_hint_x=None, width=dp(24), font_size=sp(11), bold=True),
            index=0,
        )
        self.mic_image = None

    def show_tab(self, name):
        if name not in self._tab_buttons:
            return
        for key, button in self._tab_buttons.items():
            button.background_color = (0.2, 0.45, 0.3, 1) if key == name else (0.18, 0.2, 0.26, 1)
        _switch_screen(self.tabs, name)
        if name == "chat":
            self.scroll_to_bottom()

    def send_message(self):
        text = self.chat_input.text
        if not text.strip():
            return
        if not self.app.send_chat(text):
            return
        self.chat_input.text = ""
        Clock.schedule_once(lambda *_: self._focus_input(), 0)

    def _focus_input(self):
        if self.app.in_session() and self.tabs.current == "chat" and not self.chat_input.disabled:
            self.chat_input.focus = True

    def clear_chat(self):
        self.chat_box.clear_widgets()
        self.scroll_to_bottom()

    def scroll_to_bottom(self):
        self.chat_scroll.scroll_y = 0
        Clock.schedule_once(lambda *_: setattr(self.chat_scroll, "scroll_y", 0), 0)

    def append_chat_line(self, line):
        self.chat_box.add_widget(self._chat_label(line))
        while len(self.chat_box.children) > LINE_LIMIT:
            self.chat_box.remove_widget(self.chat_box.children[-1])
        self.scroll_to_bottom()

    def _chat_label(self, line):
        stamp = time.strftime("%H:%M:%S", time.localtime(line.get("ts") or time.time()))
        text = escape_markup(str(line.get("text") or ""))
        kind = line.get("kind")
        if kind == "chat":
            who = escape_markup(str(line.get("who") or t("chat.user.unknown")))
            if line.get("own"):
                markup = f"[color=#7f8899][{stamp}][/color] [color=#8fc4ff][b]{who}[/b][/color]: {text}"
            else:
                markup = f"[color=#7f8899][{stamp}][/color] [color=#e4e9f2]{who}[/color]: {text}"
        elif kind == "warning":
            markup = f"[color=#7f8899][{stamp}][/color] [color=#ffc766]{text}[/color]"
        elif kind == "error":
            markup = f"[color=#7f8899][{stamp}][/color] [color=#ff7777]{text}[/color]"
        else:
            markup = f"[color=#8b94a7][{stamp}] {text}[/color]"
        label = Label(
            text=markup,
            markup=True,
            font_name=_EMOJI_FONT,
            size_hint_y=None,
            halign="left",
            valign="middle",
        )
        label.bind(width=lambda *_: setattr(label, "text_size", (label.width, None)))
        label.bind(texture_size=lambda *_: setattr(label, "height", label.texture_size[1] + dp(2)))
        return label

    def _update_speaker(self, snapshot):
        names = [user["name"] for user in snapshot["users"] if user.get("speaking")]
        signature = tuple(names)
        if signature == self._speaker_signature:
            return
        self._speaker_signature = signature
        if names:
            text = names[0] + (f" +{len(names) - 1}" if len(names) > 1 else "")
            self.speaker_name.text = text
            self.speaker_box.width = dp(110)
            self.speaker_box.opacity = 1
        else:
            self.speaker_name.text = ""
            self.speaker_box.width = 0
            self.speaker_box.opacity = 0

    def render(self, snapshot):
        connection = snapshot["connection"]
        server = snapshot["server"]
        me = snapshot["me"]
        audio = snapshot.get("audio") or {}
        mic_allowed = bool(audio.get("mic_allowed", True))

        state = connection["state"]
        if connection["kicked"]:
            state_text = t("session.state.rejected")
        else:
            state_text = _state_label(state)
        self.title.text = f"{server['name'] or 'PartyDroid'} · {state_text}"
        if connection["retry_in"] is not None:
            self.banner.text = t(
                "session.banner.retry",
                seconds=connection["retry_in"],
                attempt=connection["retry_attempt"],
            )
            self.banner.color = (1, 0.8, 0.35, 1)
        elif connection["error"]:
            self.banner.text = connection["error"]
            self.banner.color = (1, 0.45, 0.45, 1)
        elif connection["connected"]:
            audio_error = audio.get("error")
            if (audio_error or not mic_allowed) and not audio.get("tx_ready"):
                reason = t("session.reason.mic_not_allowed") if not mic_allowed else audio_error
                self.banner.text = t("session.banner.listen_only", reason=reason)
                self.banner.color = (1, 0.75, 0.35, 1)
            elif getattr(self.app, "_background_error", None) and not getattr(
                self.app, "_background_active", False
            ):
                self.banner.text = t(
                    "session.banner.background_unavailable",
                    error=self.app._background_error,
                )
                self.banner.color = (1, 0.75, 0.35, 1)
            else:
                key = "session.banner.connected" if connection["synced"] else "session.banner.connected_syncing"
                self.banner.text = t(key)
                self.banner.color = (0.6, 0.9, 0.65, 1)
        elif connection["retry_attempt"] > 0:
            self.banner.text = t("session.banner.reconnecting", attempt=connection["retry_attempt"])
            self.banner.color = (1, 0.8, 0.35, 1)
        else:
            self.banner.text = t("session.banner.connecting")
            self.banner.color = (0.8, 0.85, 0.9, 1)

        muted = bool(audio.get("muted", me["muted"] if me else False))
        deaf = bool(audio.get("deaf", me["deaf"] if me else False))
        self.mute.text = t("session.mute.on") if muted else t("session.mute.off")
        self.mute.background_color = (0.55, 0.25, 0.3, 1) if muted else (0.22, 0.24, 0.3, 1)
        self.deaf.text = t("session.deaf.on") if deaf else t("session.deaf.off")
        self.deaf.background_color = (0.55, 0.25, 0.3, 1) if deaf else (0.22, 0.24, 0.3, 1)

        tx_ready = bool(audio.get("tx_ready"))
        can_speak = bool(audio.get("can_speak", True))
        transmitting = bool(audio.get("transmit"))
        if (audio.get("error") or not mic_allowed) and not tx_ready:
            tx_text, tx_color = t("session.tx.listen_only"), (1, 0.75, 0.35, 1)
        elif transmitting:
            tx_text, tx_color = t("session.tx.active"), (0.6, 1, 0.7, 1)
        elif muted:
            tx_text, tx_color = t("session.tx.blocked_muted"), (1, 0.8, 0.4, 1)
        elif not can_speak:
            tx_text, tx_color = t("session.tx.blocked_permission"), (1, 0.6, 0.4, 1)
        elif not tx_ready:
            tx_text, tx_color = t("session.tx.unavailable"), (0.8, 0.8, 0.85, 1)
        else:
            tx_text, tx_color = t("session.tx.ready"), (0.6, 0.9, 0.7, 1)
        self.tx_state.text = tx_text
        self.tx_state.color = tx_color
        if self.keep_screen is not None:
            keep_on = bool(self.app.settings["keep_screen_on"])
            self.keep_screen.text = t("session.keep_screen.on") if keep_on else t("session.keep_screen.off")
            self.keep_screen.background_color = (0.2, 0.5, 0.35, 1) if keep_on else (0.22, 0.24, 0.3, 1)
        self.ptt.disabled = not (tx_ready and can_speak and not muted and mic_allowed)
        self.ptt.text = t("session.ptt.talk") if not self.ptt.disabled else t("session.ptt.unavailable")
        self.ptt.background_color = (0.2, 0.65, 0.35, 1) if transmitting else (0.3, 0.3, 0.3, 1)
        target = 0.0
        if transmitting:
            target = min(1.0, max(0.0, (float(audio.get("level_db", -120.0)) + 60.0) / 60.0))
        self._level_value = target if target >= self._level_value else self._level_value * 0.75
        self.level.value = self._level_value

        own_room = me["room"] if me else None
        room_signature = tuple(
            (room["id"], room["name"], room["locked"], own_room == room["id"]) for room in snapshot["rooms"]
        )
        if room_signature != self._room_signature:
            self._room_signature = room_signature
            self.rooms_box.clear_widgets()
            for room in snapshot["rooms"]:
                key = "session.rooms.button_locked" if room["locked"] else "session.rooms.button"
                button = Button(
                    text=t(
                        key,
                        name=room["name"],
                        profile=room["profile"],
                        frame_ms=room["frame_ms"],
                    ),
                    size_hint_y=None,
                    height=dp(36),
                    background_normal="",
                    background_color=(0.2, 0.45, 0.3, 1)
                    if me and me["room"] == room["id"]
                    else (0.18, 0.2, 0.26, 1),
                )
                button.bind(on_release=lambda _button, room_id=room["id"]: self.app.move_room(room_id))
                self.rooms_box.add_widget(button)

        user_signature = tuple(
            (
                user["sid"],
                user["name"],
                user["room"],
                user["muted"],
                user["deaf"],
                user["operator"],
                user["server_muted"],
                user["text_only"],
                user["speaking"],
                user["local_muted"],
            )
            for user in snapshot["users"]
        )
        if user_signature != self._user_signature:
            self._user_signature = user_signature
            lines = []
            for user in snapshot["users"]:
                marker = ">" if user["speaking"] else " "
                names = []
                if user["muted"]:
                    names.append(t("session.members.status.muted"))
                if user["deaf"]:
                    names.append(t("session.members.status.deaf"))
                if user["server_muted"]:
                    names.append(t("session.members.status.server_muted"))
                if user["operator"]:
                    names.append(t("session.members.status.operator"))
                if user["text_only"]:
                    names.append(t("session.members.status.text_only"))
                if user["local_muted"]:
                    names.append(t("session.members.status.local_muted"))
                detail = t("session.members.detail", names="/".join(names)) if names else ""
                name = user["name"]
                if me and user["sid"] == me["sid"]:
                    name = f"[b]{name}[/b]"
                lines.append(
                    t(
                        "session.members.line",
                        marker=marker,
                        name=name,
                        room=user["room"],
                        detail=detail,
                    )
                )
            self.users.text = "\n".join(lines) or t("session.members.empty")

        self._update_speaker(snapshot)
        can_chat = bool(connection["connected"] and me and me.get("room") is not None)
        self.chat_input.disabled = not can_chat
        self.send_button.disabled = not can_chat
        if can_chat:
            self.chat_hint.text = ""
            self.chat_hint.height = 0
        else:
            self.chat_hint.text = (
                t("session.chat.hint.join")
                if connection["connected"]
                else t("session.chat.hint.connect_and_join")
            )
            self.chat_hint.height = dp(20)


class PartyDroidApp(App):
    title = "PartyDroid"

    def build(self):
        Window.clearcolor = (0.07, 0.08, 0.1, 1)
        Window.softinput_mode = "resize"
        self.settings = MobileSettings()
        configure(self.settings["language"])
        self.servers = SavedServers()
        self._chat = ChatLog()
        self._language_restart_scheduled = False
        self.engine = None
        self._engine_error = None
        self._connect_request = None
        self._ptt_active = False
        self._session_saved = False
        self._settings_return = "connect"
        self._screen_on_held = False
        self._paused = False
        self._background_active = False
        self._background_error = None
        self._notification_text = None
        self._notifications_requested = False
        Window.bind(on_touch_up=self._on_window_touch_up)
        Window.bind(on_keyboard=self._on_keyboard)
        self.screens = ScreenManager(transition=NoTransition())
        self.connect_screen = ConnectScreen(self, name="connect")
        self.session_screen = SessionScreen(self, name="session")
        self.settings_screen = SettingsScreen(self, name="settings")
        self.screens.add_widget(self.connect_screen)
        self.screens.add_widget(self.session_screen)
        self.screens.add_widget(self.settings_screen)
        self.connect_screen.autofill_last()
        return self.screens

    def on_start(self):
        Clock.schedule_interval(self._tick, 0.1)
        Clock.schedule_once(lambda *_: self._prestart(), 0.05)
        Clock.schedule_once(lambda *_: self.request_microphone(silent=True), 0.8)
        Clock.schedule_once(lambda *_: self.request_notifications(silent=True), 0.9)
        Clock.schedule_once(lambda *_: threading.Thread(target=_log_diagnostics, daemon=True).start(), 1.5)
        if is_android():
            Clock.schedule_interval(self._poll_keyboard, 0.25)

    def _on_keyboard(self, _window, key, _scancode=None, _codepoint=None, _modifier=None):
        if key != 27:
            return False
        if self.screens.current == "session":
            self.leave_session()
        elif self.screens.current == "settings":
            self.hide_settings()
        else:
            self.stop()
        return True

    def _poll_keyboard(self, _dt):
        try:
            from jnius import autoclass

            activity = autoclass("org.kivy.android.PythonActivity").mActivity
            insets = activity.getWindow().getDecorView().getRootWindowInsets()
            height = 0
            if insets is not None:
                ime = autoclass("android.view.WindowInsets$Type").ime()
                height = int(insets.getInsets(ime).bottom)
        except Exception:
            return
        self.session_screen.set_keyboard_height(height)

    def on_stop(self):
        self._release_ptt()
        self._sync_keep_screen_on(False)
        self._stop_background_session()
        if self.engine is not None:
            self.engine.stop()

    def on_pause(self):
        self._paused = True
        self._release_ptt()
        self._sync_keep_screen_on(False)
        if self.engine is not None and not self._background_active:
            self.engine.pause_audio()
        elif self.engine is not None:
            self._sync_background_notification(self.engine.snapshot())
        return True

    def on_resume(self):
        self._paused = False
        self._sync_keep_screen_on()
        self.request_notifications(silent=True)
        if self.engine is not None:
            threading.Thread(target=self._resume_engine, daemon=True).start()

    def _resume_engine(self):
        engine = self.engine
        if engine is None:
            return
        allowed = self._mic_permission()
        engine.set_microphone_allowed(allowed)
        if not allowed:
            self._stop_background_session()
        elif not self._background_active and engine.snapshot()["connection"]["wanted"]:
            self._start_background_session(
                "PartyDroid",
                self._notification_text or t("session.notification.reconnecting"),
            )
        engine.resume_audio()
        self._sync_background_notification(engine.snapshot())

    def _start_background_session(self, title, text):
        if not is_android():
            self._background_active = False
            return False
        if not self._mic_permission():
            self._background_active = False
            self._background_error = t("session.background.mic_not_allowed")
            print(f"PARTYLINE_BACKGROUND fallback: {self._background_error}", flush=True)
            return False
        self._background_active = background.start(title, text)
        if self._background_active:
            self._background_error = None
            self._notification_text = text
        else:
            self._background_error = background.last_error() or t("session.background.service_unavailable")
            print(f"PARTYLINE_BACKGROUND fallback: {self._background_error}", flush=True)
        return self._background_active

    def _stop_background_session(self):
        background.stop()
        self._background_active = False
        self._background_error = None
        self._notification_text = None

    def _set_background_text(self, text):
        if not self._background_active or text == self._notification_text:
            return
        self._notification_text = text
        if background.update("PartyDroid", text):
            self._background_error = None
            return
        self._background_error = background.last_error() or t("session.background.service_unavailable")
        print(f"PARTYLINE_BACKGROUND restart after update failure: {self._background_error}", flush=True)
        self._background_active = background.start("PartyDroid", text)

    def _sync_background_notification(self, snapshot):
        if not self._background_active:
            return
        connection = snapshot.get("connection") or {}
        if not connection.get("connected") and not connection.get("wanted"):
            self._stop_background_session()
            return
        me = snapshot.get("me") or {}
        room_name = None
        if me.get("room") is not None:
            for candidate in snapshot.get("rooms", []):
                if candidate.get("id") == me.get("room"):
                    room_name = candidate.get("name")
                    break
        if room_name:
            text = t("session.notification.room", room=room_name)
        elif me.get("room") is not None:
            text = t("session.notification.room_fallback", room=me["room"])
        elif connection.get("connected"):
            text = t("session.notification.connected")
        elif connection.get("wanted"):
            text = (
                t("session.notification.reconnecting")
                if connection.get("retry_attempt")
                else t("session.notification.connecting")
            )
        else:
            text = t("session.notification.active")
        self._set_background_text(text)

    def in_session(self):
        return self.screens.current == "session"

    def _tick(self, _dt):
        if self.engine is None:
            return
        snapshot = self.engine.snapshot()
        me = snapshot.get("me") or {}
        me_sid = me.get("sid")
        for event in self.engine.drain_events():
            for line in self._chat.ingest(event, me_sid, snapshot.get("identity")):
                self.session_screen.append_chat_line(line)
        connection = snapshot["connection"]
        self._sync_background_notification(snapshot)
        if connection["connected"] and not self._session_saved:
            self._session_saved = True
            self._remember_connected_server(snapshot)
        if self.screens.current == "session":
            self.session_screen.render(snapshot)
            return
        if self.screens.current == "settings":
            return
        if connection["connected"]:
            self._enter_session(snapshot)
        elif connection["retry_in"] is not None:
            self.connect_screen.set_status(
                t(
                    "connect.status.retry",
                    seconds=connection["retry_in"],
                    attempt=connection["retry_attempt"],
                ),
                "transient",
            )
        elif connection["error"] and connection["state"] in ("idle", "closed"):
            self.connect_screen.set_status(connection["error"], "error")
        elif connection["retry_attempt"] > 0:
            self.connect_screen.set_status(
                t("connect.status.reconnecting", attempt=connection["retry_attempt"]),
                "transient",
            )
        elif (
            not connection["wanted"]
            and connection["state"] in ("idle", "closed")
            and self.connect_screen._status_kind == "transient"
        ):
            self.connect_screen.set_status(t("connect.status.disconnected"), "idle")

    def _enter_session(self, snapshot):
        _switch_screen(self.screens, "session")
        self.session_screen.show_tab("chat")
        self.session_screen.scroll_to_bottom()
        self.session_screen.render(snapshot)
        self._sync_keep_screen_on(True)
        self._sync_background_notification(snapshot)

    def _prestart(self):
        if self.engine is not None:
            return
        try:
            engine = Engine(
                display_name=self.settings["name"] or None,
                client_options=self.settings.audio_options(),
            )
            engine.start()
        except SharedInstanceUnavailable as error:
            self._engine_error = str(error)
            self.connect_screen.set_status(self._engine_error, "error")
        except Exception as error:
            self._engine_error = f"{type(error).__name__}: {error}"
            self.connect_screen.set_status(self._engine_error, "error")
        else:
            self._engine_error = None
            self.engine = engine
            engine.set_microphone_allowed(self._mic_permission())
            self.connect_screen.set_status(
                t("connect.status.identity", hash=engine.identity_hash),
                "info",
            )

    def _start_engine(self, callback):
        if self.engine is not None:
            callback()
            return
        self._prestart()
        if self.engine is None:
            self.connect_screen.set_status(
                self._engine_error or t("connect.status.no_engine"),
                "error",
            )
            return
        callback()

    def hash_error(self, text):
        value = (text or "").strip().lower()
        if len(value) != 32 or any(character not in "0123456789abcdef" for character in value):
            return t("connect.status.hash_error")
        return None

    def connect(self, hash_text, room, password, server_password):
        text = (hash_text or "").strip().lower()
        error = self.hash_error(text)
        if error:
            return error
        self._connect_request = (text, room, password, server_password)
        self._session_saved = False
        self._clear_chat()
        self.connect_screen.set_status(t("connect.status.starting_engine"), "transient")
        self._start_engine(lambda: self._do_connect())
        return None

    def _do_connect(self):
        engine = self.engine
        if self._connect_request is None or engine is None:
            return
        text, room, password, server_password = self._connect_request
        self.request_notifications(silent=True)
        self._start_background_session("PartyDroid", t("session.notification.connecting"))
        try:
            engine.connect(text, room=room, password=password, server_password=server_password)
        except Exception as error:
            self._stop_background_session()
            self.connect_screen.set_status(f"{type(error).__name__}: {error}", "error")
            return
        self.connect_screen.set_status(
            t("connect.status.connecting_identity", hash=engine.identity_hash),
            "transient",
        )

    def leave_session(self):
        self._release_ptt()
        self._sync_keep_screen_on(False)
        self._stop_background_session()
        if self.engine is not None:
            self.engine.disconnect()
        self._connect_request = None
        self._session_saved = False
        self._clear_chat()
        self.connect_screen.set_status(t("connect.status.disconnected"), "idle")
        _switch_screen(self.screens, "connect")

    def _clear_chat(self):
        self._chat.clear()
        self.session_screen.clear_chat()

    def send_chat(self, text):
        if self.engine is None:
            return False
        return self.engine.send_text(text)

    def _remember_connected_server(self, snapshot):
        request = self._connect_request
        if not request:
            return
        hash_text, room, password, server_password = request
        me = snapshot.get("me") or {}
        room_name = None
        if me.get("room") is not None:
            for candidate in snapshot.get("rooms", []):
                if candidate["id"] == me["room"]:
                    room_name = candidate["name"]
                    break
        entry = self.servers.upsert(
            hash_text,
            room=room_name or room or "",
            password=password or "",
            server_password=server_password or "",
            name=(snapshot.get("server") or {}).get("name"),
        )
        self.connect_screen.refresh_servers(select=entry)

    def show_settings(self, return_to):
        self._settings_return = return_to or "connect"
        self.settings_screen.show(self._settings_return)
        _switch_screen(self.screens, "settings")

    def hide_settings(self):
        target = self._settings_return or "connect"
        _switch_screen(self.screens, target)
        if target == "session" and self.engine is not None:
            self.session_screen.render(self.engine.snapshot())

    def save_settings(self, **fields):
        previous_language = self.settings["language"]
        self.settings.apply(**fields)
        self.settings.save()
        self.connect_screen.refresh_servers()
        language_changed = (
            "language" in fields
            and fields["language"] != previous_language
            and resolve_language(fields["language"]) != current_language()
        )
        if self.engine is not None:
            self.engine.set_display_name(self.settings["name"])
            options = self.settings.audio_options()
            threading.Thread(
                target=self.engine.apply_audio_settings, kwargs=options, daemon=True
            ).start()
        if language_changed:
            self._language_restart_scheduled = False
            Clock.schedule_once(lambda *_: self._apply_language_change(), 0.2)
            return
        if self.in_session():
            self.session_screen.banner.text = t("settings.saved")
            self.session_screen.banner.color = (0.6, 0.9, 0.65, 1)

    def _apply_language_change(self):
        if self._language_restart_scheduled:
            return
        self._language_restart_scheduled = True
        fallback_message = t("settings.language.restart_manual")
        try:
            configure(self.settings["language"])
            if self.in_session():
                self.leave_session()
            self._session_saved = False
            self._rebuild_ui()
            print(f"PARTYLINE_I18N language applied language={current_language()}", flush=True)
        except Exception as error:
            print(f"PARTYLINE_I18N language apply failed: {error}", flush=True)
            self._show_restart_message(fallback_message)

    def _rebuild_ui(self):
        self.screens.clear_widgets()
        self.connect_screen = ConnectScreen(self, name="connect")
        self.session_screen = SessionScreen(self, name="session")
        self.settings_screen = SettingsScreen(self, name="settings")
        self.screens.add_widget(self.connect_screen)
        self.screens.add_widget(self.session_screen)
        self.screens.add_widget(self.settings_screen)
        self.connect_screen.autofill_last()
        if self.engine is not None and self.engine.identity_hash:
            self.connect_screen.set_status(
                t("connect.status.identity", hash=self.engine.identity_hash),
                "info",
            )
        _switch_screen(self.screens, "connect")

    def _show_restart_message(self, message=None):
        text = message or t("settings.language.restart_manual")
        if self.screens.current == "session":
            self.session_screen.banner.text = text
            self.session_screen.banner.color = (1, 0.75, 0.35, 1)
        else:
            self.connect_screen.set_status(text, "info")

    def toggle_keep_screen_on(self):
        self.settings["keep_screen_on"] = not bool(self.settings["keep_screen_on"])
        self.settings.save()
        self._sync_keep_screen_on()

    def _sync_keep_screen_on(self, active=None):
        if active is None:
            active = self.in_session()
        hold = bool(active and self.settings["keep_screen_on"] and not self._paused)
        if hold != self._screen_on_held:
            self._screen_on_held = hold
            _set_keep_screen_on(hold)

    def move_room(self, room_id):
        if self.engine is not None:
            self.engine.move(room_id)
            self.session_screen.banner.text = t("session.banner.entering_room", room=room_id)

    def toggle_mute(self):
        if self.engine is None:
            return
        self._release_ptt()
        audio = self.engine.snapshot().get("audio") or {}
        self.engine.set_muted(not bool(audio.get("muted")))

    def toggle_deaf(self):
        if self.engine is None:
            return
        self._release_ptt()
        audio = self.engine.snapshot().get("audio") or {}
        self.engine.set_deaf(not bool(audio.get("deaf")))

    def ptt_pressed(self):
        engine = self.engine
        if engine is None:
            return
        audio = engine.snapshot().get("audio") or {}
        reason = None
        if not audio.get("mic_allowed", True):
            reason = t("session.reason.mic_permission")
        elif not audio.get("tx_ready"):
            reason = audio.get("error") or t("session.reason.audio_unavailable")
        elif audio.get("muted"):
            reason = t("session.reason.muted")
        elif not audio.get("can_speak", True):
            reason = t("session.reason.cannot_speak")
        if reason:
            self.session_screen.banner.text = reason
            self.session_screen.banner.color = (1, 0.75, 0.35, 1)
            self._ptt_active = False
            return
        if engine.set_transmit(True):
            self._ptt_active = True
            self.session_screen.ptt.background_color = (0.2, 0.65, 0.35, 1)
        else:
            self.session_screen.banner.text = t("session.reason.transmit_failed")
            self.session_screen.banner.color = (1, 0.75, 0.35, 1)

    def ptt_released(self):
        self._release_ptt()

    def _release_ptt(self):
        if not self._ptt_active:
            return
        self._ptt_active = False
        if self.engine is not None:
            self.engine.set_transmit(False)
        self.session_screen.ptt.background_color = (0.3, 0.3, 0.3, 1)

    def _on_window_touch_up(self, _window, _touch):
        self._release_ptt()

    def request_microphone(self, silent=False):
        if not is_android():
            if not silent:
                self.connect_screen.set_status(t("permissions.mic_android_only"), "info")
            return
        try:
            from android.permissions import Permission, request_permissions
        except Exception as error:
            self.connect_screen.set_status(
                t("permissions.request_failed", error=f"{type(error).__name__}: {error}"),
                "error",
            )
            return
        if not silent:
            self.connect_screen.set_status(t("permissions.mic_requesting"), "info")
        try:
            request_permissions([Permission.RECORD_AUDIO], self._permission_result)
        except Exception as error:
            self.connect_screen.set_status(
                t("permissions.request_failed", error=f"{type(error).__name__}: {error}"),
                "error",
            )

    def _permission_result(self, permissions, grants):
        granted = bool(grants) and all(grants)
        status_key = "permissions.mic_granted" if granted else "permissions.mic_denied"
        Clock.schedule_once(
            lambda *_: self.connect_screen.set_status(t(status_key), "info"),
            0,
        )
        Clock.schedule_once(lambda *_: self._after_microphone_permission(granted), 0)
        if self.engine is not None:
            threading.Thread(
                target=self.engine.set_microphone_allowed, args=(granted,), daemon=True
            ).start()

    def _after_microphone_permission(self, granted):
        if not granted:
            self._stop_background_session()
            return
        if (
            not self._background_active
            and self.engine is not None
            and self.engine.snapshot()["connection"]["wanted"]
        ):
            self._start_background_session(
                "PartyDroid",
                self._notification_text or t("session.notification.active"),
            )

    def request_notifications(self, silent=False):
        if not is_android() or self._notifications_requested:
            return
        self._notifications_requested = True
        try:
            from jnius import autoclass

            if autoclass("android.os.Build$VERSION").SDK_INT < 33:
                return
            from android.permissions import Permission, check_permission, request_permissions

            if check_permission(Permission.POST_NOTIFICATIONS):
                return
        except Exception as error:
            if not silent:
                self.connect_screen.set_status(
                    t("permissions.notifications_failed", error=error),
                    "error",
                )
            return
        try:
            request_permissions([Permission.POST_NOTIFICATIONS], self._notification_permission_result)
        except Exception as error:
            if not silent:
                self.connect_screen.set_status(
                    t("permissions.notifications_failed", error=error),
                    "error",
                )

    def _notification_permission_result(self, permissions, grants):
        granted = bool(grants) and all(grants)
        print(f"PARTYLINE_BACKGROUND notifications={'granted' if granted else 'denied'}", flush=True)

    def _mic_permission(self):
        if not is_android():
            return True
        try:
            from android.permissions import Permission, check_permission

            return bool(check_permission(Permission.RECORD_AUDIO))
        except Exception:
            return True


def _log_diagnostics():
    try:
        versions = collect_versions()
        print("PARTYLINE_DIAGNOSTICS " + " ".join(f"{name}={value}" for name, value in versions.items()), flush=True)
    except Exception as error:
        print(f"PARTYLINE_DIAGNOSTICS error={type(error).__name__}: {error}", flush=True)


def _fill_diagnostics(label):
    try:
        text = "\n".join(f"{name}: {value}" for name, value in collect_versions().items())
    except Exception as error:
        text = t("diagnostics.error", error=f"{type(error).__name__}: {error}")
    Clock.schedule_once(lambda *_: setattr(label, "text", text), 0)


def _run_codecs(label):
    def worker():
        try:
            results = codec_roundtrip()
        except Exception as error:
            text = t("diagnostics.codecs_error", error=f"{type(error).__name__}: {error}")
        else:
            lines = []
            for result in results:
                if result.get("ok"):
                    lines.append(
                        t(
                            "diagnostics.codec_ok",
                            codec=result["codec"],
                            bytes=result["encoded_bytes"],
                            samples=result["decoded_samples"],
                        )
                    )
                else:
                    lines.append(
                        t(
                            "diagnostics.codec_fail",
                            codec=result["codec"],
                            error=result.get("error", ""),
                        ).rstrip()
                    )
            text = "\n".join(lines)
        Clock.schedule_once(lambda *_: setattr(label, "text", text), 0)

    threading.Thread(target=worker, daemon=True).start()


def _run_audio(label, app=None):
    if app is not None and app.engine is not None:
        audio = app.engine.snapshot().get("audio") or {}
        if audio.get("rx_ready") or audio.get("tx_ready"):
            Clock.schedule_once(
                lambda *_: setattr(label, "text", t("diagnostics.audio_busy")),
                0,
            )
            return

    def worker():
        try:
            results = audio_sanity()
        except Exception as error:
            text = t("diagnostics.audio_error", error=f"{type(error).__name__}: {error}")
        else:
            lines = []
            for result in results:
                if result.get("ok"):
                    lines.append(
                        t(
                            "diagnostics.audio_ok",
                            device=result["device"],
                            rate=result["samplerate"],
                        )
                    )
                else:
                    lines.append(
                        t(
                            "diagnostics.audio_fail",
                            device=result["device"],
                            error=result.get("error", ""),
                        ).rstrip()
                    )
            text = "\n".join(lines)
        Clock.schedule_once(lambda *_: setattr(label, "text", text), 0)

    threading.Thread(target=worker, daemon=True).start()


if __name__ == "__main__":
    PartyDroidApp().run()
