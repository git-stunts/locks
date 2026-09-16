# ---------------------------------------------------------------- refusals

refusal() { # path, after describe(): one refusal line on stderr
  local _j1 _j2 _j3
  json_str _j1 "$1"
  json_str _j2 "${D_HOLDER}"
  json_str _j3 "${D_JOB}"
  printf '{"event":"refused","path":%s,"holder":%s,"job":%s,"expires":%s}\n' "${_j1}" "${_j2}" "${_j3}" "${D_EXPIRES}" >&2
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
