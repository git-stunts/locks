# ---------------------------------------------------------------- sweep

cmd_sweep() {
  (($# == 0)) || usage
  local at ref oid rows rjob rholder rexpires _j1 _j2 attempt done_jobs=() still
  now_v at
  rows="$(job_refs)"
  while IFS=' ' read -r ref oid; do
    [[ -z "${ref}" ]] && continue
    describe "${oid}"
    [[ "${D_EXPIRES}" -gt "${at}" ]] && continue
    rjob="${D_JOB}"
    in_list "${rjob}" "${done_jobs[@]}" && continue # already swept as someone's descendant
    rholder="${D_HOLDER}"
    rexpires="${D_EXPIRES}"
    local swept=0
    for ((attempt = 0; attempt < RETRIES; attempt++)); do
      snapshot
      plan_reset
      still="$(ref_oid "${ref}")"
      [[ -n "${still}" ]] || break          # gone meanwhile
      [[ "${still}" == "${oid}" ]] || break # replaced or extended meanwhile: that is not the lock we saw expire
      plan_terminate "${rjob}" || fail "${PLAN_CONFLICT}" 1
      if transact; then
        swept=1
        break
      fi
      sleep 0.01
    done
    ((swept)) || continue
    done_jobs+=("${rjob}")
    local d
    for d in "${DESC[@]}"; do done_jobs+=("${d}"); done
    json_str _j1 "${rjob}"
    json_str _j2 "${rholder}"
    if [[ "${TERMINATED_CASCADE}" == '[]' ]]; then
      printf '{"event":"swept","job":%s,"holder":%s,"expires":%s}\n' "${_j1}" "${_j2}" "${rexpires}"
    else
      printf '{"event":"swept","job":%s,"holder":%s,"expires":%s,"cascaded":%s}\n' "${_j1}" "${_j2}" "${rexpires}" "${TERMINATED_CASCADE}"
    fi
  done <<<"${rows}"
  return 0
}
