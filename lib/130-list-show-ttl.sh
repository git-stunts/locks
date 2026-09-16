# ---------------------------------------------------------------- list / show / ttl

lock_line() {     # oid -> one JSON line for list and show; no fork per line, so a list of n locks is O(n) bash and no processes
  ensure_snapshot # in this shell, so the record parses below memoise here
  local _j1 _j2 _j3 _j4 jpaths claimed pj paths acq
  describe "$1"
  field_v claimed "$1" claimed
  field_v acq "$1" acquisition
  json_str _j4 "${acq}"
  record_paths_v paths "$1"
  json_paths_v jpaths "${paths}"
  json_str _j1 "${D_JOB}"
  json_str _j2 "${D_HOLDER}"
  json_str _j3 "$1"
  parent_json pj "$1"
  printf '{"job":%s,"holder":%s,"state":"%s","claimed":%s,"expires":%s,"remaining":%s%s,"paths":%s,"record":%s,"acquisition":%s}\n' \
    "${_j1}" "${_j2}" "${D_STATE}" "${claimed:-0}" "${D_EXPIRES}" "${D_REMAINING}" "${pj}" "${jpaths}" "${_j3}" "${_j4}"
}

cmd_list() {
  (($# == 0)) || usage
  local ref oid rows
  rows="$(job_refs)"
  while IFS=' ' read -r ref oid; do
    [[ -z "${ref}" ]] && continue
    lock_line "${oid}"
  done <<<"${rows}"
  return 0
}

job_arg() { # --job <id> [--ttl <n>] -> JOB_ARG TTL_ARG, or usage
  JOB_ARG=''
  TTL_ARG=''
  while (($# > 0)); do
    case "$1" in
      --job)
        [[ $# -ge 2 ]] || usage
        JOB_ARG="$2"
        shift 2
        ;;
      --ttl)
        [[ $# -ge 2 ]] || usage
        TTL_ARG="$2"
        shift 2
        ;;
      *) usage ;;
    esac
  done
  [[ -n "${JOB_ARG}" ]] || usage
  valid_job "${JOB_ARG}" || fail "job id '${JOB_ARG}' must match [A-Za-z0-9][A-Za-z0-9._-]*" 2
}

missing() { # job -> one line on stderr, exit 1
  local _j1
  json_str _j1 "$1"
  printf '{"event":"missing","job":%s}\n' "${_j1}" >&2
  exit 1
}

cmd_show() {
  ensure_snapshot # in this shell, so the $(…) reads below inherit one fresh snapshot instead of each taking their own
  local jref oid
  job_arg "$@"
  jref="$(job_ref "${JOB_ARG}")"
  oid="$(ref_oid "${jref}")"
  [[ -n "${oid}" ]] || missing "${JOB_ARG}"
  lock_line "${oid}"
}

cmd_ttl() {
  ensure_snapshot # in this shell, so the $(…) reads below inherit one fresh snapshot instead of each taking their own
  local _j1 jref oid
  job_arg "$@"
  jref="$(job_ref "${JOB_ARG}")"
  oid="$(ref_oid "${jref}")"
  [[ -n "${oid}" ]] || missing "${JOB_ARG}"
  describe "${oid}"
  json_str _j1 "${D_JOB}"
  printf '{"job":%s,"expires":%s,"remaining":%s}\n' "${_j1}" "${D_EXPIRES}" "${D_REMAINING}"
}
