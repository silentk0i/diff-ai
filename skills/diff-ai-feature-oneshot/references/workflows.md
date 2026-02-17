# Diff-AI Workflow Reference

## Baseline Loop

Install persistent AGENTS policy (recommended for Codex multi-turn sessions):

```bash
"${CODEX_HOME:-$HOME/.codex}/skills/diff-ai-feature-oneshot/scripts/install-agents-policy.sh" --repo . --mode ai-task
```

Use this loop for one-shot feature hardening:

```bash
DIFF_AI_BIN="${CODEX_HOME:-$HOME/.codex}/skills/diff-ai-feature-oneshot/scripts/diff-ai"
"$DIFF_AI_BIN" config-init --out .diff-ai.toml
"$DIFF_AI_BIN" config-validate --repo . --config .diff-ai.toml --format json
"$DIFF_AI_BIN" plugins --repo . --config .diff-ai.toml --format json --dry-run
"$DIFF_AI_BIN" score --repo . --config .diff-ai.toml --review-mode ai-task --format json
```

Milestone alternative:

```bash
"$DIFF_AI_BIN" score --repo . --config .diff-ai.toml --review-mode milestone --base "<BASE_REV>" --head "<HEAD_REV>" --format json
```

Before patching, update profile sections in `.diff-ai.toml`:

- Add/remove `[profile.paths].critical` and `sensitive` globs for real critical/sensitive areas.
- Add/remove `[profile.patterns].unsafe_added` regexes based on observed repo risk patterns.
- Add/remove `[profile.tests].required_for` and refine `test_globs` to match actual test layout.
- Keep `[rules].enable` present; do not comment it out to lower score.

After code + tests:

```bash
"$DIFF_AI_BIN" score --repo . --config .diff-ai.toml --review-mode ai-task --format json --fail-above <TARGET_SCORE>
```

## Objective Presets

- `feature_oneshot`:
  - default for logic/integration/test completeness
  - security pack is opt-in
- `security_strict`:
  - use for explicitly security-focused requests

## Time Budget Tuning

- `fast`:
  - shortest runtime
  - runs only low-cost plugins
- `standard`:
  - balanced default
- `deep`:
  - highest coverage, longer runtime

Increase/decrease:

- `[objective].mode`
- `[objective].budget_seconds`
- `[plugins].enable` / `[plugins].disable`

## Prompt + Bundle

Use when handing off to another AI agent:

```bash
"$DIFF_AI_BIN" prompt --repo . --config .diff-ai.toml --review-mode ai-task \
  --target-score <TARGET_SCORE> \
  --include-diff top-hunks \
  --max-bytes 120000 \
  --redact-secrets \
  --format markdown
```

```bash
"$DIFF_AI_BIN" bundle --repo . --config .diff-ai.toml --review-mode ai-task \
  --target-score <TARGET_SCORE> \
  --include-snippets risky-only \
  --max-bytes 120000 \
  --redact-secrets \
  --out ./diff-ai-bundle
```

## Stop Criteria

Stop when all are true:

- score at or below target
- no high-priority logic/integration findings remain
- changed behavior has explicit test coverage
- residual risk is documented with smallest next step

## Output Hygiene

- Do not emit full diff text or full prompt markdown in final response.
- Summarize key command outputs only.
- End cleanly after `Residual Risk`.
