# Vendored dependencies

## partyline 1.0.5

- Upstream: Partyline 1.0.5 (protocol version 1)
- Base commit: `5a4866f`
- Vendored at: `app/partyline/`
- Files: `__init__.py`, `audio.py`, `client.py`, `common.py`, `i18n.py`, `prefs.py`

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

No other vendored file differs from the upstream release. The patches must be
applied before `partyline` is imported; `partyline_android.paths.prepare_environment()`
sets `PARTYLINE_CONFIG_DIR` and `HOME` at startup.

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
