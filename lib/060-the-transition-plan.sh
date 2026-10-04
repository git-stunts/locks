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

transact() { # root CAS: success or a stale snapshot that the caller must replan
  local next rc
  next="$(state_tree 2>&1)" || store_write_error "could not build the successor state tree: ${next}"
  valid_oid "${next}" || store_write_error 'invalid successor state object id'
  test_gate "${GIT_LOCKS_PAUSE_BEFORE_COMMIT:-}" # tests force an interleaving between planning and commit
  TRANSACT_ERR="$(
    {
      printf 'start\n'
      if [[ -n "${STATE_OID}" ]]; then
        printf 'update %s %s %s\n' "${STATE_REF}" "${next}" "${STATE_OID}"
      else
        printf 'create %s %s\n' "${STATE_REF}" "${next}"
      fi
      printf 'prepare\ncommit\n'
    } | g update-ref --stdin 2>&1
  )"
  rc=$?
  SNAP_LOADED=0
  ((rc == 0))
}
