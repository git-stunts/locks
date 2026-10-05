# ---------------------------------------------------------------- explicit test instrumentation

test_hooks_enabled() { [[ "${GIT_LOCKS_TEST_HOOKS:-}" == 1 ]]; }

validate_test_hooks() {
  if ! test_hooks_enabled && [[ -n "${GIT_LOCKS_NOW+x}${GIT_LOCKS_TRACE+x}${GIT_LOCKS_PAUSE_AFTER_READ+x}${GIT_LOCKS_PAUSE_BEFORE_COMMIT+x}" ]]; then
    fail 'test controls require GIT_LOCKS_TEST_HOOKS=1; unset them for normal use' 2
  fi
}
