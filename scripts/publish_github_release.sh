#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if ! command -v gh >/dev/null 2>&1; then
  echo "error: gh CLI is required. install gh, run 'gh auth login', then retry." >&2
  exit 1
fi

VERSION="${1:-}"
if [[ -z "$VERSION" ]]; then
  VERSION="$(awk -F'"' '/^version = /{print $2; exit}' pyproject.toml)"
fi
if [[ -z "$VERSION" ]]; then
  echo "error: unable to resolve version from pyproject.toml or argv" >&2
  exit 1
fi

shift || true

TAG="v${VERSION}"
TITLE="diff-ai feature-oneshot v${VERSION}"
CODEX_ZIP="releases/diff-ai-feature-oneshot-codex-v${VERSION}.zip"
CLAUDE_ZIP="releases/diff-ai-feature-oneshot-claude-v${VERSION}.zip"
CHECKSUMS="releases/SHA256SUMS.txt"

if [[ ! -f "$CODEX_ZIP" || ! -f "$CLAUDE_ZIP" || ! -f "$CHECKSUMS" ]]; then
  echo "release artifacts missing, building first..."
  ./scripts/build_releases.sh "$VERSION"
fi

gh release create "$TAG" \
  "$CODEX_ZIP" \
  "$CLAUDE_ZIP" \
  "$CHECKSUMS" \
  --title "$TITLE" \
  --notes "Codex and Claude feature-oneshot integrations for diff-ai." \
  "$@"

echo "published GitHub release: $TAG"
