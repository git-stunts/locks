#!/usr/bin/env python3
"""Synthetic admission facts do not establish real Docker/cgroup containment."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
subprocess.run(['node', str(ROOT / 'scripts/require-docker.mjs')], check=True)

import importlib.util
import stat
from types import SimpleNamespace
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('bootstrap_provider', ROOT / 'scripts/docker-ci.py')
provider = importlib.util.module_from_spec(spec)
spec.loader.exec_module(provider)
info = {'DockerRootDir': str(provider.DATA / 'docker'), 'Driver': 'overlay2',
        'CgroupDriver': 'cgroupfs', 'CgroupVersion': '2'}
health = {'monitor': {'pid': 20, 'parent': 1, 'started': 30},
          'watchdog': {'pid': 21, 'parent': 20, 'started': 40}}
values = {'cpu.max': '200000 100000', 'memory.max': str(provider.MEMORY_BYTES),
          'memory.swap.max': '0', 'pids.max': '2048', 'dockerd.pid': '22',
          'daemon-group': '0::/gitlocksci.slice/gitlockscidaemon.service',
          'worker-group': '0::/gitlocksci.slice/docker-worker'}


def admission(changes=None, daemon_info=None, free=70 << 30, protected=True, kill=True):
    facts = dict(values, **(changes or {}))
    def contents(path):
        if path.name == 'cgroup':
            return facts['daemon-group' if path.parent.name == '22' else 'worker-group']
        return facts[path.name]
    def identity(pid, require_root=True):
        assert pid in (22, 23)
        assert require_root == (pid == 22)
        return {'pid': pid, 'parent': 1, 'started': 100 + pid}
    with patch.object(provider.platform, 'system', return_value='Linux'), \
         patch.object(provider, 'quota_filesystem', return_value={'device': 7, 'capacity_bytes': provider.BUILD_BYTES}), \
         patch.object(provider, 'monitor_health', return_value=health), \
         patch.object(provider.shutil, 'disk_usage', return_value=SimpleNamespace(free=free)), \
         patch.object(provider.os, 'lstat', return_value=SimpleNamespace(st_mode=stat.S_IFREG | 0o644,
                     st_uid=0 if protected else 1000, st_nlink=1, st_size=3)), \
         patch.object(provider, 'process_identity', side_effect=identity), \
         patch.object(provider.Path, 'read_text', contents), \
         patch.object(provider.Path, 'is_file', return_value=kill):
        return provider.quota_admission(info if daemon_info is None else daemon_info, 23)


result = admission()
assert result['worker']['pid'] == 23 and result['daemon']['pid'] == 22
assert result['capacity_bytes'] == provider.BUILD_BYTES
checks = 1
cases = [
    {'changes': {'cpu.max': 'max 100000'}}, {'changes': {'cpu.max': '300000 100000'}},
    {'changes': {'cpu.max': '0 100000'}}, {'changes': {'memory.max': 'max'}},
    {'changes': {'memory.swap.max': '1'}}, {'changes': {'pids.max': 'max'}},
    {'changes': {'pids.max': '2049'}}, {'changes': {'pids.max': '0'}},
    {'changes': {'daemon-group': '0::/other.slice/daemon'}},
    {'changes': {'worker-group': '0::/gitlocksci.slice-escape/worker'}},
    {'changes': {'worker-group': '1:cpu:/gitlocksci.slice/worker'}},
    {'free': (50 << 30) - 1}, {'protected': False}, {'kill': False},
    {'daemon_info': dict(info, DockerRootDir='/var/lib/docker')},
    {'daemon_info': dict(info, Driver='overlayfs')},
    {'daemon_info': dict(info, CgroupDriver='systemd')},
    {'daemon_info': dict(info, CgroupVersion='1')},
]
for case in cases:
    try:
        admission(**case)
    except RuntimeError:
        checks += 1
    else:
        raise AssertionError(('accepted invalid admission', case))
print(f'Bootstrap admission: {checks} synthetic cases passed', flush=True)
