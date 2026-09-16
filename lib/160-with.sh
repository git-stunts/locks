# ---------------------------------------------------------------- with

acquire_with_wait() { # kind(lock|sem) wait-seconds errfile -> 0 acquired (ACQUIRED_LINE set), else exits with the refusal
  local kind="$1" wait="$2" errfile="$3" out rc clock deadline
  clock="$(date +%s)" # the wait window is wall-clock time, whatever GIT_LOCKS_NOW says about lock expiry
  deadline=$((clock + wait))
  while :; do
    SNAP_LOADED=0 # each attempt reads afresh; a subshell cannot invalidate for us
    if [[ "${kind}" == sem ]]; then
      out="$( (sem_acquire_once "${W_SEM}" "${W_JOB}" "${W_HOLDER}" "${W_TTL}") 2>"${errfile}")"
    elif [[ -n "${W_PARENT}" ]]; then
      out="$( (cmd_claim --job "${W_JOB}" --holder "${W_HOLDER}" --ttl "${W_TTL}" --parent "${W_PARENT}" --note "${W_NOTE}" -- "${W_PATHS[@]}") 2>"${errfile}")"
    else
      out="$( (cmd_claim --job "${W_JOB}" --holder "${W_HOLDER}" --ttl "${W_TTL}" --note "${W_NOTE}" -- "${W_PATHS[@]}") 2>"${errfile}")"
    fi
    rc=$?
    if ((rc == 0)); then
      ACQUIRED_LINE="${out}"
      return 0
    fi
    clock="$(date +%s)"
    if ((rc != 1 || clock >= deadline)); then
      cat "${errfile}" >&2
      return "${rc}"
    fi
    sleep 1
  done
}

record_of() { # VAR json-line -> the "acquisition" field, the identity that survives renewals
  local line="$2" rec=''
  [[ "${line}" =~ \"acquisition\":\"([^\"]+)\" ]] && rec="${BASH_REMATCH[1]}"
  printf -v "$1" '%s' "${rec}"
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
  [[ "${wait}" =~ ^[0-9]+$ ]] || fail '--wait is a number of seconds' 2
  # Validate everything before acquiring anything: the semaphore path does not pass through claim_args or cmd_sem.
  valid_job "${W_JOB}" || fail "job id '${W_JOB}' must match [A-Za-z0-9][A-Za-z0-9._-]*" 2
  valid_holder "${W_HOLDER}" || fail 'holder must be one line' 2
  valid_ttl W_TTL "${W_TTL}" || fail '--ttl is a positive number of seconds' 2
  valid_note "${W_NOTE}" || fail '--note must be one line' 2
  [[ -z "${W_SEM}" ]] || valid_job "${W_SEM}" || fail "semaphore name '${W_SEM}' must match [A-Za-z0-9][A-Za-z0-9._-]*" 2
  [[ -z "${W_PARENT}" ]] || valid_job "${W_PARENT}" || fail "parent id '${W_PARENT}' must match [A-Za-z0-9][A-Za-z0-9._-]*" 2

  local errfile sem_record='' lock_record='' rc
  errfile="$(mktemp "${TMPDIR:-/tmp}/git-locks-with.XXXXXX")" || fail 'cannot create a temporary file'

  # Release exactly the acquisitions this invocation made, never whatever wears the job name now. Armed before the
  # first acquisition: a signal while waiting for the lock must give back the slot already taken.
  local status=0
  with_release_all() {
    if [[ -n "${lock_record}" ]]; then
      SNAP_LOADED=0
      (cmd_release --job "${W_JOB}" --acquisition "${lock_record}") >&2
    fi
    if [[ -n "${sem_record}" ]]; then
      with_release_sem "${sem_record}"
    fi
    rm -f "${errfile}"
    return 0
  }
  trap 'with_release_all; exit 130' INT
  trap 'with_release_all; exit 143' TERM
  if [[ -n "${W_SEM}" ]]; then
    acquire_with_wait sem "${wait}" "${errfile}"
    rc=$?
    ((rc == 0)) || {
      rm -f "${errfile}"
      exit "${rc}"
    }
    record_of sem_record "${ACQUIRED_LINE}"
    printf '%s\n' "${ACQUIRED_LINE}" >&2
  fi
  if ((${#W_PATHS[@]} > 0)); then
    acquire_with_wait lock "${wait}" "${errfile}"
    rc=$?
    ((rc == 0)) || {
      rm -f "${errfile}"
      [[ -n "${sem_record}" ]] && with_release_sem "${sem_record}"
      exit "${rc}"
    }
    record_of lock_record "${ACQUIRED_LINE}"
    printf '%s\n' "${ACQUIRED_LINE}" >&2
  fi
  rm -f "${errfile}"

  "${command[@]}" || status=$?
  trap - INT TERM
  with_release_all
  return "${status}"
}

with_release_sem() { # record -> releases this invocation's slot, if it is still the current one
  SNAP_LOADED=0
  (sem_release_once "${W_SEM}" "${W_JOB}" "$1") >&2
}
