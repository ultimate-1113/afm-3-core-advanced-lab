#!/bin/zsh
set -eu
cd "${0:A:h}"
if [[ ${AFM_HARNESS_PANEL:-primary} == edits ]]; then
  cd edits
fi
route=${1:-both}
case "$route" in both|system|pcc) ;; *) print -u2 'Expected both, system, or pcc.'; exit 2 ;; esac
export AFM_HARNESS_WORK="${AFM_HARNESS_WORK:-$PWD/build/session}"
part="$AFM_HARNESS_WORK/terminal"
mkdir -p "$part"
zmodload zsh/datetime
zmodload zsh/system
: >> "$part/session.lock"
zsystem flock -t 0 -f lock_fd "$part/session.lock" || { print -u2 'A run is already active.'; exit 1; }
{
  /usr/bin/fm models > "$part/models"
  /usr/bin/python3 -B run.py init "$route"
  print '合成資料によるAFM 3ハーネス評価を開始します。'
  queue=("${(@f)$(<"$part/sequence")}")
  for job in "${queue[@]}"; do
    args=("${(@s: :)job}"); model=$args[1]; cid=$args[2]; arm=$args[3]
    if /usr/bin/python3 -B run.py prepare "$model" "$cid" "$arm"; then
      :
    else
      ret=$?
      (( ret == 3 )) && continue
      exit $ret
    fi
    qb=0
    if [[ "$model" == pcc ]]; then
      /usr/bin/fm quota-usage --model pcc > "$part/quota-before" 2>&1 || qb=$?
    fi
    /usr/bin/python3 -B run.py before "$qb"
    flags=(respond --model "$model" --greedy --stream --instructions "$(<"$part/instructions")" --save-transcript "$part/transcript.json")
    [[ -s "$part/schema" ]] && flags+=(--schema "$(<"$part/schema")")
    [[ -s "$part/image" ]] && flags+=(--image "$(<"$part/image")")
    flags+=(--text "$(<"$part/prompt")")
    print "$model  $cid  $arm"
    started=$EPOCHREALTIME
    /usr/bin/fm "${flags[@]}" 2> "$part/stderr" | /usr/bin/python3 -B run.py capture
    rc=$pipestatus[1]; ended=$EPOCHREALTIME
    qa=0
    if [[ "$model" == pcc ]]; then
      /usr/bin/fm quota-usage --model pcc > "$part/quota-after" 2>&1 || qa=$?
    fi
    /usr/bin/python3 -B run.py after "$rc" "$started" "$ended" "$qa"
  done
  /usr/bin/python3 -B run.py end
  /usr/bin/python3 -B report.py export
} always {
  zsystem flock -u $lock_fd
  [[ -f "$AFM_HARNESS_WORK/status.json" ]] && cat "$AFM_HARNESS_WORK/status.json"
}
