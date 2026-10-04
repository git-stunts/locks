#!/usr/bin/env bash
# Called only after the host runner has copied regular source files into tmpfs.
set -euo pipefail
source scripts/require-docker.sh
[[ ! -e .git ]]
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_COMMON_DIR GIT_PREFIX GIT_OBJECT_DIRECTORY GIT_ALTERNATE_OBJECT_DIRECTORIES GIT_NAMESPACE
# The evidence verifier and demos need a commit. This repository has no host
# history, remotes, hooks, alternates, credentials, or linked worktrees.
git init -q -b isolated-input
git add --all
git -c user.name='git-locks tests' -c user.email=tests@example.invalid commit -qm 'Isolated copied test input'
remotes="$(git remote)"
[[ -z "${remotes}" ]]
[[ ! -e .git/objects/info/alternates && ! -e .git/commondir ]]
git_dir="$(git rev-parse --absolute-git-dir)"
[[ "${git_dir}" == /work/source/.git ]]
printf 'Docker input: fresh local Git fixture; no remotes, host mounts, or network.\n'
