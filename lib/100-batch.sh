# ---------------------------------------------------------------- batch

cmd_batch() {
  (($# == 0)) || usage
  local line key val job='' holder='' ttl='' parent='' paths=() in_paths=0 count=0 lines_out=()
  plan_reset
  finish_record() {
    if [[ -z "${job}" && -z "${holder}" && ${#paths[@]} -eq 0 ]]; then return 0; fi
    [[ -n "${job}" && -n "${holder}" && ${#paths[@]} -gt 0 ]] || fail 'batch: every record needs job:, holder: and at least one path under paths:' 2
    valid_job "${job}" || fail "batch: job id '${job}' must match [A-Za-z0-9][A-Za-z0-9._-]*" 2
    [[ -z "${ttl}" ]] && ttl="${DEFAULT_TTL}"
    [[ "${ttl}" =~ ^[0-9]+$ && "${ttl}" -gt 0 ]] || fail 'batch: ttl is a positive number of seconds' 2
    plan_claim "${job}" "${holder}" "${ttl}" "${parent}" "${paths[@]}"
    lines_out+=("${CLAIM_LINE}")
    count=$((count + 1))
    job=''
    holder=''
    ttl=''
    parent=''
    paths=()
    in_paths=0
  }
  while IFS= read -r line || [[ -n "${line}" ]]; do
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
      paths) in_paths=1 ;;
      *) fail "batch: unknown line '${line}'" 2 ;;
    esac
  done
  finish_record
  ((count > 0)) || fail 'batch: no records on stdin' 2
  ((CONFLICTS)) && exit 1
  commit_plan || exit 1
  printf '%s\n' "${lines_out[@]}"
}
