#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

VERSION="${1:-}"
if [[ -z "$VERSION" ]]; then
  VERSION="$(python3 - <<'PY'
from pathlib import Path
version = ""
init_path = Path("diff_ai/__init__.py")
if init_path.exists():
    for line in init_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("__version__"):
            version = line.split("=", 1)[1].strip().strip('"').strip("'")
            break
print(version)
PY
)"
fi

if [[ -z "$VERSION" ]]; then
  echo "error: unable to resolve version from diff_ai/__init__.py or argv" >&2
  exit 1
fi

CODEX_SKILL_PATH="skills/diff-ai-feature-oneshot"
CLAUDE_CMD_PATH=".claude/commands/diff-ai-feature-oneshot.md"
SKILL_BIN_PATH="$CODEX_SKILL_PATH/scripts/diff-ai"
SOURCE_PACKAGE_PATH="diff_ai"
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
if [[ ! -f "$SKILL_BIN_PATH" ]]; then
  echo "error: missing $SKILL_BIN_PATH" >&2
  exit 1
fi
if [[ ! -d "$SOURCE_PACKAGE_PATH" ]]; then
  echo "error: missing $SOURCE_PACKAGE_PATH" >&2
  exit 1
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

CODEX_STAGE="$TMP_DIR/codex"
CLAUDE_STAGE="$TMP_DIR/claude"
CODEX_STAGE_SKILL="$CODEX_STAGE/skills/diff-ai-feature-oneshot"
CLAUDE_STAGE_TOOL="$CLAUDE_STAGE/.claude/tools/diff-ai-feature-oneshot"

mkdir -p "$CODEX_STAGE/skills"
cp -R "$CODEX_SKILL_PATH" "$CODEX_STAGE/skills/"
mkdir -p "$CODEX_STAGE_SKILL/runtime"
cp -R "$SOURCE_PACKAGE_PATH" "$CODEX_STAGE_SKILL/runtime/"

mkdir -p "$CLAUDE_STAGE/.claude/commands"
cp "$CLAUDE_CMD_PATH" "$CLAUDE_STAGE/.claude/commands/"
mkdir -p "$CLAUDE_STAGE_TOOL/scripts" "$CLAUDE_STAGE_TOOL/runtime"
cp "$SKILL_BIN_PATH" "$CLAUDE_STAGE_TOOL/scripts/diff-ai"
cp -R "$SOURCE_PACKAGE_PATH" "$CLAUDE_STAGE_TOOL/runtime/"

find "$CODEX_STAGE" "$CLAUDE_STAGE" -type d -name "__pycache__" -prune -exec rm -rf {} +

mkdir -p "$RELEASE_DIR"
rm -f "$CODEX_ZIP" "$CLAUDE_ZIP" "$CHECKSUMS_FILE"

(cd "$CODEX_STAGE" && zip -r "$ROOT_DIR/$CODEX_ZIP" skills >/dev/null)
(cd "$CLAUDE_STAGE" && zip -r "$ROOT_DIR/$CLAUDE_ZIP" .claude >/dev/null)

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
