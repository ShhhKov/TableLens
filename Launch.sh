#!/bin/sh
set -eu
APP_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
case "$(uname -s):$(uname -m)" in
    Linux:x86_64|Linux:amd64) APP_PLATFORM=linux-x64 ;;
    Linux:aarch64|Linux:arm64) APP_PLATFORM=linux-arm64 ;;
    Darwin:x86_64) APP_PLATFORM=macos-x64 ;;
    Darwin:arm64) APP_PLATFORM=macos-arm64 ;;
    *) printf 'Unsupported operating system or architecture.\n'; exit 1 ;;
esac
APP_PYTHON="$APP_DIR/runtime/$APP_PLATFORM/python/bin/python3"
if [ ! -x "$APP_PYTHON" ]; then
    printf 'Bundled Python is missing: %s\nCopy the entire application folder.\n' "$APP_PYTHON"
    exit 1
fi
cd "$APP_DIR"
exec "$APP_PYTHON" -B "$APP_DIR/editor.py" "$@"
