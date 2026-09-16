# ---------------------------------------------------------------- check

cmd_check() {
  ensure_snapshot # in this shell, so the $(…) reads below inherit one fresh snapshot instead of each taking their own
  (($# > 0)) || usage
  local at held=0 p n ref cur jp _j1 _j2
  now_v at
  for p in "$@"; do
    n="$(normalize_path "${p}")" || exit 2
    path_ref ref "${n}"
    cur="$(ref_oid "${ref}")"
    json_str jp "${n}"
    if [[ -z "${cur}" ]]; then
      printf '{"path":%s,"state":"free"}\n' "${jp}"
      continue
    fi
    describe "${cur}"
    json_str _j1 "${D_HOLDER}"
    json_str _j2 "${D_JOB}"
    if [[ "${D_EXPIRES}" -gt "${at}" ]]; then
      printf '{"path":%s,"state":"held","holder":%s,"job":%s,"expires":%s,"remaining":%s}\n' "${jp}" "${_j1}" "${_j2}" "${D_EXPIRES}" "${D_REMAINING}"
      held=1
    else
      printf '{"path":%s,"state":"expired","holder":%s,"job":%s,"expires":%s,"remaining":0}\n' "${jp}" "${_j1}" "${_j2}" "${D_EXPIRES}"
    fi
  done
  return "${held}"
}
