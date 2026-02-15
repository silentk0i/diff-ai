#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

VERSION="${1:-}"
if [[ -z "$VERSION" ]]; then
  VERSION="$(awk -F'"' '/^version = /{print $2; exit}' pyproject.toml)"
fi

if [[ -z "$VERSION" ]]; then
  echo "error: unable to resolve version from pyproject.toml or argv" >&2
  exit 1
fi

CODEX_SKILL_PATH="skills/diff-ai-feature-oneshot"
CLAUDE_CMD_PATH=".claude/commands/diff-ai-feature-oneshot.md"
RELEASE_DIR="releases"
CODEX_ZIP="$RELEASE_DIR/diff-ai-feature-oneshot-codex-v${VERSION}.zip"
CLAUDE_ZIP="$RELEASE_DIR/diff-ai-feature-oneshot-claude-v${VERSION}.zip"
CHECKSUMS_FILE="$RELEASE_DIR/SHA256SUMS.txt"

if [[ ! -d "$CODEX_SKILL_PATH" ]]; then
  echo "error: missing $CODEX_SKILL_PATH" >&2
  exit 1
fi
if [[ ! -f "$CLAUDE_CMD_PATH" ]]; then
  echo "error: missing $CLAUDE_CMD_PATH" >&2
  exit 1
fi

mkdir -p "$RELEASE_DIR"
rm -f "$CODEX_ZIP" "$CLAUDE_ZIP" "$CHECKSUMS_FILE"

zip -r "$CODEX_ZIP" "$CODEX_SKILL_PATH" >/dev/null
zip -r "$CLAUDE_ZIP" "$CLAUDE_CMD_PATH" >/dev/null

(
  cd "$RELEASE_DIR"
  sha256sum \
    "diff-ai-feature-oneshot-codex-v${VERSION}.zip" \
    "diff-ai-feature-oneshot-claude-v${VERSION}.zip" \
    > "SHA256SUMS.txt"
  sha256sum -c "SHA256SUMS.txt" >/dev/null
)

echo "built release artifacts:"
echo "- $CODEX_ZIP"
echo "- $CLAUDE_ZIP"
echo "- $CHECKSUMS_FILE"
