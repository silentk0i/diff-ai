# diff-ai

`diff-ai` is a local, deterministic diff reviewer skill for AI feature one-shots.

## Install Skill Releases

Build release zips:

```bash
./scripts/build_releases.sh
```

Artifacts:
- `releases/diff-ai-feature-oneshot-codex-v<VERSION>.zip`
- `releases/diff-ai-feature-oneshot-claude-v<VERSION>.zip`
- `releases/SHA256SUMS.txt`

### Codex

```bash
mkdir -p "$CODEX_HOME/skills"
unzip -o releases/diff-ai-feature-oneshot-codex-v<VERSION>.zip -d .
cp -R skills/diff-ai-feature-oneshot "$CODEX_HOME/skills/diff-ai-feature-oneshot"
```

Use:

```text
$diff-ai-feature-oneshot
```

### Claude Code

```bash
unzip -o releases/diff-ai-feature-oneshot-claude-v<VERSION>.zip -d .
```

Use:

```text
/diff-ai-feature-oneshot origin/main HEAD 30
```

## Runtime Command (Direct)

Codex-installed path:

```bash
DIFF_AI_BIN="${CODEX_HOME:-$HOME/.codex}/skills/diff-ai-feature-oneshot/scripts/diff-ai"
```

Local checkout path:

```bash
DIFF_AI_BIN="./skills/diff-ai-feature-oneshot/scripts/diff-ai"
```

Examples:

```bash
"$DIFF_AI_BIN" --help
"$DIFF_AI_BIN" config-init --out .diff-ai.toml
"$DIFF_AI_BIN" score --repo . --base origin/main --head HEAD --format json
"$DIFF_AI_BIN" prompt --repo . --base origin/main --head HEAD --format markdown > prompt.md
```

Config example: `examples/config.toml`

## Repo Layout

- Skill definition: `skills/diff-ai-feature-oneshot/SKILL.md`
- Codex metadata: `skills/diff-ai-feature-oneshot/agents/openai.yaml`
- Claude command: `.claude/commands/diff-ai-feature-oneshot.md`
- Standalone runtime: `diff_ai/standalone.py`
