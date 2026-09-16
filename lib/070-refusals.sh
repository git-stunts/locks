# ---------------------------------------------------------------- refusals

refusal() { # path [via], after describe(): one refusal line on stderr; via names the lock's own path when it differs (a prefix over the path, or a path under a wanted prefix)
  local _j1 _j2 _j3 _jv=''
  json_str _j1 "$1"
  json_str _j2 "${D_HOLDER}"
  json_str _j3 "${D_JOB}"
  if [[ -n "${2:-}" ]]; then
    json_str _jv "$2"
    _jv=",\"via\":${_jv}"
  fi
  printf '{"event":"refused","path":%s,"holder":%s%s,"job":%s%s,"expires":%s}\n' "${_j1}" "${_j2}" "${D_NOTE_JSON}" "${_j3}" "${_jv}" "${D_EXPIRES}" >&2
}

parent_refusal() { # child parent detail
  local _j1 _j2
  json_str _j1 "$1"
  json_str _j2 "$2"
  printf '{"event":"refused","reason":"parent","job":%s,"parent":%s,"detail":"%s"}\n' "${_j1}" "${_j2}" "$3" >&2
}

duplicate_refusal() { # path named twice within one plan
  local _j1
  json_str _j1 "$1"
  printf '{"event":"refused","reason":"duplicate","path":%s}\n' "${_j1}" >&2
}

transaction_refusal() { # git's words, as one line
  local _j1
  json_str _j1 "${TRANSACT_ERR}"
  printf '{"event":"refused","reason":"transaction","detail":%s}\n' "${_j1}" >&2
}
