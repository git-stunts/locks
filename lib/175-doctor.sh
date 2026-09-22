# ---------------------------------------------------------------- doctor
#
# A read-only invariant check over one snapshot. Every finding is one line
# as it is found; the last line states the basis (how many refs and records
# were read, at what clock) and the verdict. A store that cannot be read is
# a store-read error, exit 2, never "healthy". Diagnosis only: nothing here
# writes, and repair, if it ever exists, is a separate explicit command.

DOC_FINDINGS=0
DOC_CHECKS='"record-decodes","job-ref-name","path-ref-missing","path-ref-elsewhere","path-ref-orphan","path-ref-stray","parent-missing","parent-expired","parent-holder","family-cycle","sem-meta","sem-gen","sem-record","sem-capacity","unknown-ref"'

finding() { # check subject detail -> one finding line on stdout
  local _j1 _j2 _j3
  json_str _j1 "$1"
  json_str _j2 "$2"
  json_str _j3 "$3"
  printf '{"event":"finding","check":%s,"subject":%s,"detail":%s}\n' "${_j1}" "${_j2}" "${_j3}"
  DOC_FINDINGS=$((DOC_FINDINGS + 1))
}

doctor_hash_paths() { # path... -> PATH_HASH for every path, in one git process: each path becomes a file, hash-object hashes them all
  local dir p i=0 files=() todo=() out h rc
  for p in "$@"; do
    [[ -n "${PATH_HASH[${p}]+x}" ]] && continue
    in_list "${p}" "${todo[@]}" && continue
    todo+=("${p}")
  done
  ((${#todo[@]} > 0)) || return 0
  dir="$(mktemp -d "${TMPDIR:-/tmp}/git-locks-doctor.XXXXXX")" || fail 'cannot create a temporary directory for hashing' 2
  for p in "${todo[@]}"; do
    printf '%s' "${p}" >"${dir}/${i}"
    files+=("${dir}/${i}")
    i=$((i + 1))
  done
  out="$(g hash-object --no-filters "${files[@]}" 2>&1)" # --no-filters: the same bytes path_ref hashes from stdin
  rc=$?
  rm -rf "${dir}"
  ((rc == 0)) || store_error "hash-object exited ${rc}: ${out}"
  i=0
  while IFS= read -r h; do
    [[ -z "${h}" ]] && continue
    valid_oid "${h}" || store_error "hash-object line does not parse: ${h}"
    PATH_HASH["${todo[${i}]}"]="${h}"
    i=$((i + 1))
  done <<<"${out}"
  ((i == ${#todo[@]})) || store_error "hash-object returned ${i} hashes for ${#todo[@]} paths"
}

doctor_lock_record() { # subject oid -> decoded lock or a diagnostic finding
  validate_record "$2" lock && return 0
  finding record-decodes "$1" "record ${2}: ${RECORD_ERROR}"
  return 1
}

doctor_slot_record() { # subject oid name job -> 0 when the record decodes as a slot of that semaphore for that job
  local v bad=0
  validate_record "$2" slot || {
    finding sem-record "$1" "slot record ${2}: ${RECORD_ERROR}"
    return 1
  }
  field_v v "$2" semaphore
  [[ "${v}" == "$3" ]] || {
    finding sem-record "$1" "slot record ${2} names semaphore '${v}'"
    bad=1
  }
  field_v v "$2" job
  [[ "${v}" == "$4" ]] || {
    finding sem-record "$1" "slot record ${2} names job '${v}'"
    bad=1
  }
  return "${bad}"
}

cmd_doctor() {
  (($# == 0)) || usage
  ensure_snapshot
  local rows ref oid job name rest at refs_n=0 recs_n="${#BLOB[@]}"
  local -A JOB_OID=() OID_JOBS=() PATHREF_OID=() EXPECTED_PATHREF=() JOB_OK=()
  local -A SEM_META=() SEM_GEN=() SEM_SLOT_OIDS=() SEM_SLOT_JOBS=() SEM_NAMES=()
  local jobs=() sems=() pathrefs=() all_paths=() p paths
  now_v at
  rows="$(refs_under "${NS}/")" # sorted, so findings come in a stable order
  while IFS=' ' read -r ref oid; do
    [[ -z "${ref}" ]] && continue
    refs_n=$((refs_n + 1))
    case "${ref}" in
      "${NS}"/jobs/*)
        job="${ref#"${NS}"/jobs/}"
        JOB_OID["${job}"]="${oid}"
        OID_JOBS["${oid}"]+="${job} "
        jobs+=("${job}")
        ;;
      "${NS}"/paths/*)
        PATHREF_OID["${ref}"]="${oid}"
        pathrefs+=("${ref}")
        ;;
      "${NS}"/dirs/*) ;; # a directory token: the last record that touched the directory; any object will do, the snapshot already checked it exists
      "${NS}"/sem/*)
        rest="${ref#"${NS}"/sem/}"
        name="${rest%%/*}"
        rest="${rest#*/}"
        if [[ -z "${SEM_NAMES[${name}]+x}" ]]; then
          SEM_NAMES["${name}"]=1
          sems+=("${name}")
        fi
        case "${rest}" in
          meta) SEM_META["${name}"]="${oid}" ;;
          gen) SEM_GEN["${name}"]="${oid}" ;;
          slots/*)
            SEM_SLOT_OIDS["${name}"]+="${oid} "
            SEM_SLOT_JOBS["${name}"]+="${rest#slots/} "
            ;;
          *) finding unknown-ref "${ref}" 'a semaphore ref that is not meta, gen or a slot' ;;
        esac
        ;;
      *) finding unknown-ref "${ref}" 'a ref in the namespace that is not a job, path or semaphore ref' ;;
    esac
  done <<<"${rows}"

  # Job records decode and name their own job; collect every path they list.
  for job in "${jobs[@]}"; do
    oid="${JOB_OID[${job}]}"
    doctor_lock_record "${job}" "${oid}" || continue
    JOB_OK["${job}"]=1
    field_v rest "${oid}" job
    [[ "${rest}" == "${job}" ]] || finding job-ref-name "${job}" "the job ref points at a record for job '${rest}'"
    record_paths_v paths "${oid}"
    while [[ -n "${paths}" ]]; do
      p="${paths%%$'\n'*}"
      if [[ "${p}" == "${paths}" ]]; then paths=''; else paths="${paths#*$'\n'}"; fi
      [[ -n "${p}" ]] && all_paths+=("${p}")
    done
  done
  doctor_hash_paths "${all_paths[@]}"

  # Every listed path has a path ref pointing at this record; every path ref is listed by the record it points at.
  local have key
  for job in "${jobs[@]}"; do
    [[ -n "${JOB_OK[${job}]+x}" ]] || continue
    oid="${JOB_OID[${job}]}"
    record_paths_v paths "${oid}"
    while [[ -n "${paths}" ]]; do
      p="${paths%%$'\n'*}"
      if [[ "${p}" == "${paths}" ]]; then paths=''; else paths="${paths#*$'\n'}"; fi
      [[ -n "${p}" ]] || continue
      ref="${NS}/paths/${PATH_HASH[${p}]}"
      have="${PATHREF_OID[${ref}]:-}"
      if [[ -z "${have}" ]]; then
        finding path-ref-missing "${job}" "no path ref for '${p}': a claim on it would not see this lock"
      elif [[ "${have}" != "${oid}" ]]; then
        finding path-ref-elsewhere "${job}" "the path ref for '${p}' points at record ${have} (job ${OID_JOBS[${have}]:-of no job ref})"
      fi
      EXPECTED_PATHREF["${ref}|${oid}"]=1 # this record lists a path hashing to this ref
    done
  done
  for ref in "${pathrefs[@]}"; do # in ref order, from the sorted rows
    oid="${PATHREF_OID[${ref}]}"
    if [[ -z "${OID_JOBS[${oid}]+x}" ]]; then
      finding path-ref-orphan "${ref}" "points at record ${oid}, which no job ref points at: the path reads as held by nothing a release can name"
    elif key="${ref}|${oid}" && [[ -z "${EXPECTED_PATHREF[${key}]+x}" ]]; then
      finding path-ref-stray "${ref}" "points at record ${oid} (job ${OID_JOBS[${oid}]% }) which lists no path hashing to this ref"
    fi
  done

  # Families: the parent exists, is live, has the same holder, and the chain has no cycle.
  local parent pexp pholder holder cur steps
  for job in "${jobs[@]}"; do
    [[ -n "${JOB_OK[${job}]+x}" ]] || continue
    oid="${JOB_OID[${job}]}"
    field_v parent "${oid}" parent
    [[ -n "${parent}" ]] || continue
    if [[ -z "${JOB_OID[${parent}]+x}" ]]; then
      finding parent-missing "${job}" "names parent '${parent}', which has no job ref: a child cannot outlive its parent"
      continue
    fi
    [[ -n "${JOB_OK[${parent}]+x}" ]] || continue # its decoder already reported the corrupt parent
    field_v pexp "${JOB_OID[${parent}]}" expires
    ((${pexp:-0} > at)) || finding parent-expired "${job}" "parent '${parent}' expired at ${pexp:-0}; sweep removes both"
    field_v holder "${oid}" holder
    field_v pholder "${JOB_OID[${parent}]}" holder
    [[ "${holder}" == "${pholder}" ]] || finding parent-holder "${job}" "held by '${holder}' but parent '${parent}' is held by '${pholder}'"
    cur="${parent}"
    steps=0
    while [[ -n "${cur}" && -n "${JOB_OID[${cur}]+x}" ]] && ((steps <= ${#jobs[@]})); do
      if [[ "${cur}" == "${job}" ]]; then
        finding family-cycle "${job}" "its parent chain returns to itself"
        break
      fi
      field_v cur "${JOB_OID[${cur}]}" parent
      steps=$((steps + 1))
    done
  done

  # Semaphores: meta and gen exist, records decode, live slots fit the capacity.
  local cap live sjob soid slot_oids slot_jobs exp
  for name in "${sems[@]}"; do
    if [[ -z "${SEM_META[${name}]+x}" ]]; then
      finding sem-meta "${name}" 'no meta ref: the semaphore has no capacity'
      cap=''
    else
      if ! validate_record "${SEM_META[${name}]}" meta; then
        finding sem-record "${name}" "meta record ${SEM_META[${name}]}: ${RECORD_ERROR}"
        cap=''
      else
        field_v cap "${SEM_META[${name}]}" capacity
        field_v rest "${SEM_META[${name}]}" semaphore
        [[ "${rest}" == "${name}" ]] || finding sem-record "${name}" "meta record names semaphore '${rest}'"
      fi
    fi
    [[ -n "${SEM_GEN[${name}]+x}" ]] || finding sem-gen "${name}" 'no gen ref: acquire and release cannot compare-and-swap'
    live=0
    slot_oids="${SEM_SLOT_OIDS[${name}]:-}"
    slot_jobs="${SEM_SLOT_JOBS[${name}]:-}"
    while [[ -n "${slot_oids}" ]]; do
      soid="${slot_oids%% *}"
      slot_oids="${slot_oids#* }"
      sjob="${slot_jobs%% *}"
      slot_jobs="${slot_jobs#* }"
      doctor_slot_record "${name}/${sjob}" "${soid}" "${name}" "${sjob}" || continue
      field_v exp "${soid}" expires
      ((exp > at)) && live=$((live + 1))
    done
    if [[ -n "${cap}" ]] && ((live > cap)); then
      finding sem-capacity "${name}" "${live} live slots over a capacity of ${cap}"
    fi
  done

  local _j1 healthy=true
  ((DOC_FINDINGS == 0)) || healthy=false
  json_str _j1 "${STORE}"
  printf '{"event":"doctor","store":%s,"basis":{"refs":%s,"records":%s,"now":%s},"checks":[%s],"findings":%s,"healthy":%s}\n' \
    "${_j1}" "${refs_n}" "${recs_n}" "${at}" "${DOC_CHECKS}" "${DOC_FINDINGS}" "${healthy}"
  ((DOC_FINDINGS == 0))
}
