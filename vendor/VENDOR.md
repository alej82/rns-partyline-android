# Vendored dependencies

## partyline 1.1.0

- Upstream: Partyline 1.1.0 (protocol version 1)
- Base commit: `a4ef0c4` (the release commit is not tagged upstream)
- Vendored at: `app/partyline/`
- Files: `__init__.py`, `audio.py`, `client.py`, `common.py`, `i18n.py`,
  `prefs.py`, `locale/`

`APP_VERSION` in `common.py` is still `1.0.5` upstream, so the vendored copy
keeps announcing `1.0.5` and a stock 1.1.0 server does not trigger a version
mismatch. Do not bump it locally: it would make every unpatched server report a
version warning on connect. `partyline_android.ENGINE_VERSION` mirrors this
release for the connect screen and the diagnostics dialog; update it when
re-vendoring.

1.1.0 only changes `client.py` for the engine (bounded receive structures:
`MAX_SPEAKERS`/`MAX_USERS`/`MAX_CHANNELS`/`MAX_EVENTS`/`MAX_INBOX`/`MAX_BURST`,
a per-second cap on new speakers, a 60 s speaker TTL trimmed from the receive
worker and `kicked` on an unknown room profile), plus the `ru` catalog. The
upstream `gui.py` fixes have no Android counterpart; the port already releases
PTT on focus loss and guards retries in the engine.

Patch list:

1. `common.py:52` — the configuration root resolves from `PARTYLINE_CONFIG_DIR`
   before falling back to `~/.config/partyline`, so the engine keeps its
   identity and state in Android app-private storage:

   ```python
   CONFIG_DIR = os.environ.get("PARTYLINE_CONFIG_DIR") or os.path.expanduser("~/.config/partyline")
   ```

2. `client.py` — `Client.cancel_transmit()` cancels the PTT hang timer and
   clears `ptt_down` immediately before reapplying the current mode. The
   Android app needs it when pausing or disconnecting while PTT is held, so
   transmit cannot resume on its own when audio is rebuilt. `Client.connect()`
   also calls it so a new session can never inherit a held PTT:

   ```python
   def cancel_transmit(self):
       self._cancel_ptt_hang()
       self.ptt_down = False
       self.apply_mode()
   ```

3. `client.py` — `Client.welcome()` clears rooms, users, per-user audio state
   and the playout before the server synchronization is applied. Without this,
   a reconnect keeps members from the previous link and can show duplicate
   identities or stale speakers.

The upstream `locale/` directory is copied verbatim from the pinned base commit
so the client's own gettext messages can follow the app language. It is an
added asset, not a code patch; the Spanish catalog covers the client messages
shown in the timeline (the only missing entry is `RTT {0} ms`, which remains in
source English). `buildozer.spec` includes `mo`, `po` and `pot` so the catalogs
are packaged.

No other vendored Python file differs from the upstream release. The patches
must be applied before `partyline` is imported;
`partyline_android.paths.prepare_environment()` sets `PARTYLINE_CONFIG_DIR` and
`HOME` at startup, and `partyline_android.i18n.configure()` installs the
resolved language before the engine starts.

## Runtime dependencies (installed by python-for-android)

- RNS 1.5.7
- LXST 0.5.4 (includes the Android source/sink backend)
- numpy 1.22.3
- libopus (local recipe: `p4a-recipes/libopus`)
- libcodec2 + pycodec2 (local recipes: `p4a-recipes/libcodec2`, `p4a-recipes/pycodec2`)
- libbz2 and liblzma (needed by RNS for `_bz2`/`_lzma`)

## LXST/pyogg Android compatibility

`LXST.Codecs.libs.pyogg` defines its ctypes aliases only when libogg can be
loaded, and resolves native libraries through `ctypes.util.find_library()`,
which does not work on Android. `app/partyline_android/pyogg_android.py`
installs an import hook that injects the missing aliases into `pyogg.ogg` and
extends pyogg's library loader to try the shared objects packaged in the APK
(`libopus.so`). No vendored LXST file is modified.
