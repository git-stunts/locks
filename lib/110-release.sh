# ---------------------------------------------------------------- release

cmd_release() {
  local jobs=() records=() acqs=() _j1 j have_acq
  while (($# > 0)); do
    case "$1" in
      --job)
        [[ $# -ge 2 ]] || usage
        jobs+=("$2")
        records+=('')
        acqs+=('')
        shift 2
        ;;
      --record)
        [[ $# -ge 2 ]] || usage
        ((${#jobs[@]} > 0)) || usage
        valid_oid "$2" || fail '--record is an object id' 2
        records[${#jobs[@]} - 1]="$2"
        shift 2
        ;;
      --acquisition)
        [[ $# -ge 2 ]] || usage
        ((${#jobs[@]} > 0)) || usage
        acqs[${#jobs[@]} - 1]="$2"
        shift 2
        ;;
      *) usage ;;
    esac
  done
  ((${#jobs[@]} > 0)) || usage
  for j in "${jobs[@]}"; do
    valid_job "${j}" || fail "job id '${j}' must match [A-Za-z0-9][A-Za-z0-9._-]*" 2
  done
  local attempt i present counts cascades absent superseded jref oid
  for ((attempt = 0; attempt < RETRIES; attempt++)); do
    snapshot
    plan_reset
    present=()
    counts=()
    cascades=()
    absent=()
    superseded=()
    for i in "${!jobs[@]}"; do
      j="${jobs[${i}]}"
      jref="$(job_ref "${j}")"
      oid="$(ref_oid "${jref}")"
      if [[ -z "${oid}" ]]; then
        absent+=("${j}")
        continue
      fi
      if [[ -n "${records[${i}]}" && "${records[${i}]}" != "${oid}" ]]; then
        superseded+=("${j}")
        continue
      fi
      if [[ -n "${acqs[${i}]}" ]]; then
        have_acq="$(field "${oid}" acquisition)"
        if [[ "${have_acq}" != "${acqs[${i}]}" ]]; then
          superseded+=("${j}")
          continue
        fi
      fi
      in_list "${j}" "${present[@]}" && continue
      plan_terminate "${j}" || fail "${PLAN_CONFLICT}" 1
      present+=("${j}")
      counts+=("${TERMINATED_PATHS}")
      cascades+=("${TERMINATED_CASCADE}")
    done
    if ((${#PLAN_ORDER[@]} == 0)); then break; fi
    transact && break
    sleep 0.01
  done
  ((attempt < RETRIES)) || {
    transaction_refusal
    exit 1
  }
  for i in "${!present[@]}"; do
    json_str _j1 "${present[${i}]}"
    if [[ "${cascades[${i}]}" == '[]' ]]; then
      printf '{"event":"released","job":%s,"paths":%d}\n' "${_j1}" "${counts[${i}]}"
    else
      printf '{"event":"released","job":%s,"paths":%d,"cascaded":%s}\n' "${_j1}" "${counts[${i}]}" "${cascades[${i}]}"
    fi
  done
  for j in "${superseded[@]}"; do
    json_str _j1 "${j}"
    printf '{"event":"nothing","job":%s,"reason":"superseded"}\n' "${_j1}"
  done
  for j in "${absent[@]}"; do
    json_str _j1 "${j}"
    printf '{"event":"nothing","job":%s}\n' "${_j1}"
  done
  return 0
}
