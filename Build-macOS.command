#!/bin/bash
set -eu
cd "$(dirname "$0")"

if [ ! -x ".venv/bin/python" ]; then
  ./Setup-macOS.command
fi

.venv/bin/python -m pip install pyinstaller

# Directory mode, not --onefile: a onefile .app unpacks itself on every launch,
# which is slow with MarkItDown's dependencies, and the tkdnd data files are
# more reliable when they sit alongside the binary.
.venv/bin/pyinstaller --noconfirm --clean --windowed \
  --name "MarkItDown Desktop" \
  --additional-hooks-dir=. \
  --collect-all markitdown \
  app.py

APP="dist/MarkItDown Desktop.app"

# Signing is optional. Without it the app still runs, but macOS shows a
# Gatekeeper warning the first time and users must Control-click and Open.
if [ -n "${APPLE_DEVELOPER_ID:-}" ]; then
  echo "Signing with $APPLE_DEVELOPER_ID..."
  codesign --deep --force --options runtime --timestamp --sign "$APPLE_DEVELOPER_ID" "$APP"

  if [ -n "${APPLE_ID:-}" ] && [ -n "${APPLE_TEAM_ID:-}" ] && [ -n "${APPLE_APP_PASSWORD:-}" ]; then
    echo "Submitting for notarization (this can take several minutes)..."
    ditto -c -k --keepParent "$APP" dist/notarize.zip
    xcrun notarytool submit dist/notarize.zip \
      --apple-id "$APPLE_ID" --team-id "$APPLE_TEAM_ID" \
      --password "$APPLE_APP_PASSWORD" --wait
    xcrun stapler staple "$APP"
    echo "Notarized and stapled."
  else
    echo "Signed but not notarized. Set APPLE_ID, APPLE_TEAM_ID and APPLE_APP_PASSWORD to notarize."
  fi
else
  echo "Built unsigned. Set APPLE_DEVELOPER_ID to sign, and the APPLE_* variables to notarize."
fi

echo "Build complete: $APP"
read -r -p "Press Return to close..."
