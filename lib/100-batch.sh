# ---------------------------------------------------------------- batch

B_JOB=()
B_HOLDER=()
B_TTL=()
B_PARENT=()
B_NOTE=()
B_PATHS=() # newline joined
B_LINES=()

plan_batch() { # plans every parsed record against the current snapshot; B_LINES collects the claim lines
  local i paths p list
  B_LINES=()
  for i in "${!B_JOB[@]}"; do
    list=()
    paths="${B_PATHS[${i}]}"
    while [[ -n "${paths}" ]]; do
      p="${paths%%$'\n'*}"
      if [[ "${p}" == "${paths}" ]]; then paths=''; else paths="${paths#*$'\n'}"; fi
      [[ -n "${p}" ]] && list+=("${p}")
    done
    plan_claim "${B_JOB[${i}]}" "${B_HOLDER[${i}]}" "${B_TTL[${i}]}" "${B_PARENT[${i}]}" "${B_NOTE[${i}]}" '' "${list[@]}"
    B_LINES+=("${CLAIM_LINE}")
  done
}

cmd_batch() {
  (($# == 0)) || usage
  local input rc temporary read_error='' error_read='' error_write='' error_rc
  # Read stdin in this shell: a command-substitution reader could survive a
  # signal sent only to the CLI PID. Keep diagnostics in an anonymous file,
  # with independent read/write offsets, and unlink it before waiting on input.
  temporary="$(mktemp "${TMPDIR:-/tmp}/git-locks-read.XXXXXXXX" 2>&1)" || fail "batch: cannot prepare input diagnostics: ${temporary}" 2
  # The new file is empty; sharing its bytes with separate offsets is intentional.
  # shellcheck disable=SC2094
  if ! { exec {error_write}>"${temporary}" {error_read}<"${temporary}"; } 2>/dev/null; then
    [[ -z "${error_read}" ]] || exec {error_read}<&-
    [[ -z "${error_write}" ]] || exec {error_write}>&-
    rm -f -- "${temporary}" 2>/dev/null
    fail 'batch: cannot open input diagnostics' 2
  fi
  if ! rm -f -- "${temporary}" 2>/dev/null; then
    exec {error_read}<&- {error_write}>&-
    fail 'batch: cannot unlink input diagnostics' 2
  fi
  IFS= read -r -d '' input 2>&"${error_write}"
  rc=$?
  IFS= read -r -d '' read_error <&"${error_read}" 2>/dev/null
  error_rc=$?
  exec {error_read}<&- {error_write}>&-
  ((error_rc == 1)) || fail 'batch: cannot read input diagnostics' 2
  [[ -z "${read_error}" ]] || fail "batch: cannot read stdin: ${read_error}" 2
  ((rc != 0)) || fail 'batch: input contains a NUL byte' 2
  ((rc == 1)) || fail "batch: cannot read stdin (status ${rc})" 2
  local line key val job='' holder='' ttl='' parent='' note='' paths=() in_paths=0 count=0
  finish_record() {
    if [[ -z "${job}" && -z "${holder}" && -z "${ttl}" && -z "${parent}" && -z "${note}" && ${#paths[@]} -eq 0 ]]; then return 0; fi # only a wholly empty record is skipped; one with just parent: or ttl: is malformed
    [[ -n "${job}" && -n "${holder}" && ${#paths[@]} -gt 0 ]] || fail 'batch: every record needs job:, holder: and at least one path under paths:' 2
    valid_job "${job}" || fail "batch: job id '${job}' must match [A-Za-z0-9][A-Za-z0-9._-]*" 2
    [[ -z "${ttl}" ]] && ttl="${DEFAULT_TTL}"
    valid_ttl ttl "${ttl}" || fail 'batch: ttl is a positive number of seconds' 2
    valid_holder "${holder}" || fail 'batch: holder must be one valid UTF-8 line' 2
    valid_note "${note}" || fail 'batch: note must be one valid UTF-8 line' 2
    B_JOB+=("${job}")
    B_HOLDER+=("${holder}")
    B_TTL+=("${ttl}")
    B_PARENT+=("${parent}")
    B_NOTE+=("${note}")
    local joined
    joined="$(printf '%s\n' "${paths[@]}")"
    B_PATHS+=("${joined}")
    count=$((count + 1))
    job=''
    holder=''
    ttl=''
    parent=''
    note=''
    paths=()
    in_paths=0
  }
  while IFS= read -r line || [[ -n "${line}" ]]; do
    valid_utf8 "${line}" || fail 'batch: input must be valid UTF-8' 2
    if [[ -z "${line}" ]]; then
      finish_record
      continue
    fi
    if ((in_paths)); then
      paths+=("${line}")
      continue
    fi
    key="${line%%:*}"
    val="${line#*:}"
    val="${val# }"
    case "${key}" in
      job) job="${val}" ;;
      holder) holder="${val}" ;;
      ttl) ttl="${val}" ;;
      parent) parent="${val}" ;;
      note) note="${val}" ;;
      paths) in_paths=1 ;;
      *) fail "batch: unknown line '${line}'" 2 ;;
    esac
  done <<<"${input}"
  finish_record
  ((count > 0)) || fail 'batch: no records on stdin' 2
  commit_claims plan_batch
  printf '%s\n' "${B_LINES[@]}"
}
