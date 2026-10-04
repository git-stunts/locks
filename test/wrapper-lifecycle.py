#!/usr/bin/env python3
"""Wrapper admission, owned cleanup, expiry, and process-group cancellation."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
subprocess.run(['node', str(ROOT / 'scripts/require-docker.mjs')], check=True)

import fnmatch
import json
import sys
import os
import pty
import select
import signal
import tempfile
import time

import jsonschema

CLI = str(ROOT / 'bin/git-locks')
VALIDATOR = jsonschema.Draft202012Validator(json.loads((ROOT / 'schema/git-locks.schema.json').read_text()))
checks = 0
failures = []


def setup(base):
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env.update(GIT_LOCKS_STORE=str(base / 'store.git'), GIT_LOCKS_NOW='100')
    assert invoke(env, 'sem', 'create', 'gpu', '--capacity', '1').returncode == 0
    return env


def invoke(env, *args):
    return subprocess.run([CLI, *args], env=env, text=True, capture_output=True, timeout=10)


def rows(text):
    try:
        parsed = [json.loads(line) for line in text.splitlines()]
    except json.JSONDecodeError as error:
        raise AssertionError(f'non-JSON lifecycle output: {text!r}') from error
    for row in parsed:
        VALIDATOR.validate(row)
    return parsed


def await_file(path, process):
    deadline = time.monotonic() + 5
    while not path.exists():
        assert time.monotonic() < deadline and process.poll() is None, ('never became ready', path)
        time.sleep(0.01)


def stop(process, base):
    # Only process groups explicitly created by this fixture. The old wrapper
    # shares its test session; the new wrapper also owns a separate child group.
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()
    identity = base / 'identity'
    if identity.exists():
        data = json.loads(identity.read_text())
        for pgid in set((data['group'], data['supervisor'], process.pid)):
            if pgid != os.getpgrp():
                try:
                    os.killpg(pgid, signal.SIGKILL)
                except ProcessLookupError:
                    pass


def start(base, env, kind='path', code=0, stubborn=False, wait_ready=True, background=False):
    ready, gate = base / 'ready', base / 'gate'
    script = base / 'command.py'
    script.write_text('''import json, os, signal, subprocess, sys, time
from pathlib import Path
base = Path(sys.argv[1])
signal.signal(signal.SIGINT, signal.SIG_DFL)
if sys.argv[3] == 'stubborn':
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
child = subprocess.Popen(['sleep', '30'])
(base / 'identity').write_text(json.dumps({'pid': os.getpid(), 'child': child.pid, 'group': os.getpgrp(), 'supervisor': os.getppid()}))
(base / 'ready').touch()
while not (base / 'gate').exists():
    time.sleep(0.01)
child.terminate()
child.wait()
sys.exit(int(sys.argv[2]))
''')
    args = [CLI, 'with', '--job', 'w', '--holder', 'alice', '--ttl', '5']
    if kind in ('sem', 'both'):
        args += ['--sem', 'gpu']
    if kind in ('path', 'both'):
        args += ['x.md']
    process = subprocess.Popen([*args, '--', 'python3', str(script), str(base), str(code), 'stubborn' if stubborn else 'normal'],
                               env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               start_new_session=not background, preexec_fn=os.setpgrp if background else None)
    try:
        if wait_ready:
            await_file(ready, process)
    except BaseException:
        stop(process, base)
        raise
    return process, gate


def lost(base, kind, mode, code=0):
    env = setup(base)
    # A mutable clock exercises expiry inside the wrapper's own process.
    shim = base / 'shim'
    shim.mkdir()
    clock = base / 'clock'
    clock.write_text('100')
    (shim / 'date').write_text('#!/bin/sh\ncat "$CLOCK_SAMPLE"\n')
    (shim / 'date').chmod(0o755)
    env.pop('GIT_LOCKS_NOW')
    env.update(PATH=str(shim) + os.pathsep + env['PATH'], CLOCK_SAMPLE=str(clock))
    process, gate = start(base, env, kind, code=code)
    try:
        if mode == 'expired':
            clock.write_text('105')
        elif mode == 'missing':
            args = ('release', '--job', 'w') if kind == 'path' else ('sem', 'release', 'gpu', '--job', 'w')
            assert invoke(env, *args).returncode == 0
        elif mode == 'superseded':
            if kind == 'path':
                assert invoke(env, 'claim', '--job', 'w', '--holder', 'bob', 'x.md').returncode == 0
            else:
                assert invoke(env, 'sem', 'release', 'gpu', '--job', 'w').returncode == 0
                assert invoke(env, 'sem', 'acquire', 'gpu', '--job', 'w', '--holder', 'bob').returncode == 0
        gate.touch()
        out, err = process.communicate(timeout=5)
        assert process.returncode == 125 and not out, (process.returncode, out, err)
        events = rows(err)
        lost_rows = [row for row in events if row['event'] == 'lost']
        assert len(lost_rows) == (2 if kind == 'both' else 1), events
        assert all(row['reason'] == mode and row['command_status'] == code for row in lost_rows), events
        if mode == 'superseded':
            state = invoke(env, 'show', '--job', 'w') if kind == 'path' else invoke(env, 'sem', 'show', 'gpu')
            record = json.loads(state.stdout)
            assert (record['holder'] if kind == 'path' else record['slots'][0]['holder']) == 'bob', record
        else:
            assert not invoke(env, 'list').stdout
            assert json.loads(invoke(env, 'sem', 'show', 'gpu').stdout)['live'] == 0
    finally:
        stop(process, base)


def cancelled(base, sig, stubborn=False):
    env = setup(base)
    process, _ = start(base, env, 'both', stubborn=stubborn)
    try:
        identity = json.loads((base / 'identity').read_text())
        begun = time.monotonic()
        process.send_signal(sig)
        out, err = process.communicate(timeout=5)
        assert process.returncode == 128 + sig and not out, (process.returncode, out, err)
        assert time.monotonic() - begun < 4
        rows(err)
        # /proc is inspected only inside the Linux test worker. Zombies are no
        # longer executing and are reaped by the worker's init.
        for pid in (identity['pid'], identity['child']):
            path = Path(f'/proc/{pid}/stat')
            assert not path.exists() or path.read_text().split()[2] == 'Z', (pid, 'still running')
        assert not invoke(env, 'list').stdout
        assert json.loads(invoke(env, 'sem', 'show', 'gpu').stdout)['live'] == 0
    finally:
        stop(process, base)


def active_name(base, kind):
    env = setup(base)
    process, gate = start(base, env, kind)
    try:
        args = ['with', '--job', 'w', '--holder', 'alice']
        if kind in ('sem', 'both'):
            args += ['--sem', 'gpu']
        if kind in ('path', 'both'):
            args += ['x.md']
        marker = base / 'forbidden'
        second = invoke(env, *args, '--', 'touch', str(marker))
        assert second.returncode == 1 and not marker.exists(), second
        assert rows(second.stderr)[0]['reason'] == 'active'
        gate.touch()
        out, err = process.communicate(timeout=5)
        assert process.returncode == 0 and not out, (process.returncode, out, err)
        rows(err)
    finally:
        stop(process, base)


def cleanup_error(base):
    env = setup(base)
    process, gate = start(base, env, 'both')
    lock = Path(env['GIT_LOCKS_STORE']) / 'refs/locks/state.lock'
    try:
        lock.write_text('owned fault fixture')
        gate.touch()
        out, err = process.communicate(timeout=5)
        assert process.returncode == 125 and not out, (process.returncode, out, err)
        events = rows(err)
        assert any(row.get('reason') == 'store-write' for row in events), events
        assert any(row.get('event') == 'with-failed' and row['reason'] == 'cleanup' and row['command_status'] == 0 for row in events), events
        assert lock.read_text() == 'owned fault fixture'
    finally:
        lock.unlink(missing_ok=True)
        stop(process, base)


def atomic_wait(base):
    env = setup(base)
    assert invoke(env, 'claim', '--job', 'blocker', '--holder', 'bob', 'x.md').returncode == 0
    trace = base / 'trace'
    process = subprocess.Popen([CLI, 'with', '--job', 'w', '--holder', 'alice', '--sem', 'gpu', '--wait', '10', 'x.md', '--', 'true'],
                               env=dict(env, GIT_LOCKS_TRACE=str(trace)), text=True, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, start_new_session=True)
    try:
        deadline = time.monotonic() + 5
        while not trace.exists() or trace.read_text().count('snapshot ') < 3:
            assert time.monotonic() < deadline and process.poll() is None
            time.sleep(0.01)
        assert json.loads(invoke(env, 'sem', 'show', 'gpu').stdout)['live'] == 0, 'path wait acquired a slot early'
        assert invoke(env, 'release', '--job', 'blocker').returncode == 0
        out, err = process.communicate(timeout=5)
        assert process.returncode == 0 and not out, (process.returncode, out, err)
        acquired = [row for row in rows(err) if row['event'] in ('claimed', 'acquired')]
        assert len(acquired) == 2 and len({row['acquisition'] for row in acquired}) == 1, acquired
    finally:
        stop(process, base)


def pass_through(base):
    env = setup(base)
    result = subprocess.run([CLI, 'with', '--job', 'w', '--holder', 'alice', 'x.md', '--', 'sh', '-c', 'cat; exit 17'],
                            env=env, input='preserve input\n', text=True, capture_output=True, timeout=10)
    assert result.returncode == 17 and result.stdout == 'preserve input\n', result
    rows(result.stderr)
    assert not invoke(env, 'list').stdout



def command_statuses(base):
    env = setup(base)
    for status in (0, 1, 17, 125, 126, 127, 130, 143, 255):
        result = invoke(env, 'with', '--job', 'w', '--holder', 'alice', 'x.md', '--',
                        'sh', '-c', 'exit "$1"', 'command', str(status))
        assert result.returncode == status, (status, result.returncode, result.stderr)
        assert all(row['event'] in ('claimed', 'released') for row in rows(result.stderr))
    assert not invoke(env, 'list').stdout


def leftover_child(base):
    env = setup(base)
    pidfile = base / 'child'
    result = invoke(env, 'with', '--job', 'w', '--holder', 'alice', 'x.md', '--', 'python3', '-c',
                    'import subprocess, sys; from pathlib import Path; '
                    'child = subprocess.Popen(["sleep", "30"]); '
                    'Path(sys.argv[1]).write_text(str(child.pid)); sys.exit(17)', str(pidfile))
    assert result.returncode == 17, result
    rows(result.stderr)
    state = Path(f'/proc/{int(pidfile.read_text())}/stat')
    assert not state.exists() or state.read_text().rsplit(')', 1)[1].split()[0] == 'Z', 'child outlived reservation cleanup'
    assert not invoke(env, 'list').stdout


def launch_error(base):
    env = setup(base)
    shim = base / 'shim'
    shim.mkdir()
    (shim / 'ps').write_text('#!/bin/sh\nexit 1\n')
    (shim / 'ps').chmod(0o755)
    env['PATH'] = str(shim) + os.pathsep + env['PATH']
    marker = base / 'forbidden'
    result = invoke(env, 'with', '--job', 'w', '--holder', 'alice', 'x.md', '--', 'touch', str(marker))
    assert result.returncode == 125 and not marker.exists(), result
    events = rows(result.stderr)
    assert any(row.get('event') == 'with-failed' and row['reason'] == 'launch' and row['command_status'] is None for row in events), events
    assert not invoke(env, 'list').stdout



def terminal(base, mode):
    env = setup(base)
    script = base / 'terminal.py'
    script.write_text("""import json, os, signal, subprocess, sys
from pathlib import Path
signal.signal(signal.SIGINT, signal.SIG_DFL)
child = subprocess.Popen(['sleep', '30'])
Path(sys.argv[1]).write_text(json.dumps({'pid': os.getpid(), 'child': child.pid, 'group': os.getpgrp(), 'supervisor': os.getppid()}))
print('TERMINAL READY', flush=True)
line = input()
print('TERMINAL INPUT:' + line, flush=True)
child.terminate()
child.wait()
sys.exit(17)
""")
    pid, fd = pty.fork()
    if pid == 0:
        args = [CLI, 'with', '--job', 'w', '--holder', 'alice', 'x.md', '--',
                'python3', str(script), str(base / 'identity')]
        if mode == 'redirected':
            with (base / 'stderr').open('wb') as stream:
                os.dup2(stream.fileno(), 2)
        if mode == 'caller':
            os.execvpe('bash', ['bash', '-c',
                              '"$@"; status=$?; echo CALLER_READY; read -r line; echo CALLER_INPUT:$line; exit "$status"',
                              'caller', *args], env)
        os.execvpe(CLI, args, env)
    output = b''
    status = None
    acted = False
    suspended = False
    caller_input = False
    try:
        deadline = time.monotonic() + 5
        while status is None and time.monotonic() < deadline:
            if select.select([fd], [], [], .02)[0]:
                try:
                    output += os.read(fd, 65536)
                except OSError:
                    pass  # PTY EIO after the last slave closes; reap below.
            if b'TERMINAL READY' in output and not acted:
                if mode in ('input', 'suspend', 'caller', 'redirected'):
                    os.write(fd, b'\x1a' if mode == 'suspend' else b'terminal input\n')
                elif mode == 'interrupt':
                    os.write(fd, b'\x03')
                else:
                    os.kill(pid, signal.SIGTERM)
                acted = True
            if b'CALLER_READY' in output and not caller_input:
                assert os.tcgetpgrp(fd) == pid, 'wrapper did not return the terminal to its caller'
                os.write(fd, b'caller input\n')
                caller_input = True
            ended, value = os.waitpid(pid, os.WNOHANG | os.WUNTRACED)
            if ended and os.WIFSTOPPED(value):
                assert mode == 'suspend' and not suspended, (mode, value, output)
                suspended = True
                assert invoke(env, 'list').stdout, 'suspended command released its reservation'
                os.kill(pid, signal.SIGCONT)
                os.write(fd, b'terminal input\n')
            elif ended:
                status = value
        expected = {'input': 17, 'caller': 17, 'redirected': 17, 'suspend': 17, 'interrupt': 130, 'terminate': 143}[mode]
        assert status is not None and os.waitstatus_to_exitcode(status) == expected, (status, output)
        if mode in ('input', 'suspend', 'caller', 'redirected'):
            assert b'TERMINAL INPUT:terminal input' in output, output
        if mode == 'caller':
            assert b'CALLER_INPUT:caller input' in output, output
        if mode == 'redirected':
            rows((base / 'stderr').read_text())
        assert mode != 'suspend' or suspended, 'terminal stop was ignored'
        assert not invoke(env, 'list').stdout
        identity = json.loads((base / 'identity').read_text())
        for child in (identity['pid'], identity['child']):
            path = Path(f'/proc/{child}/stat')
            assert not path.exists() or path.read_text().split()[2] == 'Z', (child, 'still running')
    finally:
        groups = {pid}
        if (base / 'identity').exists():
            identity = json.loads((base / 'identity').read_text())
            groups.update((identity['group'], identity['supervisor']))
        for group in groups:
            try:
                os.killpg(group, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if status is None:
            os.waitpid(pid, 0)
        os.close(fd)



def terminal_background(base):
    env = setup(base)
    pid, fd = pty.fork()
    if pid == 0:
        process, _ = start(base, env, background=True, wait_ready=False)
        (base / 'wrapper.pid').write_text(str(process.pid))
        out, err = process.communicate(timeout=10)
        os._exit(process.returncode)
    status = None
    try:
        deadline = time.monotonic() + 5
        while not (base / 'ready').exists():
            assert time.monotonic() < deadline, 'background command did not start'
            time.sleep(.01)
        assert os.tcgetpgrp(fd) == pid, 'background wrapper stole the controlling terminal'
        (base / 'gate').touch()
        while status is None and time.monotonic() < deadline:
            ended, value = os.waitpid(pid, os.WNOHANG)
            if ended:
                status = value
            time.sleep(.01)
        assert status is not None and os.waitstatus_to_exitcode(status) == 0, status
        assert not invoke(env, 'list').stdout
    finally:
        groups = {pid}
        if (base / 'wrapper.pid').exists():
            groups.add(int((base / 'wrapper.pid').read_text()))
        if (base / 'identity').exists():
            identity = json.loads((base / 'identity').read_text())
            groups.update((identity['group'], identity['supervisor']))
        for group in groups:
            try:
                os.killpg(group, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if status is None:
            os.waitpid(pid, 0)
        os.close(fd)



def publication_boundary(base, mode):
    env = setup(base)
    shim = base / 'shim'
    shim.mkdir()
    clock = base / 'clock'
    clock.write_text('100')
    (shim / 'date').write_text('#!/bin/sh\ncat "$CLOCK_SAMPLE"\n')
    (shim / 'date').chmod(0o755)
    git_script = '''#!/usr/bin/python3
import os, subprocess, sys, time
from pathlib import Path
args = sys.argv[1:]
if 'update-ref' not in args or not os.environ.get('PUBLICATION_GATE'):
    os.execv(os.environ['REAL_GIT'], [os.environ['REAL_GIT'], *args])
count_file = Path(os.environ['PUBLICATION_COUNT'])
count = int(count_file.read_text()) + 1 if count_file.exists() else 1
count_file.write_text(str(count))
data = sys.stdin.read()
def pause():
    gate = Path(os.environ['PUBLICATION_GATE'])
    Path(str(gate) + '.ready').touch()
    deadline = time.monotonic() + 8
    while not gate.exists():
        if time.monotonic() >= deadline:
            sys.exit(77)
        time.sleep(0.01)
selected = count == int(os.environ['PUBLICATION_TARGET'])
if selected and os.environ['PUBLICATION_PHASE'] == 'before':
    pause()
result = subprocess.run([os.environ['REAL_GIT'], *args], input=data, text=True, capture_output=True)
if selected and os.environ['PUBLICATION_PHASE'] == 'after':
    pause()
print(result.stdout, end='')
print(result.stderr, end='', file=sys.stderr)
sys.exit(result.returncode)
'''
    (shim / 'git').write_text(git_script)
    (shim / 'git').chmod(0o755)
    import shutil
    env.pop('GIT_LOCKS_NOW')
    env.update(PATH=str(shim) + os.pathsep + env['PATH'], CLOCK_SAMPLE=str(clock), REAL_GIT=shutil.which('git'))
    gate = base / 'publication'
    paused = dict(env, PUBLICATION_GATE=str(gate), PUBLICATION_TARGET='2' if mode == 'cleanup' else '1',
                  PUBLICATION_PHASE='before' if mode == 'cleanup' else 'after', PUBLICATION_COUNT=str(base / 'count'))
    ran = base / 'ran'
    process = subprocess.Popen([CLI, 'with', '--job', 'w', '--holder', 'alice', '--ttl', '5', '--sem', 'gpu',
                                'x.md', '--', 'touch', str(ran)], env=paused, text=True,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    try:
        await_file(Path(str(gate) + '.ready'), process)
        # The first publication already owns BOTH resources even while the
        # parent has not yet received its acquisition receipt.
        tree = subprocess.check_output([env['REAL_GIT'], '--git-dir=' + env['GIT_LOCKS_STORE'],
                                        'ls-tree', '-r', '--name-only', 'refs/locks/state'], text=True).splitlines()
        assert 'jobs/w' in tree and 'sem/gpu/slots/w' in tree, tree
        if mode == 'expired':
            clock.write_text('105')
        elif mode in ('superseded', 'cleanup'):
            assert invoke(env, 'claim', '--job', 'w', '--holder', 'bob', 'x.md').returncode == 0
        elif mode == 'cancel':
            process.send_signal(signal.SIGTERM)
        elif mode == 'group-cancel':
            os.killpg(process.pid, signal.SIGTERM)
        assert ran.exists() == (mode == 'cleanup')
        gate.touch()
        out, err = process.communicate(timeout=5)
        assert process.returncode == (143 if mode in ('cancel', 'group-cancel') else 125) and not out, (process.returncode, out, err)
        events = rows(err)
        if mode not in ('cancel', 'group-cancel'):
            losses = [row for row in events if row['event'] == 'lost']
            assert len(losses) == (2 if mode == 'expired' else 1), events
            assert all(row['command_status'] == (0 if mode == 'cleanup' else None) for row in losses), events
        assert ran.exists() == (mode == 'cleanup'), 'lost admission launched the command'
        assert json.loads(invoke(env, 'sem', 'show', 'gpu').stdout)['live'] == 0
        if mode in ('superseded', 'cleanup'):
            assert json.loads(invoke(env, 'show', '--job', 'w').stdout)['holder'] == 'bob'
        else:
            assert not invoke(env, 'list').stdout
    finally:
        gate.touch()
        stop(process, base)



def admission_race(base, kind):
    env = setup(base)
    racers = []
    try:
        for name in ('a', 'b'):
            directory = base / name
            directory.mkdir()
            read_gate = directory / 'read'
            process, command_gate = start(directory, dict(env, GIT_LOCKS_PAUSE_AFTER_READ=str(read_gate)), kind, wait_ready=False)
            racers.append((directory, process, read_gate, command_gate))
        for _, process, read_gate, _ in racers:
            await_file(Path(str(read_gate) + '.ready'), process)
        for _, _, read_gate, _ in racers:
            read_gate.touch()
        deadline = time.monotonic() + 5
        while True:
            started = [entry for entry in racers if (entry[0] / 'ready').exists()]
            ended = [entry for entry in racers if entry[1].poll() is not None]
            assert len(started) <= 1, 'both racing wrappers started commands for one job'
            if len(started) == 1 and len(ended) == 1:
                break
            assert time.monotonic() < deadline, 'race did not settle while the winner was held'
            time.sleep(0.01)
        loser = ended[0][1]
        out, err = loser.communicate(timeout=1)
        assert loser.returncode == 1 and not out and rows(err)[0]['reason'] == 'active', (loser.returncode, out, err)
        started[0][3].touch()
        winner = started[0][1]
        out, err = winner.communicate(timeout=5)
        assert winner.returncode == 0 and not out, (winner.returncode, out, err)
        rows(err)
        assert not invoke(env, 'list').stdout
        assert json.loads(invoke(env, 'sem', 'show', 'gpu').stdout)['live'] == 0
    finally:
        for directory, process, read_gate, command_gate in racers:
            read_gate.touch()
            command_gate.touch()
            stop(process, directory)


def case(label, body):
    global checks
    if sys.argv[1:] and not any(fnmatch.fnmatchcase(label, pattern) for pattern in sys.argv[1:]):
        return
    try:
        with tempfile.TemporaryDirectory(prefix='locks-wrapper-') as tmp:
            body(Path(tmp))
        checks += 1
    except Exception as error:
        failures.append((label, str(error)))
        print(f'FAIL wrapper ({label}): {error}', flush=True)


for kind in ('path', 'sem'):
    for mode in ('expired', 'missing', 'superseded'):
        case(f'{kind} lost {mode}', lambda base, k=kind, m=mode: lost(base, k, m))
case('both expired', lambda base: lost(base, 'both', 'expired'))
case('lost preserves command failure', lambda base: lost(base, 'path', 'missing', 17))
case('command 125 still reports loss', lambda base: lost(base, 'path', 'missing', 125))
for sig in (signal.SIGTERM, signal.SIGINT):
    case(f'forward signal {sig}', lambda base, s=sig: cancelled(base, s))
case('terminate stubborn group', lambda base: cancelled(base, signal.SIGTERM, True))
for kind in ('path', 'sem', 'both'):
    case(f'active job {kind}', lambda base, k=kind: active_name(base, k))
case('cleanup fails', cleanup_error)
case('atomic resources while waiting', atomic_wait)
for kind in ('path', 'sem', 'both'):
    case(f'stale admission race {kind}', lambda base, k=kind: admission_race(base, k))
case('stdin and command status', pass_through)
case('command exit statuses', command_statuses)
case('remaining command group stops before cleanup', leftover_child)
case('launch fails closed', launch_error)
case('terminal background ownership', terminal_background)
for mode in ('input', 'interrupt', 'terminate', 'suspend', 'caller', 'redirected'):
    case(f'terminal {mode}', lambda base, m=mode: terminal(base, m))
for mode in ('expired', 'superseded', 'cancel', 'group-cancel', 'cleanup'):
    case(f'publication boundary {mode}', lambda base, m=mode: publication_boundary(base, m))
print(f'wrapper lifecycle: {checks} cases passed; {len(failures)} failed')
assert checks or failures, 'no cases matched the requested patterns'
assert not failures, failures
