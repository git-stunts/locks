# ----------------------------------------------------- relationships in a root
# Record syntax is necessary but not sufficient authority. Check both directions
# of each index before rendering or planning. Diagnosis uses the same immutable
# snapshot but remains available to explain a damaged store.

reject_path_overlap() { # path ancestor job ancestor-job
  store_error "job $3: live path '$1' overlaps '$2' owned by job $4"
}

check_path_overlaps() { # callback now job...; malformed records are diagnosed separately
  local callback="$1" at="$2" job oid paths p ancs anc
  shift 2
  local -A active=()
  for job in "$@"; do
    oid="${REF_OID["${NS}/jobs/${job}"]}"
    validate_record "${oid}" lock || continue
    ((${R_FIELD["${oid} expires"]} > at)) || continue
    paths="${R_PATHS[${oid}]}"
    while IFS= read -r p; do active["${p}"]="${job}"; done <<<"${paths}"
  done
  for p in "${!active[@]}"; do
    ancestors_v ancs "${p}"
    [[ -n "${ancs}" ]] || continue
    while IFS= read -r anc; do
      if [[ -n "${active[${anc}]+x}" && "${active[${anc}]}" != "${active[${p}]}" ]]; then
        "${callback}" "${p}" "${anc}" "${active[${p}]}" "${active[${anc}]}"
      fi
    done <<<"${ancs}"
  done
  return 0
}

validate_relations() {
  local ref oid job paths p parent poid name rest at cur
  local jobs=() all_paths=() chain=()
  local -A expected=() parents=() finished=() visiting=() semaphore_names=() live_counts=()
  now_v at
  for ref in "${!REF_OID[@]}"; do
    oid="${REF_OID[${ref}]}"
    case "${ref}" in
      "${NS}"/jobs/*)
        job="${ref#"${NS}"/jobs/}"
        jobs+=("${job}")
        paths="${R_PATHS[${oid}]}"
        while IFS= read -r p; do all_paths+=("${p}"); done <<<"${paths}"
        parent="${R_FIELD["${oid} parent"]:-}"
        parents["${job}"]="${parent}"
        if [[ -n "${parent}" ]]; then
          poid="${REF_OID["${NS}/jobs/${parent}"]:-}"
          [[ -n "${poid}" ]] || store_error "job ${job}: missing parent ${parent}"
          [[ "${R_FIELD["${oid} holder"]}" == "${R_FIELD["${poid} holder"]}" ]] || store_error "job ${job}: holder differs from parent ${parent}"
        fi
        ;;
      "${NS}"/sem/*)
        rest="${ref#"${NS}"/sem/}"
        name="${rest%%/*}"
        semaphore_names["${name}"]=1
        if [[ "${rest#*/}" == slots/* ]] && ((${R_FIELD["${oid} expires"]} > at)); then
          live_counts["${name}"]=$((${live_counts[${name}]:-0} + 1))
        fi
        ;;
      *) ;;
    esac
  done
  hash_paths "${all_paths[@]}"
  for job in "${jobs[@]}"; do
    oid="${REF_OID["${NS}/jobs/${job}"]}"
    paths="${R_PATHS[${oid}]}"
    while IFS= read -r p; do
      ref="${NS}/paths/${PATH_HASH[${p}]}"
      [[ "${REF_OID[${ref}]:-}" == "${oid}" ]] || store_error "job ${job}: missing or inconsistent path index for '${p}'"
      expected["${ref}"]="${oid}"
    done <<<"${paths}"
  done
  for ref in "${!REF_OID[@]}"; do
    [[ "${ref}" == "${NS}"/paths/* ]] || continue
    [[ "${expected[${ref}]:-}" == "${REF_OID[${ref}]}" ]] || store_error "${ref}: orphan or stray path index"
  done

  # Each parent edge is visited once. Expired parents remain structurally valid:
  # time passes without publication, and sweep is allowed to remove that family.
  for job in "${jobs[@]}"; do
    [[ -z "${finished[${job}]+x}" ]] || continue
    cur="${job}"
    chain=()
    visiting=()
    while [[ -n "${cur}" && -z "${finished[${cur}]+x}" ]]; do
      [[ -z "${visiting[${cur}]+x}" ]] || store_error "job ${job}: cycle through parent ${cur}"
      visiting["${cur}"]=1
      chain+=("${cur}")
      cur="${parents[${cur}]}"
    done
    for cur in "${chain[@]}"; do finished["${cur}"]=1; done
  done
  for name in "${!semaphore_names[@]}"; do
    oid="${REF_OID["${NS}/sem/${name}/meta"]:-}"
    [[ -n "${oid}" ]] || store_error "semaphore ${name}: missing capacity metadata"
    [[ -n "${REF_OID["${NS}/sem/${name}/gen"]:-}" ]] || store_error "semaphore ${name}: missing generation"
    ((${live_counts[${name}]:-0} <= ${R_FIELD["${oid} capacity"]})) || store_error "semaphore ${name}: live slots exceed capacity"
  done
  check_path_overlaps reject_path_overlap "${at}" "${jobs[@]}"
}
