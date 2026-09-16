# ---------------------------------------------------------------- store, main

cmd_store() {
  local _j1
  (($# == 0)) || usage
  json_str _j1 "${STORE}"
  printf '{"store":%s}\n' "${_j1}"
}

main() {
  (($# > 0)) || usage
  local cmd="$1" a line
  shift
  case "${cmd}" in
    help | --help | -h)
      usage_json line
      printf '%s\n' "${line}"
      exit 0
      ;;
    schema)
      cmd_schema "$@"
      exit 0
      ;;
    version | --version)
      (($# == 0)) || usage
      printf '{"name":"git-locks","version":"%s"}\n' "${VERSION}"
      exit 0
      ;;
    claim | batch | release | check | list | sweep | store | show | ttl | extend | with | sem | doctor) ;;
    *) usage ;;
  esac
  for a in "$@"; do
    [[ "${a}" == '--' ]] && break # what follows belongs to the wrapped command
    if [[ "${a}" == '--help' || "${a}" == '-h' ]]; then
      sub_usage "${cmd}"
      exit 0
    fi
  done
  resolve_store
  case "${cmd}" in store) ;; *) ensure_snapshot ;; esac # once, in this shell: subshells inherit it instead of re-reading
  "cmd_${cmd}" "$@"
}

main "$@"
