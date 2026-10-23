# Partyline Android

An Android port of [Partyline](https://github.com/RFnexus/partyline) built with
Python, Kivy and python-for-android. It reuses the unmodified Partyline protocol
(version 1, `lxst.room`) and the vendored Partyline client, adding a touch UI,
mobile settings and a foreground audio service.

Voice and chat traffic runs over Reticulum through a **Reticulum shared
instance running on the phone**; the app does not open its own Reticulum
interfaces. A shared instance (TCP port `37428`) must be running on the same
device before connecting. This port has been tested against the **Columba**
client's shared instance.

## Features

- **Connect** to a server by 32-character destination hash, with optional room,
  room password and server password.
- **Saved servers** with labels, remembered credentials and a most-recent list.
- **Session view** with three tabs:
  - **Chat** — room timeline with a single local echo, bounded to 500 lines,
    markup-safe rendering, speaker indicator and `+N` counter.
  - **Salas** — browse and switch rooms (Opus, Codec2 and music profiles).
  - **Miembros** — live member list with mute/deafen/operator state.
- **Push-to-talk voice** (PTT), plus mute and deafen. RX opens on room join;
  TX only while PTT is held. Opus and Codec2 are both available and switch per
  room profile.
- **Background audio** — a foreground `AudioService` (microphone type, partial
  wake lock, persistent notification) keeps the session alive when the app is
  backgrounded or the screen is off.
- **Mobile settings** — display name, input/output device, TX gain, mic AGC and
  keep-screen-on.
- **Diagnostics** (hidden behind `SHOW_DIAGNOSTICS` in `app/main.py`) — runtime
  versions, Opus/Codec2 roundtrip and an audio sanity check.
- **Automatic reconnects** with backoff and a 45-second connect watchdog.
- **Spanish UI.**

## Requirements

### On the device

- Android 7.0+ (API 24), `arm64-v8a`.
- A Reticulum shared instance running on the device, listening on TCP port
  `37428`. Tested with the **Columba** client's shared instance; other
  providers should work as long as they expose the same TCP shared instance.
- Microphone permission (denial keeps receive audio and disables transmit).
- Notification permission on Android 13+ for the background-session notice.

### Build host

- Linux with Python 3.11 or 3.10 (for buildozer 1.5.0).
- JDK 17 (the scripts default to `~/.local/jdk17`).
- Android SDK/NDK downloaded by the first build.
- `adb` for device installs.

The toolchain is pinned:

| Component | Version |
| --- | --- |
| buildozer | 1.5.0 |
| python-for-android | v2024.01.21 (`957a3e5`) |
| Python | 3.11.5 |
| Android API / min API | 33 / 24 |
| NDK | 25b |
| Architecture | `arm64-v8a` |

## Build and install

```bash
./scripts/setup-toolchain.sh   # one-time: buildozer venv, p4a checkout, SDK/NDK
./scripts/build-apk.sh         # -> bin/partyline-0.1.0-arm64-v8a-debug.apk
./scripts/install-apk.sh       # adb install + launch
```

Set `ANDROID_SERIAL` (or pass `-s <serial>`) when more than one device is
connected. Do not run two buildozer builds at the same time; incremental builds
take a minute or two, the first one much longer.

## Development without a device

The desktop harness runs the same engine and client code as the app.

Start a Partyline server with its own Reticulum instance (the development
server must **not** use Columba's shared instance):

```bash
./scripts/partyline-dev.sh setup
./scripts/partyline-dev.sh server
```

The server prints its destination hash. Connect a headless client:

```bash
.dev-venv/bin/python tools/headless_engine.py <32-hex-hash> \
  --configdir ~/.config/partyline-dev/client-rns \
  --statedir ~/.config/partyline-dev/headless-state --duration 45
```

Synthetic voice test (no microphone or speaker needed):

```bash
# Tone sender
.dev-venv/bin/python tools/headless_engine.py <hash> --room Lobby \
  --configdir ~/.config/partyline-dev/client-rns \
  --statedir ~/.config/partyline-dev/state-voice-sender \
  --name Sender --tone 440 --null-audio --duration 12

# Null-audio listener
.dev-venv/bin/python tools/headless_engine.py <hash> --room Lobby \
  --configdir ~/.config/partyline-dev/client-rns \
  --statedir ~/.config/partyline-dev/state-voice-listener \
  --name Listener --null-audio --listen --duration 25
```

Create the desktop virtualenv with:

```bash
python3 -m venv .dev-venv
```

The tests use only the standard library and mocks. The headless harness and the
probes also need the runtime dependencies (`rns`, `lxst`, `numpy`,
`cryptography`) installed in `.dev-venv`; the native `libopus`/`libcodec2`
libraries are only required for real audio.

## Tests

```bash
.dev-venv/bin/python -m unittest discover -s tests -v
.dev-venv/bin/python -m unittest tests.test_chatlog tests.test_engine -v
```

The suites cover reconnect backoff, audio state and lifecycle, PTT, chat
mapping/sync gating/bounded history, settings and saved-server persistence, and
the foreground-service fallback behavior.

Protocol and failure-mode probes (same client code as the app):

```bash
.dev-venv/bin/python tools/probes/no_path.py
.dev-venv/bin/python tools/probes/denial.py
.dev-venv/bin/python tools/probes/incompatible_protocol.py
.dev-venv/bin/python tools/probes/shared_instance_missing.py
```

## Architecture

```
app/main.py                     Kivy shell: connect screen, session tabs, settings, diagnostics
app/partyline/                  vendored Partyline 1.0.5 client (3 small Android patches)
app/partyline_android/
  paths.py                      HOME / PARTYLINE_CONFIG_DIR in app-private storage
  reticulum.py                  start Reticulum, SharedInstanceUnavailable
  rns_config.py                 shared-instance RNS config (TCP 37428)
  engine.py                     UI-independent facade: snapshots, JSON-able events, audio lifecycle
  chatlog.py                    event-to-line mapping, sync gating, bounded timeline
  settings.py                   MobileSettings (name, devices, gain, AGC, keep-screen-on)
  servers.py                    saved servers on the partyline ServerList schema
  diagnostics.py                versions, Opus/Codec2 roundtrip, audio_sanity()
  background.py                 foreground-service bridge
  pyogg_android.py              makes LXST's bundled pyogg work on Android
android-java/.../AudioService.java   foreground service (same process as the app)
p4a-recipes/                    libopus, libcodec2, pycodec2
tools/headless_engine.py        desktop/device engine harness
tools/probes/                   no-path, denial, protocol, shared-instance probes
tests/                          engine, chat, settings and background tests
openspec/specs/                 main specifications
openspec/changes/               active and archived OpenSpec changes
evidence/                       logs, screenshots, checklists, validation output
```

`main.py` never imports RNS, LXST or `partyline`; it talks to `Engine` through
`snapshot()` and `drain_events()` only. Engine payloads stay JSON-able, and
`ChatLog` owns all event-to-line interpretation so the UI only renders lines.

## Known limitations

- **Shared-instance RPC key.** RNS shared-instance clients derive their RPC key
  from their own transport identity, so the shared instance provider (Columba
  in our tests) rejects some RPC calls with `digest sent was rejected`. Link and
  announce traffic still work; only
  path-timeout/query helpers are affected. This adds a fallback delay (the
  engine retries with 3/5/10/20/30 s backoff). Configuring a matching `rpc_key`
  on both sides would remove it.
- **Microphone indicator.** LXST keeps the microphone open while in a room
  (PTT preroll), so Android shows the microphone indicator even when not
  transmitting.
- **Audio focus** is out of scope; the app does not duck or pause other media.
- **Chat is in memory only** — it is cleared on connect/leave and never written
  to disk. Saved room/server passwords are plaintext inside the app-private
  sandbox.

## Documentation

- [RFnexus/partyline](https://github.com/RFnexus/partyline) — original Partyline
  project, protocol and reference client/server.
- `AGENTS.md` — architecture rules, Android workarounds, device coordinates and
  verification workflow.
- `vendor/VENDOR.md` — the three patches applied to vendored Partyline.
- `openspec/specs/` — contracts for `android-runtime`, `mobile-shell` and
  `partyline-engine`.
- `evidence/` — build info, logcat captures, screenshots and checklists.

## License

This project is released into the public domain under the
[Unlicense](LICENSE), matching the original
[RFnexus/partyline](https://github.com/RFnexus/partyline) project.
