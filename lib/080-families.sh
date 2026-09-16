# ---------------------------------------------------------------- families
#
# A child records `parent: <job>`. The parent's record carries `family: <n>`,
# a generation that every child admission increments by rewriting the parent's
# blob and moving the parent's job ref and path refs to it. So membership is
# part of the parent's own compare-and-swap: a release or sweep that planned
# against the parent's old blob fails when a child was admitted meanwhile, and
# re-plans with the child in view. A child cannot outlive its parent.

descendants() {   # job... -> DESC: every job whose parent chain reaches one of them (transitively), sorted
  ensure_snapshot # in this shell, so the $(…) reads below inherit one fresh snapshot instead of each taking their own
  DESC=()
  local rows ref oid rjob rparent changed=1 seeds=("$@") j
  rows="$(job_refs)"
  local all_jobs=() all_parents=()
  while IFS=' ' read -r ref oid; do
    [[ -z "${ref}" ]] && continue
    field_v rjob "${oid}" job
    field_v rparent "${oid}" parent
    all_jobs+=("${rjob}")
    all_parents+=("${rparent}")
  done <<<"${rows}"
  local family=("${seeds[@]}") i
  while ((changed)); do
    changed=0
    for i in "${!all_jobs[@]}"; do
      [[ -z "${all_parents[${i}]}" ]] && continue
      in_list "${all_jobs[${i}]}" "${family[@]}" && continue
      if in_list "${all_parents[${i}]}" "${family[@]}"; then
        family+=("${all_jobs[${i}]}")
        changed=1
      fi
    done
  done
  for j in "${family[@]}"; do
    in_list "${j}" "${seeds[@]}" || DESC+=("${j}")
  done
  if ((${#DESC[@]} > 0)); then
    local sorted
    sorted="$(printf '%s\n' "${DESC[@]}" | sort)"
    DESC=()
    while IFS= read -r j; do [[ -n "${j}" ]] && DESC+=("${j}"); done <<<"${sorted}"
  fi
}

plan_delete_job() { # job -> plans deletes for its job ref and the path refs still pointing at it; DELETED_PATHS = how many
  ensure_snapshot   # in this shell, so the $(…) reads below inherit one fresh snapshot instead of each taking their own
  local jref oid p ref have paths count=0
  DELETED_PATHS=0
  jref="$(job_ref "$1")"
  oid="$(ref_oid "${jref}")"
  [[ -n "${oid}" ]] || return 0
  plan_set "${jref}" "${oid}" '' || return 1
  paths="$(record_paths "${oid}")"
  while IFS= read -r p; do
    [[ -z "${p}" ]] && continue
    path_ref ref "${p}"
    have="$(ref_oid "${ref}")"
    if [[ "${have}" == "${oid}" ]]; then
      plan_set "${ref}" "${oid}" '' || return 1
      count=$((count + 1))
    fi
  done <<<"${paths}"
  DELETED_PATHS="${count}"
}

plan_terminate() { # job -> plans the deletion of the job and every descendant; TERMINATED_PATHS, TERMINATED_CASCADE (json array)
  local d n
  descendants "$1"
  plan_delete_job "$1" || return 1
  n="${DELETED_PATHS}"
  for d in "${DESC[@]}"; do
    plan_delete_job "${d}" || return 1
    n=$((n + DELETED_PATHS))
  done
  TERMINATED_PATHS="${n}"
  json_jobs TERMINATED_CASCADE "${DESC[@]}"
}

new_acquisition() { # VAR: a fresh acquisition id. The record oid changes on every rewrite (renewal, family bump);
  local at          # this id does not, so a caller can name the acquisition it made across renewals.
  now_v at
  printf -v "$1" '%s-%05d-%05d%05d' "${at}" "$$" "${RANDOM}" "${RANDOM}"
}

record_text() { # VAR job holder claimed expires parent family acquisition paths-newline-separated [note]
  local body
  body="$(
    printf 'schema: %s\njob: %s\nholder: %s\nclaimed: %s\nexpires: %s\n' "${SCHEMA}" "$2" "$3" "$4" "$5"
    [[ -n "$6" ]] && printf 'parent: %s\n' "$6"
    printf 'family: %s\nacquisition: %s\n' "$7" "$8"
    [[ -n "${10:-}" ]] && printf 'note: %s\n' "${10}"
    printf 'paths:\n%s' "$9"
  )"
  printf -v "$1" '%s' "${body}"
}

bump_parent() {   # parent-job parent-oid -> plans the parent's blob rewrite with family+1 on its job ref and path refs
  ensure_snapshot # in this shell, so the $(…) reads below inherit one fresh snapshot instead of each taking their own
  local pjob="$1" poid="$2" fam newfam claimed expires holder parent paths record newoid p ref have acq note
  fam="$(field "${poid}" family)"
  acq="$(field "${poid}" acquisition)"
  newfam=$((${fam:-0} + 1))
  holder="$(field "${poid}" holder)"
  claimed="$(field "${poid}" claimed)"
  expires="$(field "${poid}" expires)"
  parent="$(field "${poid}" parent)"
  paths="$(record_paths "${poid}")"
  field_v note "${poid}" note
  record_text record "${pjob}" "${holder}" "${claimed}" "${expires}" "${parent}" "${newfam}" "${acq}" "${paths}" "${note}"
  write_blob newoid "${record}" || fail 'could not write the parent record'
  local pjref
  pjref="$(job_ref "${pjob}")"
  plan_set "${pjref}" "${poid}" "${newoid}" || return 1
  while IFS= read -r p; do
    [[ -z "${p}" ]] && continue
    path_ref ref "${p}"
    have="$(ref_oid "${ref}")"
    [[ "${have}" == "${poid}" ]] && { plan_set "${ref}" "${poid}" "${newoid}" || return 1; }
  done <<<"${paths}"
  return 0
}
