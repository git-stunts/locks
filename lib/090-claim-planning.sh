# ---------------------------------------------------------------- claim planning

BATCH_JOBS=()
declare -A BATCH_HOLDER=() # job planned in this batch -> holder
declare -A BUMPED=()       # parent job -> 1 once its family generation is planned in this batch
CONFLICTS=0
CLAIM_LINE=''
TERMINATED_PATHS=0
TERMINATED_CASCADE='[]'

plan_claim() {    # job holder ttl parent path... -> plans one claim; sets CLAIM_LINE/CLAIM_OID; CONFLICTS=1 on refusal
  ensure_snapshot # in this shell, so the $(…) reads below inherit one fresh snapshot instead of each taking their own
  local job="$1" holder="$2" ttl="$3" parent="$4"
  shift 4
  local paths=("$@") p n norm=() sorted wanted=()
  for p in "${paths[@]}"; do
    n="$(normalize_path "${p}")" || exit 2
    norm+=("${n}")
  done
  sorted="$(printf '%s\n' "${norm[@]}" | sort -u)"
  while IFS= read -r n; do [[ -n "${n}" ]] && wanted+=("${n}"); done <<<"${sorted}"

  local at expires
  now_v at
  expires=$((at + ttl))

  # The parent, if any: live and the same holder, whether it exists already or is planned earlier in this batch.
  local pref poid
  if [[ -n "${parent}" ]]; then
    valid_job "${parent}" || fail "parent id '${parent}' must match [A-Za-z0-9][A-Za-z0-9._-]*" 2
    if in_list "${parent}" "${BATCH_JOBS[@]}"; then
      if [[ "${BATCH_HOLDER[${parent}]}" != "${holder}" ]]; then
        parent_refusal "${job}" "${parent}" holder
        CONFLICTS=1
        return 0
      fi
    else
      pref="$(job_ref "${parent}")"
      poid="$(ref_oid "${pref}")"
      if [[ -z "${poid}" ]]; then
        parent_refusal "${job}" "${parent}" missing
        CONFLICTS=1
        return 0
      fi
      describe "${poid}"
      if [[ "${D_STATE}" != live ]]; then
        parent_refusal "${job}" "${parent}" expired
        CONFLICTS=1
        return 0
      fi
      if [[ "${D_HOLDER}" != "${holder}" ]]; then
        parent_refusal "${job}" "${parent}" holder
        CONFLICTS=1
        return 0
      fi
      if [[ -z "${BUMPED[${parent}]+x}" ]]; then
        bump_parent "${parent}" "${poid}" || {
          fail "${PLAN_CONFLICT}" 1
        }
        BUMPED["${parent}"]=1
      fi
    fi
  fi

  local jref old_job_oid old_family='0'
  jref="$(job_ref "${job}")"
  old_job_oid="$(ref_oid "${jref}")"
  [[ -n "${old_job_oid}" ]] && old_family="$(field "${old_job_oid}" family)"
  local record new_oid acq joined
  new_acquisition acq
  joined="$(printf '%s\n' "${wanted[@]}")"
  record_text record "${job}" "${holder}" "${at}" "${expires}" "${parent}" "${old_family:-0}" "${acq}" "${joined}"
  write_blob new_oid "${record}" || fail 'could not write the lock record'

  local evict=() ref cur rjob rexp
  for p in "${wanted[@]}"; do
    path_ref ref "${p}"
    cur="$(ref_oid "${ref}")"
    if [[ -z "${cur}" ]]; then
      if [[ -n "${T_BEFORE[${ref}]+x}" && "${T_AFTER[${ref}]}" != '=' ]]; then
        duplicate_refusal "${p}" # another record in this batch already takes it
        CONFLICTS=1
        continue
      fi
      plan_set "${ref}" '' "${new_oid}" || {
        duplicate_refusal "${p}"
        CONFLICTS=1
      }
      continue
    fi
    field_v rjob "${cur}" job
    field_v rexp "${cur}" expires
    if [[ "${rjob}" == "${job}" ]]; then
      plan_set "${ref}" "${cur}" "${new_oid}" || {
        duplicate_refusal "${p}"
        CONFLICTS=1
      }
    elif [[ -n "${rexp}" && "${rexp}" -le "${at}" ]]; then
      in_list "${rjob}" "${evict[@]}" || evict+=("${rjob}")
    else
      describe "${cur}"
      refusal "${p}"
      CONFLICTS=1
    fi
  done

  # The job's own ref, and paths it held before but no longer lists.
  if [[ -n "${old_job_oid}" ]]; then
    plan_set "${jref}" "${old_job_oid}" "${new_oid}" || fail "${PLAN_CONFLICT}" 1
    local old_paths have
    old_paths="$(record_paths "${old_job_oid}")"
    while IFS= read -r p; do
      [[ -z "${p}" ]] && continue
      in_list "${p}" "${wanted[@]}" && continue
      path_ref ref "${p}"
      have="$(ref_oid "${ref}")"
      [[ "${have}" == "${old_job_oid}" ]] && { plan_set "${ref}" "${old_job_oid}" '' || fail "${PLAN_CONFLICT}" 1; }
    done <<<"${old_paths}"
  else
    plan_set "${jref}" '' "${new_oid}" || fail "${PLAN_CONFLICT}" 1
  fi

  # An expired lock in the way is terminated whole, descendants included, the same way release and sweep do it;
  # then the wanted paths it held move to the new record.
  local ej
  for ej in "${evict[@]}"; do
    plan_terminate "${ej}" || fail "${PLAN_CONFLICT}" 1
  done
  for p in "${wanted[@]}"; do
    path_ref ref "${p}"
    cur="$(ref_oid "${ref}")"
    [[ -z "${cur}" ]] && continue
    field_v rjob "${cur}" job
    in_list "${rjob}" "${evict[@]}" || continue
    T_AFTER["${ref}"]="${new_oid}" # planned as a delete by plan_terminate; the path passes to the new lock instead
  done

  BATCH_JOBS+=("${job}")
  BATCH_HOLDER["${job}"]="${holder}"
  local jpaths _j1 _j2 _j3 _j4 pj=''
  json_paths jpaths < <(printf '%s\n' "${wanted[@]}")
  json_str _j1 "${job}"
  json_str _j2 "${holder}"
  json_str _j3 "${new_oid}"
  json_str _j4 "${acq}"
  if [[ -n "${parent}" ]]; then
    json_str pj "${parent}"
    pj=",\"parent\":${pj}"
  fi
  CLAIM_LINE="{\"event\":\"claimed\",\"job\":${_j1},\"holder\":${_j2},\"claimed\":${at},\"expires\":${expires}${pj},\"paths\":${jpaths},\"record\":${_j3},\"acquisition\":${_j4}}"
  return 0
}

ref_path() { # oid ref -> which of the record's paths hashes to this ref (for naming a lost race)
  local p pr paths
  paths="$(record_paths "$1")"
  while IFS= read -r p; do
    [[ -z "${p}" ]] && continue
    path_ref pr "${p}"
    if [[ "${pr}" == "$2" ]]; then
      printf '%s' "${p}"
      return 0
    fi
  done <<<"${paths}"
  return 0
}

commit_plan() { # -> 0 committed; 1 lost a race (refusals printed)
  transact && return 0
  local lost=0 ref cur p
  for ref in "${PLAN_ORDER[@]}"; do
    [[ "${ref}" == "${NS}/paths/"* ]] || continue
    cur="$(ref_oid "${ref}")"
    [[ -z "${cur}" ]] && continue
    p="$(ref_path "${cur}" "${ref}")"
    [[ -z "${p}" ]] && continue
    describe "${cur}"
    in_list "${D_JOB}" "${BATCH_JOBS[@]}" && continue
    refusal "${p}"
    lost=1
  done
  ((lost == 0)) && transaction_refusal
  return 1
}

claim_args() { # parses claim arguments into CA_JOB CA_HOLDER CA_TTL CA_PARENT CA_PATHS
  CA_JOB=''
  CA_HOLDER=''
  CA_TTL="${DEFAULT_TTL}"
  CA_PARENT=''
  CA_PATHS=()
  while (($# > 0)); do
    case "$1" in
      --job)
        [[ $# -ge 2 ]] || usage
        CA_JOB="$2"
        shift 2
        ;;
      --holder)
        [[ $# -ge 2 ]] || usage
        CA_HOLDER="$2"
        shift 2
        ;;
      --ttl)
        [[ $# -ge 2 ]] || usage
        CA_TTL="$2"
        shift 2
        ;;
      --parent)
        [[ $# -ge 2 ]] || usage
        CA_PARENT="$2"
        shift 2
        ;;
      --)
        shift
        CA_PATHS+=("$@")
        break
        ;;
      -*) usage ;;
      *)
        CA_PATHS+=("$1")
        shift
        ;;
    esac
  done
  [[ -n "${CA_JOB}" && -n "${CA_HOLDER}" ]] || usage
  valid_job "${CA_JOB}" || fail "job id '${CA_JOB}' must match [A-Za-z0-9][A-Za-z0-9._-]*" 2
  valid_ttl CA_TTL "${CA_TTL}" || fail '--ttl is a positive number of seconds' 2
  valid_holder "${CA_HOLDER}" || fail 'holder must be one line' 2
  ((${#CA_PATHS[@]} > 0)) || usage
}

cmd_claim() {
  claim_args "$@"
  plan_reset
  plan_claim "${CA_JOB}" "${CA_HOLDER}" "${CA_TTL}" "${CA_PARENT}" "${CA_PATHS[@]}"
  ((CONFLICTS)) && exit 1
  commit_plan || exit 1
  printf '%s\n' "${CLAIM_LINE}"
}
