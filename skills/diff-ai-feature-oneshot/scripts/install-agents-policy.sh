#!/usr/bin/env bash
set -euo pipefail

REPO="."
MODE="ai-task"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo)
      REPO="${2:-}"
      shift 2
      ;;
    --mode)
      MODE="${2:-}"
      shift 2
      ;;
    *)
      echo "error: unknown arg: $1" >&2
      echo "usage: $0 [--repo <path>] [--mode ai-task|milestone]" >&2
      exit 2
      ;;
  esac
done

if [[ "$MODE" != "ai-task" && "$MODE" != "milestone" ]]; then
  echo "error: --mode must be one of: ai-task, milestone" >&2
  exit 2
fi

TARGET_DIR="$(cd "$REPO" && pwd)"
TARGET_FILE="$TARGET_DIR/AGENTS.md"

if [[ "$MODE" == "ai-task" ]]; then
  SCORE_CMD='"$DIFF_AI_BIN" score --repo . --config .diff-ai.toml --review-mode ai-task --format json'
else
  SCORE_CMD='"$DIFF_AI_BIN" score --repo . --config .diff-ai.toml --review-mode milestone --base origin/main --head HEAD --format json'
fi

BLOCK_FILE="$(mktemp)"
trap 'rm -f "$BLOCK_FILE"' EXIT

cat >"$BLOCK_FILE" <<'EOF'
<!-- diff-ai-feature-oneshot:begin -->
## Diff-AI Per-Task Policy

When code changes are made in a turn and control is returned to the user:
1. Run:
   `DIFF_AI_BIN="${CODEX_HOME:-$HOME/.codex}/skills/diff-ai-feature-oneshot/scripts/diff-ai"`
   `__DIFF_AI_SCORE_CMD__`
2. Report score and top findings in the final response.
3. If score is above target, propose the smallest safe follow-up patch plan.

Apply this policy every turn with code edits, even when the skill was not re-invoked.
Do not bypass policy by disabling `[rules].enable` or weakening config for score-only reasons.
<!-- diff-ai-feature-oneshot:end -->
EOF

sed -i "s|__DIFF_AI_SCORE_CMD__|$SCORE_CMD|g" "$BLOCK_FILE"

if [[ -f "$TARGET_FILE" ]] && grep -q "diff-ai-feature-oneshot:begin" "$TARGET_FILE"; then
  TMP_FILE="$(mktemp)"
  awk -v block="$BLOCK_FILE" '
    BEGIN {in_block=0; replaced=0}
    /<!-- diff-ai-feature-oneshot:begin -->/ {
      while ((getline line < block) > 0) print line
      close(block)
      in_block=1
      replaced=1
      next
    }
    /<!-- diff-ai-feature-oneshot:end -->/ {
      in_block=0
      next
    }
    !in_block {print}
    END {
      if (!replaced) {
        print ""
        while ((getline line < block) > 0) print line
        close(block)
      }
    }
  ' "$TARGET_FILE" >"$TMP_FILE"
  mv "$TMP_FILE" "$TARGET_FILE"
else
  {
    if [[ -f "$TARGET_FILE" && -s "$TARGET_FILE" ]]; then
      cat "$TARGET_FILE"
      echo
    fi
    cat "$BLOCK_FILE"
  } >"$TARGET_FILE"
fi

echo "wrote diff-ai policy block to: $TARGET_FILE"
echo "mode: $MODE"
