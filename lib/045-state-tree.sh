# ------------------------------------------------------- immutable state trees
#
# refs/locks/state is the only mutable authority. Its tree contains the logical
# job/path/directory/semaphore entries previously stored in individual refs.
# Reading one OID pins every membership and absence decision to the same state.
# Git trees share unchanged subtrees; a private Git index builds the successor.
# Publication compares the root, including entries the planner did not touch.

STATE_REF="${NS}/state"
STATE_OID=''
SNAP_LEGACY_ALLOWED=0 # only the explicitly offline migration may read old refs

state_tree() ( # writes the planned successor tree; cleanup stays in its subshell
  local dir ref before after path STORE_INDEX
  dir="$(mktemp -d "${TMPDIR:-/tmp}/git-locks-index.XXXXXX")" || return 1
  trap 'rm -rf "${dir}"' EXIT
  STORE_INDEX="${dir}/index"
  if [[ -n "${STATE_OID}" ]]; then
    g read-tree "${STATE_OID}" || return 1
  else
    g read-tree --empty || return 1
  fi
  for ref in "${PLAN_ORDER[@]}"; do
    before="${T_BEFORE[${ref}]}"
    after="${T_AFTER[${ref}]}"
    [[ "${REF_OID[${ref}]:-}" == "${before}" ]] || {
      printf 'plan expectation differs from its snapshot: %s\n' "${ref}" >&2
      return 1
    }
    [[ "${after}" == '=' ]] && continue
    path="${ref#"${NS}"/}"
    if [[ -z "${after}" ]]; then
      [[ -n "${before}" ]] || continue
      printf '0 %s\t%s\n' "${before//?/0}" "${path}"
    else
      printf '100644 %s\t%s\n' "${after}" "${path}"
    fi
  done >"${dir}/changes"
  g update-index --index-info <"${dir}/changes" || return 1
  g write-tree
)
