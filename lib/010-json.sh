# ---------------------------------------------------------------- JSON

json_str() { # VAR VALUE: set VAR to VALUE as a JSON string, every control character escaped
  local s="$2" out='' i c code
  s="${s//\\/\\\\}"
  s="${s//\"/\\\"}"
  if [[ "${s}" == *[[:cntrl:]]* ]]; then
    for ((i = 0; i < ${#s}; i++)); do
      c="${s:i:1}"
      case "${c}" in
        $'\n') out+='\n' ;;
        $'\r') out+='\r' ;;
        $'\t') out+='\t' ;;
        [[:cntrl:]])
          printf -v code '%d' "'${c}"
          printf -v c '\\u%04x' "${code}"
          out+="${c}"
          ;;
        *) out+="${c}" ;;
      esac
    done
    s="${out}"
  fi
  printf -v "$1" '"%s"' "${s}"
}

json_paths() { # VAR: set VAR to a JSON array of the lines on stdin
  local line items=() one IFS
  while IFS= read -r line; do
    if [[ -n "${line}" ]]; then
      json_str one "${line}"
      items+=("${one}")
    fi
  done
  IFS=','
  printf -v "$1" '[%s]' "${items[*]}"
}

json_paths_v() { # VAR TEXT: set VAR to a JSON array of TEXT's non-empty lines; no fork (locals underscored so none can shadow VAR)
  local _jp_text="$2" _jp_line _jp_items=() _jp_one IFS
  while [[ -n "${_jp_text}" ]]; do
    _jp_line="${_jp_text%%$'\n'*}"
    if [[ "${_jp_line}" == "${_jp_text}" ]]; then _jp_text=''; else _jp_text="${_jp_text#*$'\n'}"; fi
    if [[ -n "${_jp_line}" ]]; then
      json_str _jp_one "${_jp_line}"
      _jp_items+=("${_jp_one}")
    fi
  done
  IFS=','
  printf -v "$1" '[%s]' "${_jp_items[*]}"
}

json_jobs() { # VAR job... -> JSON array of job ids
  local var="$1" one items=() IFS j
  shift
  for j in "$@"; do
    json_str one "${j}"
    items+=("${one}")
  done
  IFS=','
  printf -v "${var}" '[%s]' "${items[*]}"
}

parent_json() { # VAR oid -> ',"parent":"<id>"' or '' when the record has no parent
  local p one
  field_v p "$2" parent
  if [[ -n "${p}" ]]; then
    json_str one "${p}"
    printf -v "$1" ',"parent":%s' "${one}"
  else
    printf -v "$1" ''
  fi
}
