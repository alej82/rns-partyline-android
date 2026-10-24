"""Finalize the generated manifest for the same-process foreground service."""

import os
import re

SERVICE_NAME = "com.hume4ever.partydroid.AudioService"
SERVICE_RE = re.compile(
    r'<service\s+android:name="' + re.escape(SERVICE_NAME) + r'"([^>]*?)/>'
)


def after_apk_build(_toolchain):
    path = os.path.join(os.getcwd(), "src", "main", "AndroidManifest.xml")
    with open(path, "r", encoding="utf-8") as manifest_file:
        manifest = manifest_file.read()

    match = SERVICE_RE.search(manifest)
    if match is None:
        raise RuntimeError(f"p4a manifest is missing the {SERVICE_NAME} service")

    attributes = match.group(1)
    if 'android:foregroundServiceType="microphone"' in attributes:
        return

    attributes = attributes.rstrip() + ' android:foregroundServiceType="microphone"'
    if 'android:exported=' not in attributes:
        attributes += ' android:exported="false"'
    replacement = f'<service android:name="{SERVICE_NAME}"{attributes} />'
    manifest = manifest[: match.start()] + replacement + manifest[match.end():]

    with open(path, "w", encoding="utf-8") as manifest_file:
        manifest_file.write(manifest)
    print("PARTYLINE_BUILD foreground service typed as microphone", flush=True)
