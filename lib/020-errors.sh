# ---------------------------------------------------------------- errors

fail() { # message [code]: an error line on stderr, then exit (2 is usage, 1 is a failed operation)
  local code="${2:-1}" reason _j1
  if ((code == 2)); then reason='usage'; else reason='failed'; fi
  json_str _j1 "$1"
  printf '{"event":"error","reason":"%s","detail":%s}\n' "${reason}" "${_j1}" >&2
  exit "${code}"
}

store_error() { # detail: the store could not be read; nothing is reported as free or held
  local _j1
  json_str _j1 "$1"
  printf '{"event":"error","reason":"store-read","detail":%s}\n' "${_j1}" >&2
  exit 2
}
