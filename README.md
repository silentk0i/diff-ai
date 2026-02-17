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

### Why `config.toml` Matters

`diff-ai` is deterministic, and `config.toml` is what makes it repo-aware.
Without a tuned config, scoring is generic. With a tuned config, the skill reflects your codebase's real risk profile.

Start from `examples/config.toml`, then copy it to `.diff-ai.toml` in your repo and customize:
- `[profile.paths]`: critical/sensitive areas (auth, payments, infra, migrations, etc.)
- `[profile.patterns]`: risky patterns specific to your stack
- `[profile.tests]`: where tests live and which paths require tests
- `[rules]` and `[objective]`: analysis policy and speed/coverage tradeoffs

The skill can generate `.diff-ai.toml` and update sections during its workflow.
Treat those edits as suggestions: review them, keep what matches your repo, and change anything that does not fit your standards.

This is the main mechanism that molds diff-ai behavior to your own system.

### Review Modes

`diff-ai` supports two diff scopes:
- `ai-task`: review only what changed since the last AI checkpoint (includes committed and uncommitted changes). Best for iterative AI task loops.
- `milestone`: review an explicit commit range (`base..head`).

Set in config:

```toml
[review]
mode = "ai-task" # or "milestone"
state_file = ".diff-ai-task-state.json"
```

Or override per command with `--review-mode ai-task|milestone`.

### Keep It Running Across Turns (Codex `AGENTS.md`)

Skills are often turn-scoped. If you want diff-ai to run after every AI coding task without re-invoking the skill each turn, install a repo `AGENTS.md` policy block once:

```bash
"${CODEX_HOME:-$HOME/.codex}/skills/diff-ai-feature-oneshot/scripts/install-agents-policy.sh" \
  --repo . \
  --mode ai-task
```

For milestone mode policy instead:

```bash
"${CODEX_HOME:-$HOME/.codex}/skills/diff-ai-feature-oneshot/scripts/install-agents-policy.sh" \
  --repo . \
  --mode milestone
```

The installer is idempotent and updates only the managed diff-ai policy block.

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
/diff-ai-feature-oneshot ai-task
# milestone example:
# /diff-ai-feature-oneshot milestone origin/main HEAD 30
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
"$DIFF_AI_BIN" score --repo . --review-mode ai-task --format json
"$DIFF_AI_BIN" score --repo . --review-mode milestone --base origin/main --head HEAD --format json
"$DIFF_AI_BIN" prompt --repo . --review-mode ai-task --format markdown > prompt.md
```

Config example: `examples/config.toml`

## Repo Layout

- Skill definition: `skills/diff-ai-feature-oneshot/SKILL.md`
- Codex metadata: `skills/diff-ai-feature-oneshot/agents/openai.yaml`
- Claude command: `.claude/commands/diff-ai-feature-oneshot.md`
- Standalone runtime: `diff_ai/standalone.py`
