#!/bin/zsh
set -eu
cd "${0:A:h}"
run_model=both
run_work="$PWD/build/session"
while (( $# )); do
  case "$1" in
    --only) run_model="$2"; shift 2 ;;
    --work) run_work="${2:a}"; shift 2 ;;
    *) print -u2 'Usage: Run Evaluation.command [--only both|system|pcc] [--work directory]'; exit 2 ;;
  esac
done
case "$run_model" in both|system|pcc) ;; *) print -u2 'Unknown model selection'; exit 2 ;; esac
export AFM_STUDY_WORK="$run_work"
mkdir -p "$run_work" build
echo "AFM 3 日本語評価。PCCには同梱の合成資料のみ送信します。"
if [[ ! -x build/vision-tool || Vision.swift -nt build/vision-tool ]]; then
  xcrun swiftc -O -parse-as-library -module-cache-path "$PWD/build/module-cache" Vision.swift -o build/vision-tool
fi
/usr/bin/python3 -B vision_cache.py build/vision-cache build/vision-tool
if [[ "$run_model" != pcc ]]; then
  set -o pipefail
  /usr/bin/python3 -B evaluate.py --only system --work "$run_work" | tee -a "$run_work/terminal.log"
fi
if [[ "$run_model" != system ]]; then
  source './Run PCC.zsh'
fi
