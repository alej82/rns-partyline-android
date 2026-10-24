# AGENTS.md

## Project

Android port of Partyline. Python + Kivy UI on python-for-android, reusing the
unmodified Partyline protocol and the vendored `partyline` client. No server or
protocol changes.

```
app/main.py                     Kivy shell (connect screen, tabbed session, chat, speaker)
app/partyline/                  vendored partyline 1.0.5 (see vendor/VENDOR.md)
app/partyline_android/
  paths.py                      HOME / PARTYLINE_CONFIG_DIR in app-private storage
  rns_config.py                 RNS config for Columba's shared instance (TCP 37428)
  reticulum.py                  start Reticulum, SharedInstanceUnavailable
  engine.py                     UI-independent facade: snapshots, events, audio lifecycle
  chatlog.py                    bounded chat timeline + event-to-line mapping
  settings.py                   MobileSettings: name, audio devices/gain/AGC, keep-screen-on
  servers.py                    saved-server helpers on the partyline ServerList schema
  diagnostics.py                versions, Opus/Codec2 roundtrip, audio_sanity()
  pyogg_android.py              makes LXST's bundled pyogg work on Android
app/assets/mic.png              speaker indicator icon (packaged into the APK)
app/assets/logo.png             connect screen logo (packaged into the APK)
logo/                           brand source JPEG + generated launcher icon and presplash
scripts/make-brand-assets.sh    regenerates the brand assets from logo/logo.jpeg
p4a-recipes/                    libopus, libcodec2, pycodec2
tools/headless_engine.py        desktop/device engine harness (voice/chat: --tone/--null-audio/--listen)
tools/probes/                   no-path, denial, protocol, shared-instance probes
tests/test_engine.py            backoff, reconnects, audio state/lifecycle, PTT, text, settings
tests/test_chatlog.py           chat mapping, sync gating, bounded history, clear()
tests/test_settings.py          MobileSettings and saved-server persistence
openspec/specs/                 main specs (android-runtime, mobile-shell, partyline-engine)
openspec/changes/               active changes (none currently)
openspec/changes/archive/       archived foundation, voice, settings and chat changes
evidence/                       logs, screenshots, checklists, validation output
```

## Quick commands

```bash
./scripts/setup-toolchain.sh                 # one-time SDK/NDK/p4a/buildozer setup
./scripts/build-apk.sh                       # debug APK -> bin/partydroid-0.2.0-arm64-v8a-debug.apk
./scripts/install-apk.sh                     # adb install + launch
./scripts/make-brand-assets.sh               # regenerate logo/icon + presplash (ImageMagick 7)
./scripts/partyline-dev.sh server            # test server with its own RNS instance

.dev-venv/bin/python -m unittest discover -s tests -v
.dev-venv/bin/python -m unittest tests.test_chatlog tests.test_engine -v
.dev-venv/bin/python tools/headless_engine.py <32-hex-hash> \
  --configdir ~/.config/partyline-dev/client-rns \
  --statedir ~/.config/partyline-dev/headless-state --duration 45

# synthetic voice: tone sender and null-audio listener (no mic/speaker)
.dev-venv/bin/python tools/headless_engine.py <32-hex-hash> --room Lobby \
  --configdir ~/.config/partyline-dev/client-rns \
  --statedir ~/.config/partyline-dev/state-voice-sender \
  --name Sender --tone 440 --null-audio --duration 12
.dev-venv/bin/python tools/headless_engine.py <32-hex-hash> --room Lobby \
  --configdir ~/.config/partyline-dev/client-rns \
  --statedir ~/.config/partyline-dev/state-voice-listener \
  --name Listener --null-audio --listen --duration 25

openspec validate android-runtime --strict
openspec validate mobile-shell --strict
openspec validate partyline-engine --strict
```

## Toolchain (pinned)

- buildozer 1.5.0 in `.build-venv`
- python-for-android `v2024.01.21` (commit `957a3e5`) in `.p4a`
- Python 3.11.5, API 33, min API 24, NDK 25b, `arm64-v8a`
- JDK 17 at `~/.local/jdk17` (the system Java is only a JRE)
- Reference device: Android 12 / API 31, serial `<device-serial>`
  (confirm with `adb devices`; pass `-s <serial>`)

Native dependencies live in `buildozer.spec` requirements: `libopus`,
`pycodec2`, `libbz2`, `liblzma`. Adding a native library requires a local recipe
in `p4a-recipes/` **and** the requirement entry, then verify the `.so` is inside
the APK (`unzip -l bin/*.apk | grep lib/arm64-v8a`).

## Architecture rules

- `app/main.py` must not import RNS, LXST or `partyline`. It talks to `Engine`
  through `snapshot()` and `drain_events()` only, and calls engine methods.
- Engine payloads and snapshots must stay JSON-able. Never put RNS objects,
  bytes (use hex) or `partyline.Client` instances in them.
- `ChatLog` owns all event-to-line interpretation (sync gating, room names,
  own/self detection, translated system/warning/error text). Keep it free of
  Kivy; `main.py` only appends returned lines and renders them.
- All app-owned user-facing text goes through
  `partyline_android.i18n.t(key, **params)`. The master catalog is
  `app/assets/i18n/translations.json` (English plus structured context); each
  language is a flat `app/assets/i18n/<code>.json`. Never translate server data
  (room/user names, MOTD, denial reasons, hashes) or codec/device identifiers.
  New visible text requires a key and a Spanish entry; a new language adds a
  flat file and a `meta.languages` entry.
- The language preference is `language` in `MobileSettings` (`system`, `es`,
  `en`). `PartylineApp.build()` resolves it with `configure()` before the
  engine starts and installs the vendored client's gettext catalog. Changing to
  a different language rebuilds the interface in place and ends the session; do
  not reuse the old chat timeline or engine error strings.
- Chat is in memory only, bounded to 500 lines. Clear it on `connect()` and
  `leave_session()`, keep it across automatic reconnects, and never write it to
  disk. `connected` resets sync gating and the room-name map but preserves lines.
- `Engine.send_text()` must return `False` when there is no client, no
  connection, no joined room, or only whitespace. Keep using
  `Client.send_text()` for sanitizing, truncation and the single local echo; do
  not echo again in the engine or UI. Text is independent of mute/listen-only.
- Suppress self joins/leaves/moves/operator changes by SID **and** identity: a
  reconnect can deliver a stale `user_left` for the previous SID of the same
  identity. Gate `user_joined` on `synced`.
- RNS must start on the main thread (`signal.signal` fails in a worker).
  `PartylineApp._prestart()` runs it at app open; the engine facade owns the
  client and the dispatch thread.
- `prepare_environment()` must run before any `partyline`/LXST import. It sets
  `HOME`, `PARTYLINE_CONFIG_DIR` and `PARTYLINE_RNS_DIR` to app-private storage.
- The app's RNS config uses `share_instance = Yes`, `shared_instance_type = tcp`,
  port `37428`, `require_shared_instance = Yes`, and **no interfaces**. All
  traffic goes through Columba's shared instance.
- The Partyline *server* used for development must run with its own RNS
  instance (`share_instance = No`). Attaching it to MeshChat/Columba's shared
  instance made the first link fail.
- Voice is enabled in PTT mode: RX opens on room join; TX only while PTT is
  held. `Engine.set_microphone_allowed()` is the permission gate; call it at
  startup, on the permission result and on resume. Denial keeps RX and disables
  TX.
- Keep `Client.cancel_transmit()` on connect/disconnect/pause. It prevents a
  held PTT from surviving a reconnect or audio rebuild.
- A session keeps capture and playback alive in the background through the
  same-process `AudioService` (`FOREGROUND_SERVICE_TYPE_MICROPHONE`). Start it
  from `connect()` while the activity is visible, update the notification on
  room changes, and stop it from `leave_session()`, `on_stop()` or task
  removal. `on_pause` releases PTT and the screen-on hold but must not call
  `pause_audio()` while the service is active; use suspension only as the
  fallback when the service is unavailable.
- Do not force an audio rebuild on resume. `set_microphone_allowed()` is a
  no-op when the permission value did not change, and `resume_audio()` only
  rebuilds when RX or TX are actually missing.
- Keep the `Client.welcome()` per-session reset (rooms, users, audio state).
  Without it a reconnect keeps stale members and can show duplicate identities.
- Never open a second LXST source/sink while session audio is active; the
  diagnostics “Probar audio” action must stay blocked in a session.
- `MobileSettings` and `SavedServers` read/write `PARTYLINE_CONFIG_DIR`
  `settings.json`/`servers.json` with `0600`. Saved room/server passwords are
  plaintext inside the app-private sandbox (accepted trade-off).

## Android-specific workarounds (do not regress)

- `partyline` is vendored with three small patches (see `vendor/VENDOR.md`):
  `CONFIG_DIR` from `PARTYLINE_CONFIG_DIR`, `cancel_transmit()` plus the connect
  reset, and the `welcome()` per-session reset.
- LXST's bundled pyogg defines ctypes aliases only when libogg loads, and uses
  `ctypes.util.find_library()`, which fails on Android. `pyogg_android.install()`
  (called from `partyline_android/__init__.py`) injects the aliases and loads
  `libopus.so` from the APK. Do not patch vendored LXST files.
- The app includes `libbz2`/`liblzma`; without them RNS fails with
  `ModuleNotFoundError: No module named '_bz2'`.
- Kivy's icon copy warning and missing `blake2b`/`blake2s` are harmless; RNS uses
  SHA-256 and sessions work.
- The reference activity keeps `softInputMode=adjustPan` even with
  `Window.softinput_mode="resize"`, so the Kivy window does not shrink around the
  keyboard. `PartylineApp._poll_keyboard()` reads `WindowInsets.Type.ime()` and
  `SessionScreen.set_keyboard_height()` reserves it as a bottom spacer. Do not
  switch to pan mode: it shifts rendering but not hit-testing, making the Send
  button untappable while the keyboard is open.
- `ChatSendButton` adds its touch to `FocusBehavior.ignored_touch` so tapping
  Enviar keeps the `TextInput` focused and the keyboard open.
- `app/assets/mic.png` is bundled through `source.include_exts`; verify it inside
  the APK with `unzip -p bin/*.apk assets/private.tar | tar -tf - | grep mic.png`.
- Brand assets come from `scripts/make-brand-assets.sh` and `logo/logo.jpeg`.
  p4a copies the icon verbatim and needs both adaptive layers; keep the artwork
  inside Android's 66dp safe zone (currently 65% of the 108dp canvas) and keep
  the presplash JPEG on `#12141A` so its letterbox bands blend.
- Some launchers can keep showing the previous icon in the recents header after the
  launcher icon changes, even when the launcher and app info already show the
  new one. It is a launcher cache, not the APK; force-stop
  the launcher (or reboot) and re-check the task.
- LXST keeps the microphone open while in a room (PTT preroll), so Android shows
  the microphone indicator even when not transmitting. With background audio it
  also stays open while the app is backgrounded; the foreground service uses the
  `microphone` type, a persistent notification and a partial wake lock. Audio
  focus is still out of scope.
- The foreground service is added with `android.add_src`, declared through
  `p4a.extra_args = --native-service ...`, and typed by `tools/p4a_hook.py`
  (`after_apk_build`). It must stay in the app process (no `android:process`) so
  it protects the engine and LXST. Verify the APK manifest after changing the
  pinned p4a version.

## Known limitation: shared-instance RPC

RNS shared-instance clients derive the RPC `rpc_key` from their own transport
identity, so Columba rejects RPC calls with `digest sent was rejected`. This
only affects path-timeout/query helpers; link and announce traffic work. The
engine has a 45 s connect watchdog and retries with 3/5/10/20/30 s backoff, so
slow establishment does not wedge the UI. Do not "fix" this by disabling the
shared instance. Configuring a matching `rpc_key` on both sides would remove the
fallback delay.

## Build and device workflow

- Do not run two buildozer builds at once. Incremental builds take ~1-2 minutes;
  the first one takes much longer.
- `scripts/build-apk.sh` already pins `JAVA_HOME`, the venv and `PATH`.
- The message `failed to apply patch ... assuming it is already applied` for
  `SDLActivity.java.patch` is expected on subsequent builds.
- Start long-running servers with `setsid nohup ... < /dev/null & disown`.
  Plain `nohup` inside a shell command can die when the command times out.
- Never use `pkill`/`killall` (it hangs this terminal). Use `kill -TERM <pid>`.
- Kivy renders into one SDL surface, so `uiautomator` shows no widgets. Drive
  the UI with `adb shell input tap/text` and `adb exec-out screencap -p`.
  Confirm with a screenshot; the top bar shifts when the speaker widget appears.
  Coordinates vary by device; locate widgets from a screenshot first.
- Room buttons live inside a `ScrollView`: a fast `input tap` can miss
  `on_release`. Use `adb shell input swipe X Y X Y 300` to press them.

## Verification

Useful logcat filters:

```bash
adb -s <device-serial> logcat -c
adb -s <device-serial> shell am force-stop com.hume4ever.partydroid
adb -s <device-serial> shell am start -n com.hume4ever.partydroid/org.kivy.android.PythonActivity
adb -s <device-serial> logcat -d | grep -E "PARTYLINE_TRANSPORT|PARTYLINE_DIAGNOSTICS|PARTYLINE_BACKGROUND|Audio configured|AudioRecord|AudioTrack|Traceback"
```

Expected: `PARTYLINE_TRANSPORT shared_instance=True identity=<stable hash>`,
`PARTYLINE_DIAGNOSTICS ... rns=1.5.7 lxst=0.5.4 opus=available codec2=...`,
`Audio configured for Opus ...` or `Audio configured for Codec2 ...` on join,
and `PARTYLINE_BACKGROUND foreground session started type=microphone` while in
a session.

On-device checks: connect to the dev server, confirm WELCOME/rooms/users/RTT,
then use **Diagnóstico → Probar códecs / Probar audio**. For voice, verify RX
with a synthetic tone sender, TX with a null-audio listener while holding PTT,
mute/deafen, permission denial and late grant, pause/resume with PTT held, and
an Opus ↔ Codec2 profile change. For background audio, verify a tone keeps
playing after home and screen off, the room notification is present, tapping it
returns to the same session, returning does not rebuild audio, and Salir/task
removal stops both the notification and audio. Capture evidence.

For chat, verify send/receive with two room members, exactly one local echo,
disabled input while disconnected or without a room, the `Chat/Salas/Miembros`
tabs, room-change separators, reconnect history preservation, clearing on
Salir/Conectar and app restart, speaker `+N`, keyboard behavior, markup
escaping and scrolling while reading older lines. Run the chat/engine tests and
capture `evidence/chat-*.png` plus `evidence/chat-tests.txt`.

For branding, verify the circular badge sits above the `PartyDroid` heading
with every field and button visible, the launcher shows the adaptive icon (not
the p4a default) with the artwork inside the mask, and the cold-start presplash
appears on `#12141A`. Capture `evidence/branding-*.png`.

```bash
.dev-venv/bin/python -m unittest discover -s tests -v
unzip -l bin/*.apk | grep -E "res/mipmap|presplash"
unzip -p bin/*.apk assets/private.tar | tar -tzf - | grep -E "assets/(logo|mic)\.png"
```

Desktop probes (same client code as the app):

```bash
.dev-venv/bin/python tools/probes/no_path.py
.dev-venv/bin/python tools/probes/denial.py
.dev-venv/bin/python tools/probes/incompatible_protocol.py
.dev-venv/bin/python tools/probes/shared_instance_missing.py
```

## OpenSpec workflow

1. Keep the active change's `tasks.md` checkboxes current as work lands; do not
   mark a task done without evidence.
2. Write evidence to `evidence/` (logs, screenshots, checklists, commands).
   `evidence/on-device-checklist.md` and `evidence/commands.md` are the index.
3. Run `openspec validate <change> --strict` (or validate the three specs)
   before closing and save the output to `evidence/openspec-validate.txt`.
4. `android-foundation`, `android-voice-ptt`, `add-profile-servers-settings`
   and `add-room-chat` are archived under `openspec/changes/archive/`; the
   active contracts live in `openspec/specs/`.

## Conventions

- Follow the existing style: standard library first, no new Python dependencies
  unless they are added to `buildozer.spec` and tested on device.
- Keep comments minimal; use docstrings for non-obvious Android workarounds.
- UI strings are localized; English is the fallback and Spanish remains the
  library default for headless/test callers. Engine errors are user-facing and should explain the next action (e.g.
  "Abre Columba…") through the catalog, not as hardcoded text.
- Chat rendering: one `Label` per line, escape every name/message with
  `kivy.utils.escape_markup`, and keep the timeline fixed: touch scrolling is
  disabled and the view always stays pinned to the newest line. Never persist
  chat.
- Translation assets live in `app/assets/i18n/` and the copied
  `app/partyline/locale/`; `source.include_exts` includes `json`, `mo`, `po`
  and `pot` so they are packaged.
- The Diagnostics/`Diagnóstico` buttons (connect screen and session header) are
  gated by `SHOW_DIAGNOSTICS` at the top of `app/main.py`, default `False`.
  Set it to `True` to expose them again.
- Do not commit secrets, identities or `~/.config/partyline-dev` contents.
