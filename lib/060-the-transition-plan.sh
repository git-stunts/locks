# ---------------------------------------------------------------- the transition plan
#
# One final transition per ref. Every writer says what it expects a ref to hold
# now (an oid, or absent) and what it should hold after (an oid, absent, or the
# same: a verify). Two statements about one ref must agree on the expectation;
# a later statement may only sharpen an earlier verify into a change. Anything
# else is a contradiction found here, in planning, never by git.

declare -A T_BEFORE=() # ref -> expected current oid, or '' for absent
declare -A T_AFTER=()  # ref -> resulting oid, '' for delete, '=' for verify only
PLAN_ORDER=()
PLAN_CONFLICT=''

plan_reset() {
  T_BEFORE=()
  T_AFTER=()
  PLAN_ORDER=()
  PLAN_CONFLICT=''
}

plan_set() { # ref before after -> 0, or 1 with PLAN_CONFLICT set
  local ref="$1" before="$2" after="$3"
  if [[ -z "${T_BEFORE[${ref}]+x}" ]]; then
    T_BEFORE["${ref}"]="${before}"
    T_AFTER["${ref}"]="${after}"
    PLAN_ORDER+=("${ref}")
    return 0
  fi
  if [[ "${T_BEFORE[${ref}]}" != "${before}" ]]; then
    PLAN_CONFLICT="two expectations for ${ref}"
    return 1
  fi
  local have="${T_AFTER[${ref}]}"
  if [[ "${have}" == '=' ]]; then
    T_AFTER["${ref}"]="${after}"
    return 0
  fi
  [[ "${after}" == '=' || "${after}" == "${have}" ]] && return 0
  PLAN_CONFLICT="two transitions for ${ref}"
  return 1
}

TRANSACT_ERR=''

publication_conflict() { # only Git's old-value mismatch can request a new plan
  if [[ -n "${STATE_OID}" ]]; then
    [[ "${TRANSACT_ERR}" == *"cannot lock ref '${STATE_REF}': is at "*" but expected ${STATE_OID}"* ]]
  else
    [[ "${TRANSACT_ERR}" == *"cannot lock ref '${STATE_REF}': reference already exists"* ]]
  fi
}

publication_lock_busy() { # a files-backend ref lock may belong to an active publisher
  [[ "${TRANSACT_ERR}" == *"cannot lock ref '${STATE_REF}': Unable to create "*"${STATE_REF}.lock': File exists."* ]]
}

transact() { # success, stale snapshot (return 1), or operational error (exit 2)
  local next rc lock_try
  next="$(state_tree 2>&1)" || store_write_error "could not build the successor state tree: ${next}"
  valid_oid "${next}" || store_write_error 'invalid successor state object id'
  test_gate "${GIT_LOCKS_PAUSE_BEFORE_COMMIT:-}" # tests force an interleaving between planning and commit
  # Git does not identify a .lock file's owner. Briefly retry the SAME candidate
  # to allow an active publisher to finish; never delete its lock or keep
  # rebuilding records while a possibly abandoned lock remains in place.
  for ((lock_try = 0; lock_try < 6; lock_try++)); do
    TRANSACT_ERR="$(
      {
        printf 'start\n'
        if [[ -n "${STATE_OID}" ]]; then
          printf 'update %s %s %s\n' "${STATE_REF}" "${next}" "${STATE_OID}"
        else
          printf 'create %s %s\n' "${STATE_REF}" "${next}"
        fi
        printf 'prepare\ncommit\n'
      } | g -c core.filesRefLockTimeout=0 -c core.packedRefsTimeout=0 update-ref --no-deref --stdin 2>&1
    )"
    rc=$?
    SNAP_LOADED=0
    ((rc == 0)) && return 0
    publication_conflict && return 1
    if publication_lock_busy && ((lock_try < 5)); then
      sleep 0.02
      continue
    fi
    store_write_error "could not publish the state root: ${TRANSACT_ERR}"
  done
}
