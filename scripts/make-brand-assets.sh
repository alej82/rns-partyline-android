#!/usr/bin/env bash
# Regenerates the PartyDroid brand assets from logo/logo.jpeg.
#
# Requires ImageMagick 7 (`magick`). Build assets stay in logo/; only the
# in-app badge is copied into app/assets/ so Kivy can read it at runtime.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT/logo/logo.jpeg"
OUT="$ROOT/logo"
ASSETS="$ROOT/app/assets"

command -v magick >/dev/null || { echo "error: falta ImageMagick 7 (magick)" >&2; exit 1; }
[ -f "$SRC" ] || { echo "error: falta $SRC" >&2; exit 1; }

mkdir -p "$OUT" "$ASSETS"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# Artwork bounding box is 896x537 centered at (548,508). The 940 circle
# removes the dead air above/below while keeping every extreme point inside.
magick "$SRC" -crop 940x940+78+38 +repage "$TMP/circle.png"
magick -size 940x940 xc:none -fill white -draw "circle 470,470 470,0" "$TMP/mask.png"
magick "$TMP/circle.png" "$TMP/mask.png" -alpha off -compose CopyOpacity \
  -composite -resize 512x512 "$ASSETS/logo.png"

# 952 zoom crop keeps 28 px of the original blue at the left/right edges so
# the adaptive foreground blends into the solid background.
magick "$SRC" -crop 952x952+72+32 +repage "$TMP/zoom.png"
magick "$TMP/zoom.png" -resize 512x512 "$OUT/icon.png"
magick -size 432x432 "xc:#3963AD" "$OUT/icon-bg.png"
magick -size 432x432 xc:none \( "$TMP/zoom.png" -resize 281x281 \) \
  -gravity center -composite "$OUT/icon-fg.png"

# Boot presplash: dark canvas with the 640 px circular badge centered. The
# letterbox bands blend because android.presplash_color is the same #12141A.
magick -size 1080x1920 "xc:#12141A" \( "$ASSETS/logo.png" -resize 640x640 \) \
  -gravity center -composite -quality 90 "$OUT/presplash.jpg"

echo "Wrote:"
ls -l "$OUT/icon.png" "$OUT/icon-fg.png" "$OUT/icon-bg.png" \
  "$OUT/presplash.jpg" "$ASSETS/logo.png"
