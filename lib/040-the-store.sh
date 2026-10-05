# ---------------------------------------------------------------- the store

STORE=''
STORE_INDEX='' # only state_tree may select the private index used by store Git

store_git() ( # isolate store plumbing; subject discovery and wrapped commands keep the caller's environment
  local name
  for name in "${!GIT_@}"; do
    case "${name}" in GIT_LOCKS_*) ;; *) unset "${name}" ;; esac
  done
  export GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null
  export GIT_NO_REPLACE_OBJECTS=1 GIT_NO_LAZY_FETCH=1 GIT_ALLOW_PROTOCOL='' GIT_TERMINAL_PROMPT=0
  [[ -z "${STORE_INDEX}" ]] || export GIT_INDEX_FILE="${STORE_INDEX}"
  exec git "$@"
)

outside_repository() { # accept only Git's ordinary absence, never a failed repository discovery
  [[ -z "${GIT_DIR+x}${GIT_COMMON_DIR+x}${GIT_WORK_TREE+x}" ]] || return 1
  case "$1" in
    'fatal: not a git repository (or any of the parent directories): .git') ;;
    'fatal: not a git repository (or any parent up to mount point '*$'\n''Stopping at filesystem boundary (GIT_DISCOVERY_ACROSS_FILESYSTEM not set).') ;;
    *) return 1 ;;
  esac
  # Git can report ordinary absence when HEAD or other repository metadata is
  # damaged. Never choose a new directory-based authority beside that metadata.
  local dir
  dir="$(pwd -P && printf x)" || return 1
  dir="${dir%x}"
  dir="${dir%$'\n'}"
  [[ "${dir}" != *$'\n'* ]] || return 1
  while :; do
    [[ ! -e "${dir}/.git" && ! -L "${dir}/.git" ]] || return 1
    if [[ -e "${dir}/HEAD" || -L "${dir}/HEAD" ]]; then
      [[ ! -e "${dir}/objects" && ! -e "${dir}/refs" && ! -e "${dir}/config" ]] || return 1
    fi
    [[ "${dir}" != / ]] || break
    dir="${dir%/*}"
    [[ -n "${dir}" ]] || dir=/
  done
}

resolve_store() { # sets STORE; creates the default or a custom store on first use
  local common='' sel key rc home_root
  # The sentinel preserves trailing newlines in paths, so they can be refused
  # instead of silently selecting a different path after command substitution.
  common="$(git rev-parse --path-format=absolute --git-common-dir 2>&1 && printf x)"
  rc=$?
  if ((rc == 0)); then
    common="${common%x}"
    common="${common%$'\n'}"
    [[ "${common}" == /* && "${common}" != *$'\n'* ]] || store_error 'invalid subject repository path'
  else
    if ((rc != 128)) || ! outside_repository "${common}"; then
      store_error "cannot discover the subject repository: ${common}"
    fi
    common=''
  fi
  sel="${GIT_LOCKS_STORE:-}"
  if [[ -z "${sel}" ]]; then
    sel="$(git config --get locks.store 2>&1 && printf x)"
    rc=$?
    if ((rc == 0)); then
      sel="${sel%x}"
      sel="${sel%$'\n'}"
    else
      [[ ${rc} == 1 && -z "${sel}" ]] || store_error "cannot read locks.store: ${sel}"
    fi
  fi
  [[ "${sel}" != *$'\n'* ]] || store_error 'the store selector must not contain a newline'
  if [[ -n "${common}" ]]; then
    # The shared anchor is the same as the default store's identity. Ordinary
    # and linked worktrees use the main repository top level; bare/separate
    # metadata layouts use the common Git directory itself.
    key="${common%/.git}"
  else
    key="$(pwd -P && printf x)" || store_error 'cannot resolve the working directory'
    key="${key%x}"
    key="${key%$'\n'}"
  fi
  case "${sel}" in
    '')
      home_root="${GIT_LOCKS_HOME:-${HOME}/.git-stunts}"
      [[ "${home_root}" == /* ]] || home_root="${key}/${home_root}"
      STORE="${home_root}/locks${key}"
      ;;
    self)
      [[ -n "${common}" ]] || fail 'GIT_LOCKS_STORE=self needs a git repository; this directory is not in one' 2
      STORE="${common}"
      ;;
    /*) STORE="${sel}" ;;
    *) STORE="${key}/${sel}" ;;
  esac
  [[ "${STORE}" != *$'\n'* ]] || store_error 'the store path must not contain a newline'
  # A trailing slash must not turn a missing destination into mv's directory form.
  while [[ "${STORE}" != / && "${STORE}" == */ ]]; do STORE="${STORE%/}"; done
  if [[ ! -e "${STORE}" && ! -L "${STORE}" ]]; then
    create_store || exit 2
  fi
  validate_store "${common}"
}

validate_store() { # common Git dir, or empty outside a repository
  local result
  [[ -d "${STORE}" && -f "${STORE}/HEAD" && -d "${STORE}/objects" ]] || store_error "not a Git lock store: ${STORE}; choose a missing path or an existing bare repository"
  result="$(g rev-parse --is-bare-repository 2>&1)" || store_error "cannot open the lock store at ${STORE}: ${result}"
  [[ "${STORE}" == "$1" || "${result}" == true ]] || store_error "the lock store must be bare; use self to share the subject repository"
}

create_store() ( # private initialization; publish a complete directory on this filesystem
  local store_parent="${STORE%/*}" prepared='' result nested
  result="$(mkdir -p -- "${store_parent}" 2>&1)" || store_write_error "cannot create the lock store parent: ${result}"
  prepared="$(mktemp -d "${store_parent}/.git-locks.init.XXXXXXXX" 2>&1)" || store_write_error "cannot prepare the lock store: ${prepared}"
  trap 'rm -rf -- "${prepared}"' EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
  # No templates: a user template may contain hooks or refs, neither of which
  # belongs in a newly allocated reservation store.
  result="$(store_git -c core.hooksPath=/dev/null -c core.fsmonitor=false init -q --bare --object-format=sha1 --template= "${prepared}" 2>&1)" || store_write_error "cannot initialize the lock store: ${result}"
  # Another initializer may already have published while Git was preparing ours.
  [[ -e "${STORE}" || -L "${STORE}" ]] && return 0
  # GNU and BSD mv support -n. If another initializer wins between the check and
  # rename, mv may place our unique directory INSIDE its completed store. Remove
  # only that owned directory, then the caller validates the winning store.
  result="$(mv -n -- "${prepared}" "${STORE}" 2>&1)" || store_write_error "cannot publish the lock store: ${result}"
  nested="${STORE}/${prepared##*/}"
  if [[ ! -e "${prepared}" && -d "${nested}" ]]; then
    result="$(rm -rf -- "${nested}" 2>&1)" || store_write_error "cannot remove the unused initialization directory: ${result}"
  fi
)

g() { store_git -c core.hooksPath=/dev/null -c core.fsmonitor=false --git-dir="${STORE}" "$@"; }
