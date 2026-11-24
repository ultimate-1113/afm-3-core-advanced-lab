# Run from the interactive Apple Terminal that displays both models.
# The shell calls only Apple's documented fm commands on frozen synthetic inputs.
() {
  emulate -L zsh
  unsetopt errexit nounset
  local here=${1:A:h}
  shift
  local py=/usr/bin/python3 studywork="${AFM_STUDY_WORK:-$here/build/session}"
  local part="$studywork/terminal" statusfile="$studywork/status.json"
  mkdir -p "$part" || return 1
  if [[ "${1:-}" == --check ]]; then
    "$py" -B "$here/test_study.py"
    return $?
  fi
  zmodload zsh/datetime || return 1
  zmodload zsh/system || return 1
  local fdlock
  : >> "$part/exclusive.lock"
  zsystem flock -t 0 -f fdlock "$part/exclusive.lock" || { print 'Another Terminal run is active.'; return 1; }
  {
    # Preserve the user's ordinary foreground Terminal context. No configuration changes.
    /usr/bin/fm models > "$part/models" || true
    "$py" -B "$here/terminal_run.py" init || return $?
    local -a queue ids flags
    local line id method idx rc before after start end fresult
    queue=("${(@f)$(<"$part/sequence")}")
    for line in "${queue[@]}"; do
      ids=("${(@s: :)line}"); id=$ids[1]; method=$ids[2]; idx=$ids[3]
      "$py" -B "$here/terminal_run.py" prepare "$id" "$method" "$idx"
      rc=$?
      (( rc == 3 )) && continue
      (( rc == 0 )) || return $rc
      /usr/bin/fm quota-usage --model pcc > "$part/quota-before" 2>&1
      before=$?
      "$py" -B "$here/terminal_run.py" before "$before" || return $?
      flags=(respond --model pcc --greedy --stream --instructions "$(<"$part/instructions")" --save-transcript "$part/transcript.json")
      [[ -s "$part/schema" ]] && flags+=(--schema "$(<"$part/schema")")
      [[ -s "$part/image" ]] && flags+=(--image "$(<"$part/image")")
      flags+=(--text "$(<"$part/prompt")")
      print "PCC  $id  $method  $((idx + 1))"
      start=$EPOCHREALTIME
      /usr/bin/fm "${flags[@]}" 2> "$part/stderr" | "$py" -B "$here/terminal_run.py" capture
      fresult=$pipestatus[1];end=$EPOCHREALTIME
      /usr/bin/fm quota-usage --model pcc > "$part/quota-after" 2>&1
      after=$?
      "$py" -B "$here/terminal_run.py" after "$fresult" "$start" "$end" "$after" || return $?
    done
    "$py" -B "$here/terminal_run.py" end && print 'PCC evaluation finished.'
  } always {
    zsystem flock -u $fdlock
    [[ -f "$statusfile" ]] && cat "$statusfile"
  }
} "${(%):-%x}" "$@"
