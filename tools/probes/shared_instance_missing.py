#!/usr/bin/env python3
"""Verify the specific error raised when Columba's shared instance is absent."""

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "app"))

import partyline_android
from partyline_android.reticulum import SharedInstanceUnavailable, start_reticulum

try:
    start_reticulum(tempfile.mkdtemp(prefix="rns-missing-"), require_shared=True)
except SharedInstanceUnavailable as error:
    print("SharedInstanceUnavailable:", error)
else:
    print("unexpected shared instance")
