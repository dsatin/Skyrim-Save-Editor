#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd -- "$SCRIPT_DIR/../.." && pwd)"
BUILD_DIR="$ROOT_DIR/build/appimage"
APPDIR="$BUILD_DIR/SkyrimSaveLab.AppDir"
PYTHON_BIN="${PYTHON_BIN:-python3}"

case "$(uname -m)" in
    x86_64)
        APPIMAGE_ARCH=x86_64
        ;;
    aarch64|arm64)
        APPIMAGE_ARCH=aarch64
        ;;
    *)
        echo "Unsupported AppImage architecture: $(uname -m)" >&2
        exit 1
        ;;
esac

VERSION="${VERSION:-$(git -C "$ROOT_DIR" describe --tags --always --dirty)}"
OUTPUT_DIR="${OUTPUT_DIR:-$ROOT_DIR/dist}"
OUTPUT="$OUTPUT_DIR/SkyrimSaveLab-${VERSION}-${APPIMAGE_ARCH}.AppImage"

if [[ -n "${APPIMAGETOOL:-}" ]]; then
    APPIMAGETOOL_BIN="$APPIMAGETOOL"
else
    TOOL_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/skyrim-save-lab"
    APPIMAGETOOL_BIN="$TOOL_DIR/appimagetool-${APPIMAGE_ARCH}.AppImage"
    if [[ ! -x "$APPIMAGETOOL_BIN" ]]; then
        mkdir -p "$TOOL_DIR"
        curl --fail --location --retry 3 \
            --output "$APPIMAGETOOL_BIN" \
            "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-${APPIMAGE_ARCH}.AppImage"
        chmod +x "$APPIMAGETOOL_BIN"
    fi
fi

rm -rf "$BUILD_DIR" "$ROOT_DIR/build/SkyrimSaveLab" "$ROOT_DIR/dist/SkyrimSaveLab"
mkdir -p "$APPDIR/usr/lib/skyrim-save-lab" \
    "$APPDIR/usr/share/applications" \
    "$APPDIR/usr/share/icons/hicolor/512x512/apps" \
    "$OUTPUT_DIR"

cd "$ROOT_DIR"
"$PYTHON_BIN" -m PyInstaller \
    --clean \
    --noconfirm \
    --onedir \
    --windowed \
    --name SkyrimSaveLab \
    --add-data "app/resources:app/resources" \
    --hidden-import lz4.block \
    --icon app/resources/icons/skyrim.png \
    run.py

cp -a "$ROOT_DIR/dist/SkyrimSaveLab/." "$APPDIR/usr/lib/skyrim-save-lab/"
install -Dm755 "$SCRIPT_DIR/AppRun" "$APPDIR/AppRun"
install -Dm644 \
    "$SCRIPT_DIR/io.github.xcier.SkyrimSaveLab.desktop" \
    "$APPDIR/io.github.xcier.SkyrimSaveLab.desktop"
install -Dm644 \
    "$SCRIPT_DIR/io.github.xcier.SkyrimSaveLab.desktop" \
    "$APPDIR/usr/share/applications/io.github.xcier.SkyrimSaveLab.desktop"
install -Dm644 \
    "$ROOT_DIR/app/resources/icons/skyrim.png" \
    "$APPDIR/io.github.xcier.SkyrimSaveLab.png"
install -Dm644 \
    "$ROOT_DIR/app/resources/icons/skyrim.png" \
    "$APPDIR/usr/share/icons/hicolor/512x512/apps/io.github.xcier.SkyrimSaveLab.png"
ln -sfn io.github.xcier.SkyrimSaveLab.png "$APPDIR/.DirIcon"

rm -f "$OUTPUT"
ARCH="$APPIMAGE_ARCH" APPIMAGE_EXTRACT_AND_RUN=1 \
    "$APPIMAGETOOL_BIN" "$APPDIR" "$OUTPUT"
chmod +x "$OUTPUT"

echo "AppImage created at: $OUTPUT"
