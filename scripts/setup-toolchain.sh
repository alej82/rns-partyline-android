#!/usr/bin/env bash
# Creates the pinned build toolchain: a venv with buildozer and a p4a checkout.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

P4A_TAG="v2024.01.21"

if [ ! -x .build-venv/bin/buildozer ]; then
    python3 -m venv .build-venv
    .build-venv/bin/pip install -q -U pip wheel setuptools "cython<3" buildozer==1.5.0
fi

if [ ! -d .p4a ]; then
    git clone -q --depth 1 --branch "$P4A_TAG" https://github.com/kivy/python-for-android.git .p4a
fi

echo "buildozer: $(.build-venv/bin/buildozer --version)"
echo "p4a: $(git -C .p4a describe --tags --always)"
echo "siguiente: scripts/build-apk.sh (la primera vez descarga SDK/NDK)"
