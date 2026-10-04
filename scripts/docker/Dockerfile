FROM node:24.18.0@sha256:5711a0d445a1af54af9589066c646df387d1831a608226f4cd694fc59e745059

# Toolchain only: no source, test output, host Git metadata, or package caches.
RUN apt-get update \
    && apt-get install -y --no-install-recommends bash git make python3-jsonschema shellcheck shfmt time \
    && rm -rf /var/lib/apt/lists/* \
    && printf 'git-locks isolated test runtime v1\n' > /opt/git-locks-test-runtime
USER node
WORKDIR /work
ENV HOME=/home/node PYTHONDONTWRITEBYTECODE=1 GIT_CONFIG_NOSYSTEM=1
CMD ["sleep", "infinity"]
