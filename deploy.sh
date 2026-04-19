#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: $0 <user@host> <remote-dir>"
  echo "  Example: $0 user@example.com /var/www/html"
  exit 1
}

[ $# -eq 2 ] || usage

REMOTE="$1"
REMOTE_DIR="$2"
VERSION=$(grep -m1 '^version' pyproject.toml | sed 's/.*"\(.*\)"/\1/')

echo "==> Syncing source to ${REMOTE}:${REMOTE_DIR}"
rsync -az --delete --info=progress2,stats2 \
  --exclude='.git' \
  --exclude='.venv' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='.ruff_cache' \
  --exclude='dist' \
  --exclude='config' \
  . "${REMOTE}:${REMOTE_DIR}"

echo "==> Building image on remote (version ${VERSION})"
ssh "${REMOTE}" bash -s -- "${REMOTE_DIR}" "${VERSION}" <<'EOF'
  set -euo pipefail
  DIR=$1
  VERSION=$2
  cd "$DIR"
  docker build \
    -t "imap-mcp" \
    -t "imap-mcp:${VERSION}" \
    -t "imap-mcp:latest" \
    .
  echo "==> Build complete: imap-mcp, imap-mcp:${VERSION}, imap-mcp:latest"
EOF
