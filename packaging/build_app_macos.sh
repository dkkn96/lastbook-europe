#!/bin/bash
# Builds the Lastbook Europe app and disk image for Apple Silicon. Needs uv.
#   bash packaging/build_app_macos.sh
#
# Each build gets a new folder, derived/app-build/mac/<date-time>/, so nothing ever has to be removed.
# derived/app-build/mac/Lastbook.app points at the newest good one.
# The app is ad-hoc signed by the build tool and nothing more: no certificate, no notarization.
# Optional: put one word per line in derived/app-build/scan-terms.txt (machine names, user names) and the scan refuses a package holding any.
set -euo pipefail
HERE="$(dirname "$(/bin/realpath "$0")")"
ROOT="$(dirname "$HERE")"
BUILD="$ROOT/derived/app-build"
PYVER=3.11.18   # 3.11.18 or later: earlier 3.11 releases lack the block on the compromised eMudhra CA keys (security audit, 12 Nov 2026)
mkdir -p "$BUILD/mac"
OUT="$(mktemp -d "$BUILD/mac/$(date +%Y%m%d-%H%M%S).XXXXXXXX")"
VENV="$OUT/venv"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPYCACHEPREFIX="$BUILD/mac/pycache"
export PYINSTALLER_CONFIG_DIR="$BUILD/mac/pyinstaller-cache"
if [ "$(uname -m)" != arm64 ]; then
  echo "This build is for Apple Silicon." >&2
  exit 1
fi
mkdir -p "$OUT"
LOCAL_PYTHON="$ROOT/derived/mac-toolchain/python"
if [ -x "$LOCAL_PYTHON/bin/python3.11" ]; then
  LASTBOOK_BUILD_PYTHON="${LASTBOOK_BUILD_PYTHON:-$LOCAL_PYTHON/bin/python3.11}"
fi
uv venv --python "${LASTBOOK_BUILD_PYTHON:-$PYVER}" "$VENV"
"$VENV/bin/python" -c "import sys; v = '.'.join(map(str, sys.version_info[:3])); sys.exit(None if v == '$PYVER' else f'build Python is {v}, not $PYVER')"
uv pip install --python "$VENV/bin/python" -r "$HERE/requirements_macos.txt"
"$VENV/bin/python" -I -B "$HERE/ship_app_files.py" "$OUT/ship"   # web/ and content/ as they ship: see ship_edits.json
mkdir -p "$OUT/ship/setup"
cp "$ROOT/setup/starter-manifest-v1.json" "$OUT/ship/setup/manifest-v1.json"
RUNTIME="$("$VENV/bin/python" -c 'import sys; print(sys.base_prefix)')"
if [ -d "$RUNTIME/licenses" ]; then
  cp "$RUNTIME"/licenses/*.txt "$OUT/ship/"
fi
# Release gate: setup's downloader verifies every download host through engine/setup/roots.pem only (no system trust store)
"$VENV/bin/python" -I -B "$HERE/check_tls_roots.py" --europe-maps
export LASTBOOK_SHIP="$OUT/ship"
"$VENV/bin/python" -m PyInstaller --noconfirm --distpath "$OUT/dist" --workpath "$OUT/work" "$HERE/lastbook_macos.spec" 2>&1 | tee "$OUT/build.log"
BUNDLE="$OUT/dist/Lastbook.app"
"$VENV/bin/python" "$HERE/scan_package_macos.py" "$BUNDLE" --terms-file "$BUILD/scan-terms.txt" | tee "$OUT/scan.txt"
codesign --verify --deep --strict "$BUNDLE"
STAGING="$OUT/dmg"
mkdir "$STAGING"
ditto "$BUNDLE" "$STAGING/Lastbook Europe.app"
ln -s /Applications "$STAGING/Applications"
IMAGE="$OUT/Lastbook-Europe-macOS-arm64.dmg"
hdiutil create -ov -format UDZO -volname "Lastbook Europe" -srcfolder "$STAGING" "$IMAGE"
hdiutil verify "$IMAGE"
ln -sfn "$BUNDLE" "$BUILD/mac/Lastbook.app"
du -h "$IMAGE"
echo "Built: $IMAGE"
