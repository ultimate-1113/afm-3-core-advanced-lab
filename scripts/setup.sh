#!/bin/zsh
set -euo pipefail
LAB_ROOT="${0:A:h:h}"
export DEVELOPER_DIR="${DEVELOPER_DIR:-/Applications/Xcode.app/Contents/Developer}"
LAB_PYTHON="${AFM_LAB_PYTHON:-python3}"
"$LAB_PYTHON" -c 'import sys; assert sys.version_info >= (3,10), "Python 3.10+ is required; set AFM_LAB_PYTHON"'
[[ -d "$DEVELOPER_DIR" ]] || { print -u2 'Full Xcode is required; set DEVELOPER_DIR'; exit 1; }
mkdir -p "$LAB_ROOT/bin" "$LAB_ROOT/results" "$LAB_ROOT/data/images" "$LAB_ROOT/build"
if [[ ! -x "$LAB_ROOT/.venv/bin/python" ]]; then "$LAB_PYTHON" -m venv "$LAB_ROOT/.venv"; fi
"$LAB_ROOT/.venv/bin/python" -c 'import apple_fm_sdk; import importlib.metadata; assert importlib.metadata.version("apple-fm-sdk")=="0.2.1"' 2>/dev/null || "$LAB_ROOT/.venv/bin/python" -m pip install apple-fm-sdk==0.2.1
xcrun swiftc -O -parse-as-library -swift-version 5 -module-cache-path "$LAB_ROOT/build/module-cache" "$LAB_ROOT/src/Runner.swift" -o "$LAB_ROOT/bin/afm-runner"
if [[ ! -f "$LAB_ROOT/data/manifest.json" ]]; then "$LAB_ROOT/.venv/bin/python" "$LAB_ROOT/scripts/cases.py"; fi
"$LAB_ROOT/bin/afm-runner" --fixtures "$LAB_ROOT/data/images"
