# ------------------------------------------------------- batched path identity

hash_paths() { # path... -> PATH_HASH for every path, in one git process: each path becomes a file, hash-object hashes them all
  local dir p i=0 files=() todo=() out h rc
  local -A queued=()
  for p in "$@"; do
    [[ -n "${PATH_HASH[${p}]+x}" ]] && continue
    [[ -n "${queued[${p}]+x}" ]] && continue
    queued["${p}"]=1
    todo+=("${p}")
  done
  ((${#todo[@]} > 0)) || return 0
  dir="$(mktemp -d "${TMPDIR:-/tmp}/git-locks-hashes.XXXXXX" 2>&1)" || store_error "cannot create temporary path-hashing storage: ${dir}"
  for p in "${todo[@]}"; do
    if ! { printf '%s' "${p}" >"${dir}/${i}"; } 2>/dev/null; then
      rm -rf -- "${dir}"
      store_error 'cannot write temporary path-hashing input'
    fi
    files+=("${i}")
    i=$((i + 1))
  done
  # Numeric filenames on stdin avoid command-line limits and quoting arbitrary
  # temporary directory names. --no-filters hashes the same bytes as path_ref.
  out="$(printf '%s\n' "${files[@]}" | g -C "${dir}" hash-object --no-filters --stdin-paths 2>&1)"
  rc=$?
  rm -rf -- "${dir}" || store_error 'cannot remove temporary path-hashing input'
  ((rc == 0)) || store_error "hash-object exited ${rc}: ${out}"
  i=0
  while IFS= read -r h; do
    [[ -z "${h}" ]] && continue
    valid_oid "${h}" || store_error "hash-object line does not parse: ${h}"
    ((i < ${#todo[@]})) || store_error 'hash-object returned too many path hashes'
    PATH_HASH["${todo[${i}]}"]="${h}"
    i=$((i + 1))
  done <<<"${out}"
  ((i == ${#todo[@]})) || store_error "hash-object returned ${i} hashes for ${#todo[@]} paths"
}
