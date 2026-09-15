# Security

git-locks writes only under `refs/locks/` in the repository it runs in, never pushes, never reads the network, and executes no content from lock records. Holder names and job ids are stored as plain text in blobs; do not put secrets in them.

To report a vulnerability, open a private security advisory on the GitHub repository rather than a public issue. Include the git and bash versions, the command, and the smallest repository state that reproduces it. Reports are acknowledged within a week.
