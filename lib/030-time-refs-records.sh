# ---------------------------------------------------------------- time, refs, records

now_v() { # VAR: set VAR to the clock, read once per invocation; no fork after the first call
  if [[ -z "${NOW_CACHED}" ]]; then
    if [[ -n "${GIT_LOCKS_NOW:-}" ]]; then
      NOW_CACHED="${GIT_LOCKS_NOW}"
    else
      NOW_CACHED="$(date +%s)"
    fi
  fi
  printf -v "$1" '%s' "${NOW_CACHED}"
}

now() {
  local v
  now_v v
  printf '%s' "${v}"
}

declare -A PATH_HASH=() # path -> git's hash of the path string, memoised per invocation

path_ref() { # VAR path: set VAR to the path's ref; the hash is memoised in this shell (never call inside $(…))
  local h
  if [[ -z "${PATH_HASH[$2]+x}" ]]; then
    h="$(printf '%s' "$2" | g hash-object --stdin)" || return 1
    PATH_HASH["$2"]="${h}"
  fi
  printf -v "$1" '%s/paths/%s' "${NS}" "${PATH_HASH[$2]}"
}

job_ref() { printf '%s/jobs/%s' "${NS}" "$1"; }

valid_job() { [[ "$1" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]; }

valid_holder() { [[ -n "$1" && "$1" != *$'\n'* && "$1" != *$'\r'* ]]; } # one line: the record is line-oriented; any other byte is stored whole and escaped on output

valid_ttl() { # VAR value: VAR = the value as a decimal number of seconds; 1 unless it is digits only and positive (010 is ten, never octal eight)
  [[ "$2" =~ ^[0-9]+$ ]] || return 1
  local _vt=$((10#$2))
  ((_vt > 0)) || return 1
  printf -v "$1" '%s' "${_vt}"
}

valid_oid() { [[ "$1" =~ ^[0-9a-f]{40}([0-9a-f]{24})?$ ]]; }

path_error() { # detail -> a usage error line on stderr (the caller returns 2)
  local _j1
  json_str _j1 "$1"
  printf '{"event":"error","reason":"usage","detail":%s}\n' "${_j1}" >&2
}

normalize_path() { # -> prints the lexical form, or returns 2 with the reason on stderr
  # Policy, stated: leading ./, empty segments (//), single-dot segments and a
  # trailing / are removed; absolute paths and .. segments are refused; case,
  # symlinks and hard links are NOT resolved. dir/ and dir/file are different keys.
  local p="$1" part parts=() IFS='/'
  [[ "${p}" == /* ]] && {
    path_error "${p}: paths are repo-relative"
    return 2
  }
  [[ "${p}" == *$'\n'* ]] && {
    path_error 'a path with a newline is not supported'
    return 2
  }
  for part in ${p}; do
    [[ -z "${part}" || "${part}" == '.' ]] && continue
    [[ "${part}" == '..' ]] && {
      path_error "${p}: no .. components"
      return 2
    }
    parts+=("${part}")
  done
  ((${#parts[@]} > 0)) || {
    path_error 'an empty path'
    return 2
  }
  printf '%s' "${parts[*]}"
}
