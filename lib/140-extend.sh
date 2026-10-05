# ---------------------------------------------------------------- extend

renewal_refusal() { # job reason -> a refused renewal, exit 1
  local _j1
  json_str _j1 "$1"
  printf '{"event":"refused","reason":"%s","job":%s}\n' "$2" "${_j1}" >&2
  exit 1
}

cmd_extend() {
  local _j1 oid jref at expires record new_oid paths p ref have claimed parent family attempt acq ttl note
  local expected_acq='' options=()
  while (($# > 0)); do
    case "$1" in
      --job | --ttl)
        [[ $# -ge 2 ]] || usage
        options+=("$1" "$2")
        shift 2
        ;;
      --acquisition)
        [[ $# -ge 2 ]] || usage
        valid_holder "$2" || fail '--acquisition must be a nonempty UTF-8 line' 2
        expected_acq="$2"
        shift 2
        ;;
      *) usage ;;
    esac
  done
  job_arg "${options[@]}"
  valid_ttl ttl "${TTL_ARG}" || fail '--ttl is a positive number of seconds' 2
  jref="$(job_ref "${JOB_ARG}")"
  for ((attempt = 0; attempt < RETRIES; attempt++)); do
    snapshot
    plan_reset
    oid="$(ref_oid "${jref}")"
    [[ -n "${oid}" ]] || missing "${JOB_ARG}"
    describe "${oid}"
    field_v acq "${oid}" acquisition
    [[ -z "${expected_acq}" || "${expected_acq}" == "${acq}" ]] || renewal_refusal "${JOB_ARG}" superseded
    [[ "${D_STATE}" == live ]] || renewal_refusal "${JOB_ARG}" expired
    now_v at
    expiry_v expires "${at}" "${ttl}"
    paths="$(record_paths "${oid}")"
    claimed="$(field "${oid}" claimed)"
    parent="$(field "${oid}" parent)"
    family="$(field "${oid}" family)"
    field_v note "${oid}" note
    record_text record "${D_JOB}" "${D_HOLDER}" "${claimed}" "${expires}" "${parent}" "${family:-0}" "${acq}" "${paths}" "${note}"
    write_blob new_oid "${record}"
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
