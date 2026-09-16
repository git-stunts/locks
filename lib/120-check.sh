# ---------------------------------------------------------------- check

cmd_check() {
  ensure_snapshot # in this shell, so the $(…) reads below inherit one fresh snapshot instead of each taking their own
  (($# > 0)) || usage
  local at held=0 p n ref cur jp _j1 _j2 via jv
  now_v at
  for p in "$@"; do
    n="$(normalize_path "${p}")" || exit 2
    path_ref ref "${n}"
    cur="$(ref_oid "${ref}")"
    json_str jp "${n}"
    via=''
    if [[ -z "${cur}" ]] || ! record_live "${cur}" "${at}"; then
      covering_v via "${n}" "${at}" # a live prefix above, or a live path under a prefix; empty when none
    fi
    if [[ -n "${via}" ]]; then
      path_ref ref "${via}"
      cur="$(ref_oid "${ref}")"
    fi
    if [[ -z "${cur}" ]]; then
      printf '{"path":%s,"state":"free"}\n' "${jp}"
      continue
    fi
    describe "${cur}"
    json_str _j1 "${D_HOLDER}"
    json_str _j2 "${D_JOB}"
    jv=''
    if [[ -n "${via}" ]]; then
      json_str jv "${via}"
      jv=",\"via\":${jv}"
    fi
    if [[ "${D_EXPIRES}" -gt "${at}" ]]; then
      printf '{"path":%s,"state":"held","holder":%s%s,"job":%s%s,"expires":%s,"remaining":%s}\n' "${jp}" "${_j1}" "${D_NOTE_JSON}" "${_j2}" "${jv}" "${D_EXPIRES}" "${D_REMAINING}"
      held=1
    else
      printf '{"path":%s,"state":"expired","holder":%s%s,"job":%s,"expires":%s,"remaining":0}\n' "${jp}" "${_j1}" "${D_NOTE_JSON}" "${_j2}" "${D_EXPIRES}"
    fi
  done
  return "${held}"
}

record_live() { # oid now -> 0 when the record's expiry is in the future
  local _rl
  field_v _rl "$1" expires
  [[ -n "${_rl}" ]] && ((_rl > $2))
}

covering_v() { # VAR path now: set VAR to the path of a live lock that covers this one from above (a prefix) or, for a prefix, from below (a path under it); empty when none
  local _cv_p="$2" _cv_at="$3" _cv_ancs _cv_anc _cv_ref _cv_cur _cv_rows _cv_oid _cv_paths _cv_rp
  printf -v "$1" ''
  ancestors_v _cv_ancs "${_cv_p}"
  while [[ -n "${_cv_ancs}" ]]; do
    _cv_anc="${_cv_ancs%%$'\n'*}"
    if [[ "${_cv_anc}" == "${_cv_ancs}" ]]; then _cv_ancs=''; else _cv_ancs="${_cv_ancs#*$'\n'}"; fi
    path_ref _cv_ref "${_cv_anc}"
    _cv_cur="${REF_OID[${_cv_ref}]:-}"
    if [[ -n "${_cv_cur}" ]] && record_live "${_cv_cur}" "${_cv_at}"; then
      printf -v "$1" '%s' "${_cv_anc}"
      return 0
    fi
  done
  is_prefix "${_cv_p}" || return 0
  _cv_rows="$(job_refs)"
  while IFS=' ' read -r _cv_ref _cv_oid; do
    [[ -z "${_cv_ref}" ]] && continue
    record_live "${_cv_oid}" "${_cv_at}" || continue
    record_paths_v _cv_paths "${_cv_oid}"
    while [[ -n "${_cv_paths}" ]]; do
      _cv_rp="${_cv_paths%%$'\n'*}"
      if [[ "${_cv_rp}" == "${_cv_paths}" ]]; then _cv_paths=''; else _cv_paths="${_cv_paths#*$'\n'}"; fi
      if [[ -n "${_cv_rp}" && "${_cv_rp}" == "${_cv_p}"?* ]]; then
        printf -v "$1" '%s' "${_cv_rp}"
        return 0
      fi
    done
  done <<<"${_cv_rows}"
  return 0
}
