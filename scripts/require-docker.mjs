import { existsSync, readFileSync, realpathSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { ensureDocker } from './vendor/docker-guard/src/index.js';

// Upstream's environment-only check also accepts GITHUB_ACTIONS on a host.
// Supply verified evidence instead; neither environment variable is a bypass.
const root = fileURLToPath(new URL('../', import.meta.url));
let isolated = false;
try {
  const mounts = readFileSync('/proc/self/mountinfo', 'utf8').split('\n');
  const tmpfs = (path) => mounts.some((line) =>
    line.split(' ')[4] === path && line.includes(' - tmpfs '));
  isolated = existsSync('/.dockerenv')
    && readFileSync('/opt/git-locks-test-runtime', 'utf8') === 'git-locks isolated test runtime v1\n'
    && realpathSync(root) === '/work/source'
    && tmpfs('/work') && tmpfs('/tmp') && tmpfs('/home/node')
    && readdirSync('/sys/class/net').every((name) => name === 'lo')
    && !existsSync('/var/run/docker.sock');
} catch {
  // Missing container evidence fails closed, including on non-Linux hosts.
}
ensureDocker({
  env: isolated ? { GIT_STUNTS_DOCKER: '1' } : {},
  logger: (message) => console.error(message.replace('Run: docker-compose run --rm test', 'Run: make test (or python3 scripts/docker-run.py <command>)')),
});
if (!isolated) process.exit(1);
