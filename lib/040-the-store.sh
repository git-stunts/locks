# ---------------------------------------------------------------- the store

STORE=''

resolve_store() { # sets STORE; creates the default or a custom store on first use
  local common='' sel key
  common="$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" || common='' # empty outside a repository
  sel="${GIT_LOCKS_STORE:-}"
  if [[ -z "${sel}" ]]; then
    sel="$(git config --get locks.store 2>/dev/null)" || sel=''
  fi
  if [[ -n "${common}" ]]; then key="${common%/.git}"; else key="${PWD}"; fi # main repo when there is one, else the directory
  case "${sel}" in
    '') STORE="${GIT_LOCKS_HOME:-${HOME}/.git-stunts}/locks${key}" ;;
    self)
      [[ -n "${common}" ]] || fail 'GIT_LOCKS_STORE=self needs a git repository; this directory is not in one' 2
      STORE="${common}"
      ;;
    /*) STORE="${sel}" ;;
    *) STORE="${PWD}/${sel}" ;;
  esac
  if [[ "${STORE}" != "${common}" && ! -f "${STORE}/HEAD" ]]; then # a repository, bare or not, has a HEAD
    mkdir -p "${STORE}" || fail "cannot create the lock store at ${STORE}" 2
    git init -q --bare "${STORE}" || fail "cannot initialise the lock store at ${STORE}" 2
  fi
}

g() { git --git-dir="${STORE}" "$@"; }
