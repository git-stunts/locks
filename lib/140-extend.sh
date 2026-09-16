# ---------------------------------------------------------------- extend

cmd_extend() {
  local _j1 oid jref at expires record new_oid paths p ref have claimed parent family attempt acq
  job_arg "$@"
  [[ "${TTL_ARG}" =~ ^[0-9]+$ && "${TTL_ARG}" -gt 0 ]] || fail '--ttl is a positive number of seconds' 2
  jref="$(job_ref "${JOB_ARG}")"
  for ((attempt = 0; attempt < RETRIES; attempt++)); do
    snapshot
    plan_reset
    oid="$(ref_oid "${jref}")"
    [[ -n "${oid}" ]] || missing "${JOB_ARG}"
    describe "${oid}"
    at="$(now)"
    expires=$((at + TTL_ARG))
    paths="$(record_paths "${oid}")"
    claimed="$(field "${oid}" claimed)"
    parent="$(field "${oid}" parent)"
    family="$(field "${oid}" family)"
    acq="$(field "${oid}" acquisition)"
    record_text record "${D_JOB}" "${D_HOLDER}" "${claimed}" "${expires}" "${parent}" "${family:-0}" "${acq}" "${paths}"
    write_blob new_oid "${record}" || fail 'could not write the lock record'
    plan_set "${jref}" "${oid}" "${new_oid}" || fail "${PLAN_CONFLICT}" 1
    while IFS= read -r p; do
      [[ -z "${p}" ]] && continue
      path_ref ref "${p}"
      have="$(ref_oid "${ref}")"
      [[ "${have}" == "${oid}" ]] && { plan_set "${ref}" "${oid}" "${new_oid}" || fail "${PLAN_CONFLICT}" 1; }
    done <<<"${paths}"
    transact && break
    sleep 0.01
  done
  ((attempt < RETRIES)) || {
    transaction_refusal
    exit 1
  }
  json_str _j1 "${JOB_ARG}"
  printf '{"event":"extended","job":%s,"expires":%s}\n' "${_j1}" "${expires}"
}
