#!/bin/zsh
set -eu
cd "${0:A:h}"
/usr/bin/python3 -B study.py generate
/usr/bin/python3 -B study.py export
