# ---------------------------------------------------------------- the snapshot
#
# One for-each-ref and one cat-file --batch per invocation; every reader below
# comes from these two arrays. A read that fails, or an object that does not
# parse, is a store error: it is never reported as "free". Every transaction
# invalidates the snapshot; the next read takes a fresh one. A snapshot is a
# cached read taken under one for-each-ref, not a proof of a consistent cut;
# every write below carries the expectations that make a stale read fail.

declare -A REF_OID=()  # ref -> oid
declare -A BLOB=()     # oid -> record text
declare -A R_FIELDS=() # oid -> "key\x1fvalue\x1e..." for the header lines before paths:
declare -A R_PATHS=()  # oid -> the path lines, newline separated
SNAP_LOADED=0

parse_record() { # oid -> fills R_FIELDS[oid] and R_PATHS[oid] from BLOB[oid], once per shell; parameter expansion only, no fork
  [[ -n "${R_FIELDS[$1]+x}" ]] && return 0
  local text="${BLOB[$1]:-}" line fields='' paths='' in_paths=0
  while [[ -n "${text}" ]]; do
    line="${text%%$'\n'*}"
    if [[ "${line}" == "${text}" ]]; then text=''; else text="${text#*$'\n'}"; fi
    if ((in_paths)); then
      paths+="${line}"$'\n'
    elif [[ "${line}" == 'paths:' ]]; then
      in_paths=1
    elif [[ "${line}" == *': '* ]]; then
      fields+="${line%%: *}"$'\x1f'"${line#*: }"$'\x1e'
    fi
  done
  R_FIELDS["$1"]="${fields}"
  R_PATHS["$1"]="${paths%$'\n'}"
  [[ -n "${GIT_LOCKS_TRACE:-}" ]] && printf 'parse %s\n' "$1" >>"${GIT_LOCKS_TRACE}"
  return 0
}

snapshot() {
  local -A refs=() blobs=()
  local rows ref oid oids=() rc
  rows="$(g for-each-ref --format='%(refname) %(objectname)' "${NS}/" 2>&1)"
  rc=$?
  ((rc == 0)) || store_error "for-each-ref exited ${rc}: ${rows}"
  while IFS=' ' read -r ref oid; do
    [[ -z "${ref}" ]] && continue
    valid_oid "${oid}" || store_error "for-each-ref line does not parse: ${ref} ${oid}"
    refs["${ref}"]="${oid}"
    oids+=("${oid}")
  done <<<"${rows}"
  if ((${#oids[@]} > 0)); then
    local out
    out="$(printf '%s\n' "${oids[@]}" | sort -u | g cat-file --batch 2>&1 && printf x)" # the x keeps trailing newlines
    rc=$?
    ((rc == 0)) || store_error "cat-file --batch exited ${rc}: ${out%x}"
    out="${out%x}"
    local header size body nl
    # read -N over the captured text is linear; slicing ${out:pos:size} copies from pos every time and is quadratic in the store
    while IFS= read -r header; do
      [[ "${header}" =~ ^([0-9a-f]+)\ blob\ ([0-9]+)$ ]] || store_error "cat-file --batch header does not parse: ${header}"
      oid="${BASH_REMATCH[1]}"
      size="${BASH_REMATCH[2]}"
      body=''
      ((size > 0)) && { IFS= read -r -N "${size}" body || store_error "cat-file --batch object ${oid} is short"; }
      IFS= read -r -N 1 nl || nl=''
      [[ "${nl}" == $'\n' ]] || store_error "cat-file --batch object ${oid} is not newline terminated"
      blobs["${oid}"]="${body}"
    done <<<"${out%$'\n'}"
    for oid in "${oids[@]}"; do
      [[ -n "${blobs[${oid}]+x}" ]] || store_error "object ${oid} named by a ref is missing from the store"
    done
  fi
  REF_OID=()
  BLOB=()
  R_FIELDS=()
  R_PATHS=()
  for ref in "${!refs[@]}"; do REF_OID["${ref}"]="${refs[${ref}]}"; done
  for oid in "${!blobs[@]}"; do BLOB["${oid}"]="${blobs[${oid}]}"; done
  SNAP_LOADED=1
  [[ -n "${GIT_LOCKS_TRACE:-}" ]] && printf 'snapshot %s\n' "${#refs[@]}" >>"${GIT_LOCKS_TRACE}"
  test_gate "${GIT_LOCKS_PAUSE_AFTER_READ:-}" # tests force an interleaving between a read and what follows it
}

test_gate() { # file-or-empty: when set, wait here until the file exists (at most 30 s); tests only
  [[ -n "$1" ]] || return 0
  local waited=0
  until [[ -e "$1" ]] || ((waited >= 600)); do
    sleep 0.05
    waited=$((waited + 1))
  done
  return 0
}

ensure_snapshot() { ((SNAP_LOADED)) || snapshot; }

ref_oid() { # ref -> oid or empty
  ensure_snapshot
  printf '%s' "${REF_OID[$1]:-}"
}

field_v() { # VAR oid key: set VAR to the value of `key:` in the record's header (before paths:), empty when absent; no fork, so the parse memoises in this shell
  ensure_snapshot
  parse_record "$2"
  local _fv_fields="${R_FIELDS[$2]:-}" _fv_rest # underscored: a local named like the caller's VAR would swallow the printf -v
  if [[ "${_fv_fields}" == "$3"$'\x1f'* ]]; then
    _fv_rest="${_fv_fields#"$3"$'\x1f'}"
  elif [[ "${_fv_fields}" == *$'\x1e'"$3"$'\x1f'* ]]; then
    _fv_rest="${_fv_fields#*$'\x1e'"$3"$'\x1f'}"
  else
    printf -v "$1" ''
    return 0
  fi
  printf -v "$1" '%s' "${_fv_rest%%$'\x1e'*}"
}

field() { # oid key -> the value on stdout; inside $(…) the parse happens in the subshell, so hot paths use field_v
  local v
  field_v v "$1" "$2"
  printf '%s' "${v}"
}

record_paths_v() { # VAR oid: set VAR to the paths, newline separated; no fork
  ensure_snapshot
  parse_record "$2"
  printf -v "$1" '%s' "${R_PATHS[$2]:-}"
}

record_paths() { # oid -> paths, one per line
  local v
  record_paths_v v "$1"
  [[ -n "${v}" ]] && printf '%s\n' "${v}"
  return 0
}

refs_under() { # prefix -> "ref oid" lines, sorted by ref, from the snapshot
  ensure_snapshot
  local ref
  for ref in "${!REF_OID[@]}"; do
    [[ "${ref}" == "$1"* ]] && printf '%s %s\n' "${ref}" "${REF_OID[${ref}]}"
  done | sort
}

job_refs() { refs_under "${NS}/jobs/"; }

D_HOLDER=''
D_JOB=''
D_EXPIRES=0
D_REMAINING=0
D_STATE=''

describe() { # oid -> D_HOLDER D_JOB D_EXPIRES D_REMAINING D_STATE; no fork
  field_v D_HOLDER "$1" holder
  field_v D_JOB "$1" job
  local exp at
  field_v exp "$1" expires
  D_EXPIRES="${exp:-0}"
  now_v at
  D_REMAINING=$((D_EXPIRES - at))
  ((D_REMAINING < 0)) && D_REMAINING=0
  if ((D_EXPIRES > at)); then D_STATE='live'; else D_STATE='expired'; fi
}

in_list() { # needle list...
  local needle="$1" item
  shift
  for item in "$@"; do [[ "${item}" == "${needle}" ]] && return 0; done
  return 1
}

write_blob() {  # VAR CONTENT: write CONTENT as a blob, seed the snapshot with it, set VAR to its oid
  local written # not `oid`: printf -v writes to the caller's variable of that name, which a local would shadow
  written="$(printf '%s\n' "$2" | g hash-object -w --stdin)" || return 1
  ensure_snapshot
  BLOB["${written}"]="$2"$'\n'
  printf -v "$1" '%s' "${written}"
}
