#!/usr/bin/env python3
"""Validate task cards and derive their graph. No third-party modules required."""
from pathlib import Path
import argparse
import hashlib
import json
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
LANES = ['contract', 'operations', 'state', 'assurance', 'performance', 'product']
TYPES = ['Feature', 'Bug', 'Decision', 'Research', 'Investigation', 'Spike']


def require(condition, message):
    if not condition:
        raise ValueError(message)


def metadata(text):
    parts = text.split('---\n', 2)
    require(len(parts) == 3 and not parts[0], 'expected YAML frontmatter')
    values = {}
    for line in parts[1].splitlines():
        key, separator, value = line.partition(': ')
        require(separator and key not in values, 'invalid or duplicate frontmatter key: ' + key)
        values[key] = json.loads(value)
    return values, parts[2]


def layers_for(tasks):
    by_id = {t['id']: t for t in tasks}
    require(len(by_id) == len(tasks), 'duplicate task id')
    remaining = {}
    for task in tasks:
        deps = task['dependencies']
        require(len({d['id'] for d in deps}) == len(deps), 'duplicate dependency: ' + task['id'])
        for dep in deps:
            require(dep['id'] in by_id, 'unknown dependency: ' + dep['id'])
            require(dep['id'] != task['id'], 'self dependency: ' + task['id'])
            require(bool(dep['reason'].strip()), 'missing dependency reason')
            require(not task.get('release_required') or by_id[dep['id']].get('release_required'),
                    'required task depends on optional work: ' + task['id'])
        remaining[task['id']] = {d['id'] for d in deps}
    layers = []
    while remaining:
        ready = sorted(key for key, deps in remaining.items() if not deps)
        require(bool(ready), 'dependency cycle: ' + ', '.join(sorted(remaining)))
        layers.append(ready)
        remaining = {key: deps - set(ready) for key, deps in remaining.items() if key not in ready}
    return layers


def load():
    prefix = (ROOT / 'docs/tasks/PROMPT.txt').read_bytes().decode('utf-8')
    prefix_hash = hashlib.sha256(prefix.encode()).hexdigest()
    inventory = json.loads((ROOT / 'docs/planning/inventory.json').read_bytes().decode('utf-8'))
    require(inventory['schema'] == 'git-locks-inventory/2', 'unknown inventory schema')
    for gate in inventory['external_gates'].values():
        require(gate['phase'] in ['before-action', 'completion'], 'unknown gate phase')
        require(bool(gate['condition'].strip()) and bool(gate['blocks'].strip()), 'empty gate condition or action')
    tasks = []
    for path in (ROOT / 'docs/tasks').glob('*.md'):
        require(path.name == 'DAG.md' or re.fullmatch(r'GL-[0-9]{3}\.md', path.name),
                'unexpected task document: ' + path.name)
    for path in sorted((ROOT / 'docs/tasks').glob('GL-*.md')):
        raw = path.read_bytes().decode('utf-8')
        task, body = metadata(raw)
        require(task['id'] == path.stem and re.fullmatch(r'GL-[0-9]{3}', task['id']), 'bad task id')
        require(task['schema'] == 'git-locks-task/1', 'unknown task schema')
        require(task['graph_version'] == inventory['graph_version'], 'mixed graph versions')
        require(task['baseline_commit'] == inventory['baseline_commit'], 'mixed source baselines')
        require(task['workstream'] in LANES and task['type'] in TYPES, 'unknown workstream or task type')
        require(task['status'] in ['planned', 'active', 'blocked', 'done', 'deferred'], 'unknown task status')
        require(isinstance(task['release_required'], bool), 'release_required must be boolean')
        require(task['dependency_status'] in ['proposed', 'accepted'], 'unknown edge status')
        require(task['status'] != 'done' or bool(task['completion_evidence']), 'done task lacks evidence')
        require(task['prompt_prefix_sha256'] == prefix_hash, 'wrong prompt prefix hash')
        heading = '# ' + task['type'] + '\n\n```text\n'
        require(body.startswith('\n' + heading), 'task must start with its type and prompt')
        prompt = body.split('```text\n', 1)[1].split('```', 1)[0]
        require(prompt.startswith(prefix + '\nTask: ' + task['id'] + ' — '), 'prompt prefix or task id drift')
        require('Read docs/tasks/' + task['id'] + '.md.' in prompt, 'prompt reads another task')
        for number in range(1, 10):
            require(len(re.findall(r'^## ' + str(number) + r'\. ', body, re.M)) == 1,
                    task['id'] + ' missing or duplicate template section ' + str(number))
        for source in task['sources']:
            require((ROOT / source).exists(), task['id'] + ' source path missing: ' + source)
        for gate in task['external_gates']:
            require(gate in inventory['external_gates'], 'undefined external gate: ' + gate)
        prerequisite_text = body.split('## 3. Prerequisites', 1)[1].split('## 4. Scope', 1)[0]
        declared = re.findall(r'\[(GL-[0-9]{3})\]\(GL-[0-9]{3}\.md\)', prerequisite_text)
        require(declared == [d['id'] for d in task['dependencies']], 'extra or missing prerequisite in prose')
        gates = re.findall(r'External gate: `([^`]+)`', prerequisite_text)
        require(gates == task['external_gates'], 'external gate prose drift')
        for gate in task['external_gates']:
            phase = inventory['external_gates'][gate]['phase']
            require('External gate: `' + gate + '` (' + phase + ').' in prerequisite_text, 'gate phase prose drift')
        for dep in task['dependencies']:
            require('[' + dep['id'] + '](' + dep['id'] + '.md): ' + dep['reason'] in prerequisite_text,
                    'frontmatter and prerequisite text disagree: ' + task['id'])
        task.update(path=str(path.relative_to(ROOT)), sha256=hashlib.sha256(raw.encode()).hexdigest())
        tasks.append(task)
    require(bool(tasks), 'no task cards')
    ids = {t['id'] for t in tasks}
    active = inventory['active_tasks']
    require(len(active) == len(set(active)) and set(active) == ids,
            'active task inventory differs from task cards')
    previous = inventory['previous_task_ids']
    dispositions = inventory['task_disposition']
    require(len(previous) == len(set(previous)) and set(previous) == set(dispositions),
            'previous task disposition coverage differs')
    for key, disposition in dispositions.items():
        require(disposition['status'] in ['retained', 'replaced', 'deferred'], 'unknown task disposition')
        require(bool(disposition['reason'].strip()), 'missing task disposition reason')
        successors = disposition['successors']
        require(len(successors) == len(set(successors)) and set(successors) <= ids,
                'unknown or duplicate task disposition successor')
        if disposition['status'] == 'retained':
            require(key in ids and successors == [key], 'retained task disposition drift')
        else:
            require(key not in ids, 'retired task still has an active card')
            require(bool(successors) if disposition['status'] == 'replaced' else not successors,
                    'task disposition successor drift')
    coverage = inventory['issue_coverage']
    for issue, owners in coverage.items():
        require(bool(owners), 'unmapped issue: ' + issue)
        for owner in owners:
            require(owner in ids or owner.startswith(('completed:', 'deferred:')), 'unknown issue owner: ' + owner)
            if owner.startswith('deferred:'):
                require(bool(inventory['deferred_issues'].get(issue, '').strip()), 'deferred issue lacks a reason')
            if owner in ids:
                task = next(t for t in tasks if t['id'] == owner)
                require('https://github.com/git-stunts/locks/issues/' + issue in task['issues'], 'issue map drift')
    for task in tasks:
        for issue in task['issues']:
            require(task['id'] in coverage.get(issue.rsplit('/', 1)[1], []), 'task missing from issue map')
    return tasks, inventory


def render(tasks, inventory):
    layers = layers_for(tasks)
    by_id = {t['id']: t for t in tasks}
    done = {t['id'] for t in tasks if t['status'] == 'done'}
    ready = sorted(t['id'] for t in tasks if t['status'] in ['planned', 'active']
                   and {d['id'] for d in t['dependencies']} <= done)
    graph = {'schema': 'git-locks-task-graph/2', 'graph_version': inventory['graph_version'],
             'baseline_commit': inventory['baseline_commit'],
             'edge_direction': 'prerequisite-to-dependent', 'edge_status': 'see each task dependency_status',
             'tasks': tasks, 'edges': [{'from': d['id'], 'to': t['id'], 'reason': d['reason'],
                                       'status': t['dependency_status']} for t in tasks for d in t['dependencies']],
             'workstreams': {lane: [t['id'] for t in tasks if t['workstream'] == lane] for lane in LANES},
             'topological_antichains': layers, 'dependency_ready': ready,
             'candidates_without_action_gates': [key for key in ready
                 if not any(inventory['external_gates'][gate]['phase'] == 'before-action'
                            for gate in by_id[key]['external_gates'])],
             'external_gates': inventory['external_gates'],
             'limits': 'Layers are antichains, not maximum antichains or resource schedules. Ready is not authorization.'}
    md = '# Task dependency graph\n\nGenerated from task frontmatter by `scripts/roadmap.py`. Do not edit this projection directly.\n\n'
    md += 'Graph version: `' + graph['graph_version'] + '`. Edges point from prerequisite to dependent.\n'
    md += 'Each task has one workstream. External gates and resource conflicts are separate from edges.\n\n'
    md += '## Dependency-ready candidates\n\n'
    md += ', '.join('[' + key + '](' + key + '.md)' for key in ready) + '.\n\n'
    md += 'These tasks have no unfinished task prerequisite. Inspect external gates before protected actions.\n'
    md += 'A gate can permit preparation while it blocks an experiment, settings change, or final publication.\n\n'
    md += 'Candidates without a recorded action gate: ' + ', '.join(graph['candidates_without_action_gates']) + '.\n\n'
    md += 'Completion gates do not exclude preparation candidates. Inspect each gate condition before task closure.\n\n'
    md += '## Topological antichains\n\n'
    md += 'Each row has no internal dependency path. Rows do not prove simultaneous resource availability.\n\n'
    md += '| Layer | Tasks |\n| --- | --- |\n'
    for i, layer in enumerate(layers, 1):
        md += '| ' + str(i) + ' | ' + ', '.join('[' + key + '](' + key + '.md)' for key in layer) + ' |\n'
    md += '\n## Complete DAG\n\n```mermaid\nflowchart TD\n'
    for lane in LANES:
        md += '  subgraph ' + lane + '["' + lane + '"]\n'
        for task in tasks:
            if task['workstream'] == lane:
                label = task['id'] + ': ' + task['title']
                md += '    ' + task['id'].replace('-', '_') + '[' + json.dumps(label) + ']\n'
        md += '  end\n'
    for edge in graph['edges']:
        md += '  ' + edge['from'].replace('-', '_') + ' --> ' + edge['to'].replace('-', '_') + '\n'
    md += '```\n'
    checklist = '\n'.join('- [' + ('x' if by_id[key]['status'] == 'done' else ' ') + '] [' + key + ' — '
                          + by_id[key]['title'] + '](' + by_id[key]['path'] + ') · '
                          + by_id[key]['workstream'] + ' · ' + by_id[key]['horizon']
                          + (' · optional' if not by_id[key]['release_required'] else '')
                          for layer in layers for key in layer)
    roadmap = (ROOT / 'ROADMAP.md').read_bytes().decode('utf-8')
    required = sum(t['release_required'] for t in tasks)
    count_claim = f'**{len(tasks)} task cards: {required} required delivery tasks and {len(tasks) - required} gated extension tasks**'
    require(count_claim in roadmap, 'roadmap task count drift')
    start, end = '<!-- TASK CHECKLIST BEGIN -->', '<!-- TASK CHECKLIST END -->'
    require(roadmap.count(start) == roadmap.count(end) == 1, 'roadmap checklist marker drift')
    roadmap = roadmap.split(start)[0] + start + '\n' + checklist + '\n' + end + roadmap.split(end)[1]
    return {'docs/tasks/graph.json': json.dumps(graph, indent=2, ensure_ascii=False) + '\n',
            'docs/tasks/DAG.md': md, 'ROADMAP.md': roadmap}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check', action='store_true')
    mode.add_argument('--write', action='store_true')
    mode.add_argument('--prompt', metavar='TASK_ID')
    args = parser.parse_args()
    tasks, inventory = load()
    projections = render(tasks, inventory)
    if args.prompt:
        task = next((t for t in tasks if t['id'] == args.prompt), None)
        require(task is not None, 'unknown task: ' + args.prompt)
        text = (ROOT / task['path']).read_bytes().decode('utf-8')
        prompt, remainder = text.split('```text\n', 1)[1].split('```', 1)
        front = text.split('---\n', 2)[1]
        sys.stdout.buffer.write((prompt + '\nTask metadata:\n' + front + '\nTask card:\n' + remainder).encode('utf-8'))
        return
    for name, expected in projections.items():
        path = ROOT / name
        if args.write:
            path.write_bytes(expected.encode('utf-8'))
        else:
            require(path.exists() and path.read_bytes().decode('utf-8') == expected, 'stale graph projection: ' + name)
    print(f'{len(tasks)} tasks; {sum(len(t["dependencies"]) for t in tasks)} edges; '
          f'{len(layers_for(tasks))} antichain layers; graph and prompts valid')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, TypeError, OSError, json.JSONDecodeError) as error:
        raise SystemExit('roadmap: ' + str(error)) from error
