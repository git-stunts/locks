# ---------------------------------------------------------- offline migration
# Old clients do not share the new root CAS. There is no safe online import:
# --offline is the operator's assertion that every old reader/writer is stopped.

cmd_migrate() {
  [[ $# == 1 && "$1" == --offline ]] || fail 'migration requires stopped writers: git locks migrate --offline' 2
  shift
  SNAP_LEGACY_ALLOWED=1
  snapshot
  local diagnostic ref next rc result
  diagnostic="$(cmd_doctor "$@")" || store_error "legacy state is unhealthy; repair with the old client before migration: ${diagnostic}"
  if [[ -n "${STATE_OID}" ]]; then
    next="${STATE_OID}"
  else
    plan_reset
    for ref in "${!REF_OID[@]}"; do
      plan_set "${ref}" "${REF_OID[${ref}]}" "${REF_OID[${ref}]}"
    done
    next="$(state_tree 2>&1)" || store_write_error "could not build the migrated state tree: ${next}"
    result="$(
      {
        printf 'start\ncreate %s %s\n' "${STATE_REF}" "${next}"
        for ref in "${!REF_OID[@]}"; do
          printf 'delete %s %s\n' "${ref}" "${REF_OID[${ref}]}"
        done
        printf 'prepare\ncommit\n'
      } | g -c core.filesRefLockTimeout=0 -c core.packedRefsTimeout=0 update-ref --stdin 2>&1
    )"
    rc=$?
    ((rc == 0)) || store_write_error "offline migration failed: ${result}"
  fi
  printf '{"event":"migrated","format":"git-locks-state/1","root":"%s","entries":%s}\n' "${next}" "${#REF_OID[@]}"
}
