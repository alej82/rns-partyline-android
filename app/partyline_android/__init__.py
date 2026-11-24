"""Android client package for Partyline."""

from .pyogg_android import install

# Vendored upstream release, keep in sync with vendor/VENDOR.md. The vendored
# client's own APP_VERSION is still 1.0.5 upstream, so it is not shown as the
# engine version on screen.
ENGINE_VERSION = "1.1.0"

# Shown under the connect-screen title and in the diagnostics popup.
# tests/test_version.py fails if this drifts from buildozer.spec.
APP_VERSION = "0.5.1"

install()
