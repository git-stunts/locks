#!/usr/bin/env python3
"""Render help from literal sub_usage_text cases; never execute the source."""
from pathlib import Path
import re
import sys


def render(source):
    marker = 'sub_usage_text() {\n'
    if source.count(marker) != 1:
        raise ValueError('expected one canonical sub_usage_text function')
    body = source.split(marker, 1)[1]
    lines = []
    commands = set()
    for line in body.splitlines():
        stripped = line.strip()
        if stripped in ('case "$1" in', '*) usage_text ;;', 'esac', '}'):
            continue
        match = re.fullmatch(r"    ([a-z]+)\) printf 'usage: git locks ([^'\\]+)\\n' ;;", line)
        if not match:
            raise ValueError('unsupported canonical synopsis: ' + line)
        command, synopsis = match.groups()
        if command in commands or synopsis.split()[0] != command or '%' in synopsis:
            raise ValueError('duplicate or unsafe canonical synopsis: ' + command)
        commands.add(command)
        lines.append('git locks ' + synopsis)
    if not lines:
        raise ValueError('no canonical synopses')
    replacements = {
        '# @GIT_LOCKS_SYNOPSES@': '\n'.join('#   ' + line for line in lines),
        '@GIT_LOCKS_USAGE@': '\n'.join(('usage: ' if i == 0 else '       ') + line
                                         for i, line in enumerate(lines)),
    }
    for placeholder, value in replacements.items():
        if source.count(placeholder) != 1:
            raise ValueError('expected one placeholder: ' + placeholder)
        source = source.replace(placeholder, value)
    return source


if __name__ == '__main__':
    try:
        result = render(Path(sys.argv[1]).read_text())
    except (OSError, ValueError) as error:
        raise SystemExit('help generation: ' + str(error)) from error
    sys.stdout.write(result)
