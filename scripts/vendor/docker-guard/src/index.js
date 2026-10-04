/**
 * @fileoverview Docker-only guard utilities for git-stunts packages.
 */

const GUARD_BANNER = [
  '============================================================',
  '🚫 CRITICAL SAFETY ERROR: HOST EXECUTION PROHIBITED',
  '============================================================'
].join('\n');

const GUARD_MESSAGE_BODY = [
  '',
  'This project manipulates Git internals and performs heavy',
  'benchmarking that can corrupt your repository or system.',
  '',
  'YOU MUST RUN TESTS AND BENCHMARKS INSIDE DOCKER.',
  '',
  'Run: docker-compose run --rm test',
  '============================================================'
].join('\n');

const FULL_GUARD_MESSAGE = ['\n\n', GUARD_BANNER, GUARD_MESSAGE_BODY].join('\n');

const EXIT_WITH_FAILURE = (() => {
  if (typeof globalThis !== 'undefined') {
    if (typeof globalThis.process?.exit === 'function') {
      return (code) => globalThis.process.exit(code);
    }
    if (typeof globalThis.Deno?.exit === 'function') {
      return (code) => globalThis.Deno.exit(code);
    }
  }

  return (code) => {
    throw new Error(`Docker guard triggered without a supported exit handler (code: ${code})`);
  };
})();

const DEFAULT_ENV = (() => {
  if (typeof globalThis !== 'undefined') {
    if (globalThis.process && globalThis.process.env) {
      return globalThis.process.env;
    }
    if (globalThis.Deno && typeof globalThis.Deno.env?.toObject === 'function') {
      try {
        return globalThis.Deno.env.toObject();
      } catch {
        // fall through to empty object when permissions not available
      }
    }
  }

  return Object.freeze({});
})();

/**
 * @param {NodeJS.ProcessEnv} [env=DEFAULT_ENV]
 * @returns {boolean}
 */
export function isDockerEnvironment(env = DEFAULT_ENV) {
  return env.GIT_STUNTS_DOCKER === '1' || Boolean(env.GITHUB_ACTIONS);
}

/**
 * @param {Object} [options]
 * @param {NodeJS.ProcessEnv} [options.env]
 * @param {function(number): void} [options.exit]
 * @param {function(string): void} [options.logger]
 */
export function ensureDocker({ env = DEFAULT_ENV, exit = EXIT_WITH_FAILURE, logger = console.error } = {}) {
  if (isDockerEnvironment(env)) {
    return;
  }

  const logFn = typeof logger === 'function' ? logger : console.error;
  logFn(FULL_GUARD_MESSAGE);
  exit(1);
}
