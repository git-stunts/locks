# ---------------------------------------------------------------- with

sem_acquire_with_wait() { # wait-seconds errfile -> 0 acquired (ACQUIRED_LINE set)
  local wait="$1" errfile="$2" out rc clock deadline previous
  system_now_v clock || return 2 # waiting uses real wall time, independent of the lease-clock override
  time_sum_v deadline "${clock}" "${wait}" || {
    path_error "--wait exceeds the available deadline range ($((INTEGER_MAX - clock)) seconds at this clock)"
    return 2
  }
  previous="${clock}"
  while :; do
    SNAP_LOADED=0 # each attempt reads afresh; a subshell cannot invalidate for us
    out="$(sem_acquire_once "${W_SEM}" "${W_JOB}" "${W_HOLDER}" "${W_TTL}" 2>"${errfile}")"
    rc=$?
    if ((rc == 0)); then
      ACQUIRED_LINE="${out}"
      return 0
    fi
    if ((rc != 1)); then
      cat "${errfile}" >&2
      return "${rc}"
    fi
    system_now_v clock || return 2
    if ((clock < previous)); then
      clock_error 'system clock moved backwards while waiting'
      return 2
    fi
    previous="${clock}"
    if ((clock >= deadline)); then
      cat "${errfile}" >&2
      return "${rc}"
    fi
    sleep 1
  done
}

cmd_with() {
  W_JOB=''
  W_HOLDER=''
  W_TTL="${DEFAULT_TTL}"
  W_PARENT=''
  W_SEM=''
  W_NOTE=''
  W_PATHS=()
  local wait=0 command=() seen_dashdash=0 a
  while (($# > 0)); do
    a="$1"
    if ((seen_dashdash)); then
      command+=("${a}")
      shift
      continue
    fi
    case "${a}" in
      --job)
        [[ $# -ge 2 ]] || usage
        W_JOB="$2"
        shift 2
        ;;
      --holder)
        [[ $# -ge 2 ]] || usage
        W_HOLDER="$2"
        shift 2
        ;;
      --ttl)
        [[ $# -ge 2 ]] || usage
        W_TTL="$2"
        shift 2
        ;;
      --wait)
        [[ $# -ge 2 ]] || usage
        wait="$2"
        shift 2
        ;;
      --parent)
        [[ $# -ge 2 ]] || usage
        W_PARENT="$2"
        shift 2
        ;;
      --sem)
        [[ $# -ge 2 ]] || usage
        W_SEM="$2"
        shift 2
        ;;
      --note)
        [[ $# -ge 2 ]] || usage
        W_NOTE="$2"
        shift 2
        ;;
      --)
        seen_dashdash=1
        shift
        ;;
      -*) usage ;;
      *)
        W_PATHS+=("${a}")
        shift
        ;;
    esac
  done
  [[ -n "${W_JOB}" && -n "${W_HOLDER}" ]] || usage
  ((${#command[@]} > 0)) || usage
  [[ -n "${W_SEM}" || ${#W_PATHS[@]} -gt 0 ]] || usage
  decimal_uint wait "${wait}" || fail '--wait is a decimal integer from 0 through 9223372036854775807 seconds' 2
  # Validate everything before acquiring anything: the semaphore path does not pass through claim_args or cmd_sem.
  valid_job "${W_JOB}" || fail "job id '${W_JOB}' must match [A-Za-z0-9][A-Za-z0-9._-]*" 2
  valid_holder "${W_HOLDER}" || fail 'holder must be one line' 2
  valid_ttl W_TTL "${W_TTL}" || fail '--ttl is a positive number of seconds' 2
  valid_note "${W_NOTE}" || fail '--note must be one line' 2
  [[ -z "${W_SEM}" ]] || valid_job "${W_SEM}" || fail "semaphore name '${W_SEM}' must match [A-Za-z0-9][A-Za-z0-9._-]*" 2
  [[ -z "${W_PARENT}" ]] || valid_job "${W_PARENT}" || fail "parent id '${W_PARENT}' must match [A-Za-z0-9][A-Za-z0-9._-]*" 2

  local work result rc verify_rc status=0 input_fd error_fd supervisor_body report_lost=1
  work="$(mktemp -d "${TMPDIR:-/tmp}/git-locks-with.XXXXXXXX" 2>&1)" || store_write_error "cannot prepare wrapper scratch space: ${work}"
  W_ACQUISITION=''
  W_CHILD=''
  W_SUPERVISOR=''
  W_SIGNAL=0
  W_COMMAND_STATUS=null
  W_ADMITTED=0
  new_acquisition W_ACQUISITION
  trap 'with_signal INT 130' INT
  trap 'with_signal TERM 143' TERM
  trap 'with_suspend' TSTP

  with_wait "${wait}" "${work}/error"
  rc=$?
  if ((rc == 0)); then
    W_ADMITTED=1
    printf '%s\n' "${ACQUIRED_LINE}" >&2
  elif ((W_SIGNAL)); then
    # A group signal can kill Git after it commits but before its receipt.
    # Cleanup uses our preallocated identity even when admission is uncertain.
    W_ADMITTED=1
    report_lost=0
    status="${W_SIGNAL}"
  else
    status="${rc}"
  fi
  if ((W_ADMITTED && W_SIGNAL == 0)); then
    result="$(with_verify 2>&1)"
    verify_rc=$?
    if ((verify_rc != 0)); then
      printf '%s\n' "${result}" >&2
      ((verify_rc == 1)) || with_failed verification
      status=125
      report_lost=0
    else
      # A short-lived supervisor gives the command the terminal through fg.
      # The parent uses interruptible wait so it can forward TERM/INT promptly.
      exec {input_fd}<&0
      exec {error_fd}>&2
      set +m
      supervisor_body="$(declare -f with_supervise)"
      (
        # Reset the asynchronous shell's INT disposition before exec. Sharing
        # the caller's group lets fg restore the terminal to that same group.
        trap - INT TERM TSTP
        exec env BASH_ENV=/dev/null "${BASH}" --noprofile --norc -c "${supervisor_body}; with_supervise \"\$@\"" \
          git-locks-supervisor "$$" "${work}" "${input_fd}" "${error_fd}" "${command[@]}" 2>/dev/null
      ) &
      W_SUPERVISOR=$!
      exec {input_fd}<&-
      exec {error_fd}>&-
      while [[ ! -s "${work}/pid" ]] && kill -0 "${W_SUPERVISOR}" 2>/dev/null; do sleep 0.01; done
      if [[ -s "${work}/pid" ]]; then
        read -r W_CHILD <"${work}/pid"
      else
        : >"${work}/failure"
      fi
      if ((W_SIGNAL == 0)); then
        : >"${work}/run"
        while :; do
          status=0
          wait "${W_SUPERVISOR}" 2>/dev/null || status=$?
          ((W_SIGNAL == 0)) || break
          kill -0 "${W_SUPERVISOR}" 2>/dev/null || break
        done
      fi
      with_stop_child
      if [[ -s "${work}/status" ]]; then
        # Bash may abort fg with status 1 for an interrupted foreground job.
        # The command shell's EXIT receipt preserves the command's real status.
        read -r status <"${work}/status"
      fi
      if [[ -e "${work}/failure" ]]; then
        with_failed launch
        status=125
      else
        W_COMMAND_STATUS="${status}"
      fi
      ((W_SIGNAL == 0)) || status="${W_SIGNAL}"
    fi
  fi
  if ((W_ADMITTED)); then
    result="$(with_cleanup "${report_lost}" 2>&1)"
    rc=$?
    [[ -z "${result}" ]] || printf '%s\n' "${result}" >&2
    if ((rc != 0)); then
      ((rc == 125)) || with_failed cleanup
      status=125
    fi
  fi
  ((W_SIGNAL == 0)) || status="${W_SIGNAL}"
  trap - INT TERM TSTP
  rm -rf -- "${work}"
  return "${status}"
}

with_supervise() { # wrapper-pid work input-fd error-fd command...; fresh Bash
  local parent_pid="$1" work="$2" input_fd="$3" error_fd="$4"
  shift 4
  exec 2>&"${error_fd}"
  exec {error_fd}>&-
  local command=("$@")
  trap : INT TERM
  trap - TSTP
  # Keep Bash's initial terminal-group cache empty until the first foreground
  # handoff. A wrapper started in the background may be foregrounded later.
  set -m 2>/dev/null
  # Expand arguments in the fresh command shell, after the parent's gate.
  # shellcheck disable=SC2016
  BASH_ENV=/dev/null "${BASH}" --noprofile --norc -c '
    input_fd="$1"
    work="$2"
    shift 2
    exec {input_fd}<&-
    trap '\''result=$?; printf "%s\n" "${result}" >"${work}/status"'\'' EXIT
    trap '\''exit 130'\'' INT
    trap '\''exit 143'\'' TERM
    kill -STOP "${BASHPID}"
    while [[ ! -e "${work}/run" ]]; do sleep 0.01; done
    exec {command_error}>&2
    { "$@" 2>&"${command_error}" {command_error}>&-; } 2>/dev/null
  ' git-locks-command "${input_fd}" "${work}" "${command[@]}" <&"${input_fd}" &
  local command_pid=$!
  exec {input_fd}<&-
  # The command cannot finish before fg: only foregrounding resumes this stop.
  wait "${command_pid}" 2>/dev/null || true
  printf '%s\n' "${command_pid}" >"${work}/pid"
  trap 'exit 130' INT
  trap 'exit 143' TERM
  local terminal_fd=2
  # Bash uses stderr as its terminal descriptor in a noninteractive shell.
  # Keep that descriptor attached to the controlling terminal for fg, even
  # when the caller redirected stderr. Only the supervisor ignores TTOU.
  trap '' TTOU
  { exec {terminal_fd}<>/dev/tty; } 2>/dev/null || exec {terminal_fd}>/dev/null
  # Bash breaks enclosing loops when a foreground job stops. Keep fg outside
  # a loop, and re-enter after the caller resumes this invocation.
  with_foreground() {
    local command_status=0 groups caller_group foreground_group
    groups="$(ps -o pgid= -o tpgid= -p "${parent_pid}" 2>/dev/null)" || {
      : >"${work}/failure"
      return 125
    }
    read -r caller_group foreground_group <<<"${groups}"
    if [[ ! "${caller_group}" =~ ^[0-9]+$ || ! "${foreground_group}" =~ ^-?[0-9]+$ ]]; then
      : >"${work}/failure"
      return 125
    fi
    if [[ "${caller_group}" == "${foreground_group}" ]]; then
      set -m 2>&"${terminal_fd}"
      fg %+ >/dev/null 2>&"${terminal_fd}" || command_status=$?
    else
      bg %+ >/dev/null 2>&1
      wait "${command_pid}" 2>/dev/null || command_status=$?
    fi
    jobs -ps >"${work}/stopped"
    if [[ ! -s "${work}/stopped" ]]; then
      return "${command_status}"
    fi
    kill -TSTP "${parent_pid}"
    while [[ ! -e "${work}/continue" ]]; do sleep 0.01; done
    rm -f -- "${work}/continue"
    with_foreground
  }
  with_foreground
}

with_active_refusal() { # [semaphore] -> this job is already owned by a live invocation
  local _j1 _j2 extra=''
  json_str _j1 "${W_JOB}"
  if [[ -n "${1:-}" ]]; then
    json_str _j2 "$1"
    extra=",\"semaphore\":${_j2}"
  fi
  printf '{"event":"refused","reason":"active","job":%s%s}\n' "${_j1}" "${extra}" >&2
  return 1
}

with_acquire_once() { # one root publication owns every requested resource
  local attempt ref oid at
  for ((attempt = 0; attempt < RETRIES; attempt++)); do
    snapshot
    claim_reset
    now_v at
    if ((${#W_PATHS[@]})); then
      ref="$(job_ref "${W_JOB}")"
      oid="${REF_OID[${ref}]:-}"
      if [[ -n "${oid}" ]] && record_live "${oid}" "${at}"; then
        with_active_refusal
        return 1
      fi
    fi
    if [[ -n "${W_SEM}" ]]; then
      ref="$(sem_slot_ref "${W_SEM}" "${W_JOB}")"
      oid="${REF_OID[${ref}]:-}"
      if [[ -n "${oid}" ]] && record_live "${oid}" "${at}"; then
        with_active_refusal "${W_SEM}"
        return 1
      fi
    fi
    if ((${#W_PATHS[@]})); then
      plan_claim "${W_JOB}" "${W_HOLDER}" "${W_TTL}" "${W_PARENT}" "${W_NOTE}" "${W_ACQUISITION}" "${W_PATHS[@]}"
      ((CONFLICTS == 0)) || return 1
    fi
    if [[ -n "${W_SEM}" ]]; then
      plan_sem_acquire "${W_SEM}" "${W_JOB}" "${W_HOLDER}" "${W_TTL}" "${W_ACQUISITION}" || return 1
    fi
    if transact; then
      [[ -z "${W_SEM}" ]] || printf '%s\n' "${SEM_ACQUIRED_LINE}"
      ((${#W_PATHS[@]} == 0)) || printf '%s\n' "${CLAIM_LINE}"
      return 0
    fi
    sleep 0.01
  done
  transaction_refusal
  return 1
}

with_wait() { # wait-seconds errfile -> complete admission or refusal, never a partial slot
  local clock deadline previous out rc
  system_now_v clock || return 2
  time_sum_v deadline "${clock}" "$1" || {
    path_error "--wait exceeds the available deadline range ($((INTEGER_MAX - clock)) seconds at this clock)"
    return 2
  }
  previous="${clock}"
  while ((W_SIGNAL == 0)); do
    out="$(with_acquire_once 2>"$2")"
    rc=$?
    if ((rc == 0)); then
      ACQUIRED_LINE="${out}"
      return 0
    fi
    ((W_SIGNAL == 0)) || return "${W_SIGNAL}"
    if ((rc != 1)); then
      cat "$2" >&2
      return "${rc}"
    fi
    system_now_v clock || return 2
    if ((clock < previous)); then
      clock_error 'system clock moved backwards while waiting'
      return 2
    fi
    previous="${clock}"
    if ((clock >= deadline)); then
      cat "$2" >&2
      return "${rc}"
    fi
    sleep 1
  done
  return "${W_SIGNAL}"
}

with_reason() { # ref -> W_OWN_OID, W_REASON for this invocation's acquisition
  W_OWN_OID="${REF_OID[$1]:-}"
  W_REASON=''
  local acquired at
  if [[ -z "${W_OWN_OID}" ]]; then
    W_REASON=missing
    return 0
  fi
  field_v acquired "${W_OWN_OID}" acquisition
  if [[ "${acquired}" != "${W_ACQUISITION}" ]]; then
    W_REASON=superseded
    return 0
  fi
  now_v at
  record_live "${W_OWN_OID}" "${at}" || W_REASON=expired
  return 0
}

with_lost_line() { # reason [semaphore]
  local _j1 _j2 _j3 extra=''
  json_str _j1 "${W_JOB}"
  json_str _j2 "${W_ACQUISITION}"
  if [[ -n "${2:-}" ]]; then
    json_str _j3 "$2"
    extra=",\"semaphore\":${_j3}"
  fi
  printf '{"event":"lost","reason":"%s","job":%s,"acquisition":%s,"command_status":%s%s}\n' \
    "$1" "${_j1}" "${_j2}" "${W_COMMAND_STATUS}" "${extra}"
}

with_failed() { # cleanup|verification|launch -> lifecycle failed independently of command status
  local _j1
  json_str _j1 "${W_JOB}"
  printf '{"event":"with-failed","reason":"%s","job":%s,"command_status":%s}\n' "$1" "${_j1}" "${W_COMMAND_STATUS}" >&2
}

with_verify() { # check ownership and liveness once more before launching the command
  local ref lost=0
  snapshot
  if ((${#W_PATHS[@]})); then
    ref="$(job_ref "${W_JOB}")"
    with_reason "${ref}"
    if [[ -n "${W_REASON}" ]]; then
      with_lost_line "${W_REASON}"
      lost=1
    fi
  fi
  if [[ -n "${W_SEM}" ]]; then
    ref="$(sem_slot_ref "${W_SEM}" "${W_JOB}")"
    with_reason "${ref}"
    if [[ -n "${W_REASON}" ]]; then
      with_lost_line "${W_REASON}" "${W_SEM}"
      lost=1
    fi
  fi
  return "${lost}"
}

with_cleanup() { # report-lost (0/1) -> one guarded release of all still-owned resources
  local attempt ref lost line _j1 _j2 live_after i
  local lines=() losses=()
  json_str _j1 "${W_JOB}"
  for ((attempt = 0; attempt < RETRIES; attempt++)); do
    snapshot
    plan_reset
    lines=()
    losses=()
    lost=0
    if ((${#W_PATHS[@]})); then
      ref="$(job_ref "${W_JOB}")"
      with_reason "${ref}"
      if [[ -n "${W_REASON}" ]]; then
        lost=1
        losses+=("$(with_lost_line "${W_REASON}")")
      fi
      if [[ -z "${W_REASON}" || "${W_REASON}" == expired ]]; then
        plan_terminate "${W_JOB}" || fail "${PLAN_CONFLICT}" 1
        line="{\"event\":\"released\",\"job\":${_j1},\"paths\":${TERMINATED_PATHS}"
        [[ "${TERMINATED_CASCADE}" == '[]' ]] || line+=",\"cascaded\":${TERMINATED_CASCADE}"
        lines+=("${line}}")
      fi
    fi
    if [[ -n "${W_SEM}" ]]; then
      ref="$(sem_slot_ref "${W_SEM}" "${W_JOB}")"
      with_reason "${ref}"
      if [[ -n "${W_REASON}" ]]; then
        lost=1
        losses+=("$(with_lost_line "${W_REASON}" "${W_SEM}")")
      fi
      if [[ -z "${W_REASON}" || "${W_REASON}" == expired ]]; then
        sem_read "${W_SEM}" || sem_missing "${W_SEM}"
        live_after="${SEM_LIVE}"
        for i in "${!SLOT_JOBS[@]}"; do
          if [[ "${SLOT_JOBS[${i}]}" == "${W_JOB}" ]] && ((SLOT_LIVE[i])); then
            live_after=$((live_after - 1))
          fi
        done
        plan_set "${ref}" "${W_OWN_OID}" '' || fail "${PLAN_CONFLICT}" 1
        sem_plan_generation "${W_SEM}"
        json_str _j2 "${W_SEM}"
        lines+=("{\"event\":\"released\",\"semaphore\":${_j2},\"job\":${_j1},\"live\":${live_after},\"capacity\":${SEM_CAP}}")
      fi
    fi
    if ((${#PLAN_ORDER[@]} > 0)) && ! transact; then
      sleep 0.01
      continue
    fi
    ((${#lines[@]} == 0)) || printf '%s\n' "${lines[@]}"
    if ((lost)); then
      (($1 == 0)) || printf '%s\n' "${losses[@]}"
      return 125
    fi
    return 0
  done
  transaction_refusal
  return 1
}

with_suspend() { # keep ownership while the foreground command is stopped
  if ((W_SIGNAL == 0)); then
    [[ -z "${W_CHILD}" ]] || kill -STOP -- "-${W_CHILD}" 2>/dev/null || true
    kill -STOP "$$"
  fi
  # Execution resumes here after the caller foregrounds/continues the wrapper.
  : >"${work}/continue"
}

with_signal() { # signal exit-status: defer cleanup until any active Git publication finishes
  W_SIGNAL="$2"
  [[ -z "${W_CHILD}" ]] || kill -s "$1" -- "-${W_CHILD}" 2>/dev/null || true
}

with_stop_child() { # TERM/INT already forwarded; allow two seconds, then stop the whole group
  local attempt
  [[ -n "${W_CHILD}" ]] || return 0
  # Covers a signal arriving between the background fork and PID registration.
  if ((W_SIGNAL == 130)); then
    kill -INT -- "-${W_CHILD}" 2>/dev/null || true
  else
    kill -TERM -- "-${W_CHILD}" 2>/dev/null || true
  fi
  # A stopped command must continue to receive a pending terminating signal.
  : >"${work}/continue"
  kill -CONT -- "-${W_CHILD}" 2>/dev/null || true
  for ((attempt = 0; attempt < 100; attempt++)); do
    kill -0 -- "-${W_CHILD}" 2>/dev/null || break
    sleep 0.02
  done
  kill -KILL -- "-${W_CHILD}" 2>/dev/null || true
  wait "${W_SUPERVISOR}" 2>/dev/null || true
  W_CHILD=''
  W_SUPERVISOR=''
}
