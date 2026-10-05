# ---------------------------------------------------------------- time, refs, records

system_now_v() { # VAR: one validated system-clock sample; errors return to the caller for cleanup
  local _sn_clock
  _sn_clock="$(date +%s 2>&1)" || {
    clock_error "could not read the system clock: ${_sn_clock}"
    return 2
  }
  decimal_uint "$1" "${_sn_clock}" || {
    clock_error 'system clock must return a nonnegative signed 64-bit decimal epoch'
    return 2
  }
}

now_v() { # VAR: one validated clock value per snapshot; replanning refreshes it
  if [[ -z "${NOW_CACHED}" ]]; then
    if test_hooks_enabled && [[ -n "${GIT_LOCKS_NOW+x}" ]]; then
      NOW_CACHED="${GIT_LOCKS_NOW}"
    else
      system_now_v NOW_CACHED || exit 2
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
    h="$(printf '%s' "$2" | g hash-object --stdin 2>&1)" || store_error "could not hash a path: ${h}"
    valid_oid "${h}" || store_error "hash-object returned an invalid path id: ${h}"
    PATH_HASH["$2"]="${h}"
  fi
  printf -v "$1" '%s/paths/%s' "${NS}" "${PATH_HASH[$2]}"
}

job_ref() { printf '%s/jobs/%s' "${NS}" "$1"; }

valid_job() { [[ "$1" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]; }

valid_holder() { [[ -n "$1" && "$1" != *$'\n'* && "$1" != *$'\r'* ]]; } # one line: the record is line-oriented; any other byte is stored whole and escaped on output

valid_note() { [[ "$1" != *$'\n'* && "$1" != *$'\r'* ]]; } # one line; empty means no note

valid_ttl() { # VAR value: VAR = the value as a decimal number of seconds; 1 unless it is digits only and positive (010 is ten, never octal eight)
  decimal_uint "$1" "$2" && [[ "${!1}" != 0 ]]
}

valid_oid() { [[ "$1" =~ ^[0-9a-f]{40}([0-9a-f]{24})?$ ]]; }

path_error() { # detail -> a usage error line on stderr (the caller returns 2)
  local _j1
  json_str _j1 "$1"
  printf '{"event":"error","reason":"usage","detail":%s}\n' "${_j1}" >&2
}

normalize_path() { # -> prints the lexical form, or returns 2 with the reason on stderr
  # Policy, stated: leading ./, empty segments (//) and single-dot segments are
  # removed; absolute paths and .. segments are refused; case, symlinks and hard
  # links are NOT resolved. A trailing / is kept: dir/ is a prefix that covers
  # every path under it; dir is the directory entry itself, a different key.
  local p="$1" part parts=() raw_parts=() IFS='/' prefix=''
  [[ "${p}" == */ ]] && prefix='/'
  [[ "${p}" == /* ]] && {
    path_error "${p}: paths are repo-relative"
    return 2
  }
  [[ "${p}" == *$'\n'* ]] && {
    path_error 'a path with a newline is not supported'
    return 2
  }
  [[ -n "${p}" ]] || { # before the split: bash < 4.4 calls an empty array unbound under set -u
    path_error 'an empty path'
    return 2
  }
  read -r -a raw_parts <<<"${p}" # split on / without globbing: * ? [ ] are bytes of the name
  for part in "${raw_parts[@]}"; do
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
  printf '%s%s' "${parts[*]}" "${prefix}"
}

is_prefix() { [[ "$1" == */ ]]; } # a normalised path that names everything under it

covers() { # a b -> 0 when a is a prefix lock holding b (never itself)
  is_prefix "$1" && [[ "$2" == "$1"?* ]]
}

ancestors_v() { # VAR path: set VAR to the prefixes above a normalised path, shortest first, newline separated (a/b/c.md -> a/ a/b/; a/b/ -> a/; c.md -> nothing)
  local _an_p="$2" _an_acc='' _an_out='' _an_seg
  _an_p="${_an_p%/}"
  if [[ "${_an_p}" != */* ]]; then
    printf -v "$1" ''
    return 0
  fi
  _an_p="${_an_p%/*}"
  while [[ -n "${_an_p}" ]]; do
    _an_seg="${_an_p%%/*}"
    if [[ "${_an_seg}" == "${_an_p}" ]]; then _an_p=''; else _an_p="${_an_p#*/}"; fi
    _an_acc+="${_an_seg}/"
    _an_out+="${_an_acc}"$'\n'
  done
  printf -v "$1" '%s' "${_an_out%$'\n'}"
}

dir_ref() { # VAR prefix: the directory token ref for a prefix; every claim that touches the directory moves it, so a
  local _dr # prefix claim's scan of what is under it and a path claim's check of what is above it cannot both be stale
  path_ref _dr "$2" || return 1
  printf -v "$1" '%s/dirs/%s' "${NS}" "${_dr##*/}"
}
