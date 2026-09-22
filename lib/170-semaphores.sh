# ---------------------------------------------------------------- semaphores
#
# refs/locks/sem/<name>/meta holds the capacity; slots/<job> one record per
# holder; gen a token every transaction on the semaphore rewrites, so two
# acquirers who both counted "n of N live" contend on one compare-and-swap and
# exactly one commits. The other re-reads.

valid_capacity() { # VAR value: canonical positive decimal in Bash's signed 64-bit arithmetic range
  [[ "$2" =~ ^[0-9]+$ ]] || return 1
  local _capacity="${2#"${2%%[!0]*}"}" # strip leading zeros without evaluating input as arithmetic
  [[ -n "${_capacity}" ]] || return 1
  ((${#_capacity} <= 19)) || return 1
  # Compare equal-length decimal strings: arithmetic would overflow before rejecting the input.
  # shellcheck disable=SC2071
  if ((${#_capacity} == 19)) && [[ "${_capacity}" > 9223372036854775807 ]]; then
    return 1
  fi
  printf -v "$1" '%s' "${_capacity}"
}

sem_meta_ref() { printf '%s/sem/%s/meta' "${NS}" "$1"; }
sem_gen_ref() { printf '%s/sem/%s/gen' "${NS}" "$1"; }
sem_slot_ref() { printf '%s/sem/%s/slots/%s' "${NS}" "$1" "$2"; }

sem_missing() { # name -> stderr line, exit 1
  local _j1
  json_str _j1 "$1"
  printf '{"event":"missing","semaphore":%s}\n' "${_j1}" >&2
  exit 1
}

sem_refusal() { # name reason [capacity live]
  local _j1
  json_str _j1 "$1"
  case "$2" in
    capacity) printf '{"event":"refused","reason":"capacity","semaphore":%s,"capacity":%s,"live":%s}\n' "${_j1}" "$3" "$4" >&2 ;;
    exists) printf '{"event":"refused","reason":"exists","semaphore":%s}\n' "${_j1}" >&2 ;;
    live) printf '{"event":"refused","reason":"live","semaphore":%s,"live":%s}\n' "${_j1}" "$4" >&2 ;;
    *) transaction_refusal ;;
  esac
}

gen_blob() { # VAR: a fresh generation token as a blob
  local at content
  now_v at
  content="$(printf 'generation %s %s %s' "${at}" "$$" "${RANDOM}${RANDOM}")"
  write_blob "$1" "${content}"
}

# Reads a semaphore into: SEM_CAP, SEM_META_OID, SEM_GEN_OID, SEM_LIVE, and parallel arrays
# SLOT_JOBS SLOT_OIDS SLOT_LIVE (1/0) SLOT_HOLDER SLOT_CLAIMED SLOT_EXPIRES SLOT_REMAINING.
sem_read() {      # name -> 0, or 1 when the semaphore does not exist
  ensure_snapshot # in this shell, so the $(…) reads below inherit one fresh snapshot instead of each taking their own
  local name="$1" mref gref rows ref oid at exp claimed
  mref="$(sem_meta_ref "${name}")"
  SEM_META_OID="$(ref_oid "${mref}")"
  [[ -n "${SEM_META_OID}" ]] || return 1
  SEM_CAP="$(field "${SEM_META_OID}" capacity)"
  valid_capacity SEM_CAP "${SEM_CAP}" || store_error "semaphore ${name} has an invalid capacity"
  gref="$(sem_gen_ref "${name}")"
  SEM_GEN_OID="$(ref_oid "${gref}")"
  SLOT_JOBS=()
  SLOT_OIDS=()
  SLOT_LIVE=()
  SLOT_HOLDER=()
  SLOT_CLAIMED=()
  SLOT_EXPIRES=()
  SLOT_REMAINING=()
  SEM_LIVE=0
  now_v at
  rows="$(refs_under "${NS}/sem/${name}/slots/")"
  while IFS=' ' read -r ref oid; do
    [[ -z "${ref}" ]] && continue
    SLOT_JOBS+=("$(field "${oid}" job)")
    SLOT_OIDS+=("${oid}")
    SLOT_HOLDER+=("$(field "${oid}" holder)")
    claimed="$(field "${oid}" claimed)"
    SLOT_CLAIMED+=("${claimed:-0}")
    exp="$(field "${oid}" expires)"
    exp="${exp:-0}"
    SLOT_EXPIRES+=("${exp}")
    if ((exp > at)); then
      SLOT_LIVE+=(1)
      SLOT_REMAINING+=("$((exp - at))")
      SEM_LIVE=$((SEM_LIVE + 1))
    else
      SLOT_LIVE+=(0)
      SLOT_REMAINING+=(0)
    fi
  done <<<"${rows}"
  return 0
}

sem_plan_evict_expired() { # name [keep-job] -> plans deletes for expired slots, except keep-job's
  local i sref
  for i in "${!SLOT_JOBS[@]}"; do
    ((SLOT_LIVE[i])) && continue
    [[ "${SLOT_JOBS[${i}]}" == "${2:-}" ]] && continue
    sref="$(sem_slot_ref "$1" "${SLOT_JOBS[${i}]}")"
    plan_set "${sref}" "${SLOT_OIDS[${i}]}" '' || return 1
  done
}

sem_transact() { # name -> plans the generation CAS and the meta verify, then commits; 0 ok, 2 lost the race
  local gref newgen mref
  gref="$(sem_gen_ref "$1")"
  mref="$(sem_meta_ref "$1")"
  gen_blob newgen || fail 'could not write the generation token'
  plan_set "${gref}" "${SEM_GEN_OID}" "${newgen}" || fail "${PLAN_CONFLICT}" 1
  plan_set "${mref}" "${SEM_META_OID}" '=' || fail "${PLAN_CONFLICT}" 1
  transact && return 0
  return 2
}

sem_show_line() { # name, after sem_read -> one JSON line or the text block
  local i _j1 _j2 _j3 _j4 _j5 items=() IFS acq
  for i in "${!SLOT_JOBS[@]}"; do
    ((SLOT_LIVE[i])) || continue
    json_str _j2 "${SLOT_JOBS[${i}]}"
    json_str _j3 "${SLOT_HOLDER[${i}]}"
    json_str _j4 "${SLOT_OIDS[${i}]}"
    acq="$(field "${SLOT_OIDS[${i}]}" acquisition)"
    json_str _j5 "${acq}"
    items+=("{\"job\":${_j2},\"holder\":${_j3},\"claimed\":${SLOT_CLAIMED[${i}]},\"expires\":${SLOT_EXPIRES[${i}]},\"remaining\":${SLOT_REMAINING[${i}]},\"record\":${_j4},\"acquisition\":${_j5}}")
  done
  json_str _j1 "$1"
  IFS=','
  printf '{"semaphore":%s,"capacity":%s,"live":%s,"slots":[%s]}\n' "${_j1}" "${SEM_CAP}" "${SEM_LIVE}" "${items[*]}"
}

sem_acquire_once() { # name job holder ttl -> 0 acquired (line printed), 1 refused, 2 usage/missing
  local attempt rc
  for ((attempt = 0; attempt < RETRIES; attempt++)); do
    snapshot
    sem_acquire_attempt "$1" "$2" "$3" "$4"
    rc=$?
    ((rc == 2)) || return "${rc}"
    sleep 0.01
  done
  transaction_refusal
  return 1
}

sem_acquire_attempt() { # one read-plan-transact; 0 acquired, 1 refused (capacity), 2 lost the race
  ensure_snapshot       # in this shell, so the $(…) reads below inherit one fresh snapshot instead of each taking their own
  local name="$1" job="$2" holder="$3" ttl="$4" i at expires record oid _j1 _j2 _j3 _j4 _j5 own_oid='' own_live=0 slot_ref live_after acq=''
  sem_read "${name}" || sem_missing "${name}"
  for i in "${!SLOT_JOBS[@]}"; do
    if [[ "${SLOT_JOBS[${i}]}" == "${job}" ]]; then
      own_oid="${SLOT_OIDS[${i}]}"
      own_live="${SLOT_LIVE[${i}]}"
      ((own_live)) && acq="$(field "${own_oid}" acquisition)" # a refresh keeps the acquisition; a re-acquire after expiry mints one
    fi
  done
  [[ -n "${acq}" ]] || new_acquisition acq
  if ((own_live == 0 && SEM_LIVE >= SEM_CAP)); then
    sem_refusal "${name}" capacity "${SEM_CAP}" "${SEM_LIVE}"
    return 1
  fi
  now_v at
  expires=$((at + ttl))
  record="$(printf 'schema: %s\nsemaphore: %s\njob: %s\nholder: %s\nclaimed: %s\nexpires: %s\nacquisition: %s' "${SLOT_SCHEMA}" "${name}" "${job}" "${holder}" "${at}" "${expires}" "${acq}")"
  write_blob oid "${record}" || fail 'could not write the slot record'
  plan_reset
  sem_plan_evict_expired "${name}" "${job}" || fail "${PLAN_CONFLICT}" 1
  slot_ref="$(sem_slot_ref "${name}" "${job}")"
  if [[ -n "${own_oid}" ]]; then
    plan_set "${slot_ref}" "${own_oid}" "${oid}" || fail "${PLAN_CONFLICT}" 1 # live or expired: one transition, old to new
    if ((own_live)); then live_after="${SEM_LIVE}"; else live_after=$((SEM_LIVE + 1)); fi
  else
    plan_set "${slot_ref}" '' "${oid}" || fail "${PLAN_CONFLICT}" 1
    live_after=$((SEM_LIVE + 1))
  fi
  sem_transact "${name}" || return 2
  json_str _j1 "${name}"
  json_str _j2 "${job}"
  json_str _j3 "${holder}"
  json_str _j4 "${oid}"
  json_str _j5 "${acq}"
  printf '{"event":"acquired","semaphore":%s,"job":%s,"holder":%s,"claimed":%s,"expires":%s,"live":%s,"capacity":%s,"record":%s,"acquisition":%s}\n' \
    "${_j1}" "${_j2}" "${_j3}" "${at}" "${expires}" "${live_after}" "${SEM_CAP}" "${_j4}" "${_j5}"
  return 0
}

sem_release_once() { # name job [record] -> 0 released or nothing to release; 1 only when the race never settles
  local attempt rc
  for ((attempt = 0; attempt < RETRIES; attempt++)); do
    snapshot
    sem_release_attempt "$1" "$2" "${3:-}"
    rc=$?
    ((rc == 2)) || return "${rc}"
    sleep 0.01
  done
  transaction_refusal
  return 1
}

sem_release_attempt() { # one read-plan-transact; 0 done, 2 lost the race
  ensure_snapshot       # in this shell, so the $(…) reads below inherit one fresh snapshot instead of each taking their own
  local name="$1" job="$2" want="$3" i own_oid='' own_live=0 _j1 _j2 live_after slot_ref
  sem_read "${name}" || sem_missing "${name}"
  for i in "${!SLOT_JOBS[@]}"; do
    if [[ "${SLOT_JOBS[${i}]}" == "${job}" ]]; then
      own_oid="${SLOT_OIDS[${i}]}"
      own_live="${SLOT_LIVE[${i}]}"
    fi
  done
  json_str _j1 "${name}"
  json_str _j2 "${job}"
  if [[ -z "${own_oid}" ]]; then
    printf '{"event":"nothing","semaphore":%s,"job":%s}\n' "${_j1}" "${_j2}"
    return 0
  fi
  local own_acq
  own_acq="$(field "${own_oid}" acquisition)"
  if [[ -n "${want}" && "${want}" != "${own_oid}" && "${want}" != "${own_acq}" ]]; then
    printf '{"event":"nothing","semaphore":%s,"job":%s,"reason":"superseded"}\n' "${_j1}" "${_j2}"
    return 0
  fi
  if ((own_live)); then live_after=$((SEM_LIVE - 1)); else live_after="${SEM_LIVE}"; fi
  plan_reset
  sem_plan_evict_expired "${name}" "${job}" || fail "${PLAN_CONFLICT}" 1
  slot_ref="$(sem_slot_ref "${name}" "${job}")"
  plan_set "${slot_ref}" "${own_oid}" '' || fail "${PLAN_CONFLICT}" 1
  sem_transact "${name}" || return 2
  printf '{"event":"released","semaphore":%s,"job":%s,"live":%s,"capacity":%s}\n' "${_j1}" "${_j2}" "${live_after}" "${SEM_CAP}"
}

cmd_sem() {
  (($# > 0)) || usage
  local verb="$1" name='' job='' holder='' ttl="${DEFAULT_TTL}" wait=0 capacity='' record='' _j1
  shift
  case "${verb}" in
    list)
      (($# == 0)) || usage
      local rows ref oid
      rows="$(refs_under "${NS}/sem/")"
      while IFS=' ' read -r ref oid; do
        [[ "${ref}" == */meta ]] || continue
        name="${ref#"${NS}"/sem/}"
        name="${name%/meta}"
        sem_read "${name}" || continue
        sem_show_line "${name}"
      done <<<"${rows}"
      return 0
      ;;
    create | acquire | release | show | delete) ;;
    *) usage ;;
  esac
  (($# > 0)) || usage
  name="$1"
  shift
  valid_job "${name}" || fail "semaphore name '${name}' must match [A-Za-z0-9][A-Za-z0-9._-]*" 2
  while (($# > 0)); do
    case "$1" in
      --job)
        [[ $# -ge 2 ]] || usage
        job="$2"
        shift 2
        ;;
      --holder)
        [[ $# -ge 2 ]] || usage
        holder="$2"
        shift 2
        ;;
      --ttl)
        [[ $# -ge 2 ]] || usage
        ttl="$2"
        shift 2
        ;;
      --wait)
        [[ $# -ge 2 ]] || usage
        wait="$2"
        shift 2
        ;;
      --capacity)
        [[ $# -ge 2 ]] || usage
        capacity="$2"
        shift 2
        ;;
      --record)
        [[ $# -ge 2 ]] || usage
        valid_oid "$2" || fail '--record is an object id' 2
        record="$2"
        shift 2
        ;;
      --acquisition)
        [[ $# -ge 2 ]] || usage
        record="$2"
        shift 2
        ;;
      *) usage ;;
    esac
  done
  case "${verb}" in
    create)
      valid_capacity capacity "${capacity}" || fail '--capacity is a decimal integer from 1 through 9223372036854775807' 2
      if sem_read "${name}"; then
        sem_refusal "${name}" exists
        exit 1
      fi
      local at meta gen mref gref content
      now_v at
      content="$(printf 'schema: %s\nsemaphore: %s\ncapacity: %s\ncreated: %s' "${SEM_SCHEMA}" "${name}" "${capacity}" "${at}")"
      write_blob meta "${content}" || fail 'could not write the semaphore record'
      gen_blob gen || fail 'could not write the generation token'
      mref="$(sem_meta_ref "${name}")"
      gref="$(sem_gen_ref "${name}")"
      plan_reset
      plan_set "${mref}" '' "${meta}"
      plan_set "${gref}" '' "${gen}"
      transact || {
        sem_refusal "${name}" exists
        exit 1
      }
      json_str _j1 "${name}"
      printf '{"event":"created","semaphore":%s,"capacity":%s}\n' "${_j1}" "${capacity}"
      ;;
    acquire)
      [[ -n "${job}" && -n "${holder}" ]] || usage
      valid_job "${job}" || fail "job id '${job}' must match [A-Za-z0-9][A-Za-z0-9._-]*" 2
      valid_ttl ttl "${ttl}" || fail '--ttl is a positive number of seconds' 2
      valid_holder "${holder}" || fail 'holder must be one line' 2
      [[ "${wait}" =~ ^[0-9]+$ ]] || fail '--wait is a number of seconds' 2
      W_SEM="${name}"
      W_JOB="${job}"
      W_HOLDER="${holder}"
      W_TTL="${ttl}"
      local errfile rc
      errfile="$(mktemp "${TMPDIR:-/tmp}/git-locks-sem.XXXXXX")" || fail 'cannot create a temporary file'
      acquire_with_wait sem "${wait}" "${errfile}"
      rc=$?
      rm -f "${errfile}"
      ((rc == 0)) || exit "${rc}"
      printf '%s\n' "${ACQUIRED_LINE}"
      ;;
    release)
      [[ -n "${job}" ]] || usage
      valid_job "${job}" || fail "job id '${job}' must match [A-Za-z0-9][A-Za-z0-9._-]*" 2
      sem_release_once "${name}" "${job}" "${record}" || exit 1
      ;;
    show)
      sem_read "${name}" || sem_missing "${name}"
      sem_show_line "${name}"
      ;;
    delete)
      local attempt deleted=0 i mref gref sref
      for ((attempt = 0; attempt < RETRIES; attempt++)); do
        snapshot
        sem_read "${name}" || sem_missing "${name}"
        if ((SEM_LIVE > 0)); then
          sem_refusal "${name}" live "${SEM_CAP}" "${SEM_LIVE}"
          exit 1
        fi
        plan_reset
        mref="$(sem_meta_ref "${name}")"
        gref="$(sem_gen_ref "${name}")"
        plan_set "${mref}" "${SEM_META_OID}" ''
        plan_set "${gref}" "${SEM_GEN_OID}" ''
        for i in "${!SLOT_JOBS[@]}"; do
          sref="$(sem_slot_ref "${name}" "${SLOT_JOBS[${i}]}")"
          plan_set "${sref}" "${SLOT_OIDS[${i}]}" ''
        done
        if transact; then
          deleted=1
          break
        fi
        sleep 0.01
      done
      ((deleted)) || {
        transaction_refusal
        exit 1
      }
      json_str _j1 "${name}"
      printf '{"event":"deleted","semaphore":%s}\n' "${_j1}"
      ;;
    *) usage ;;
  esac
}
