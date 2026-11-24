#!/bin/zsh
set -eu
cd "${0:A:h}"
export AFM_HARNESS_PANEL=edits
exec /bin/zsh '../Run Harness.command' "$@"
