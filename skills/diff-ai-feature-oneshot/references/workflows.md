# Diff-AI Workflow Reference

## Baseline Loop

Use this loop for one-shot feature hardening:

```bash
diff-ai config-init --out .diff-ai.toml
diff-ai config-validate --repo . --config .diff-ai.toml --format json
diff-ai plugins --repo . --config .diff-ai.toml --format json --dry-run
diff-ai score --repo . --config .diff-ai.toml --base "<BASE_REV>" --head "<HEAD_REV>" --format json
```

After code + tests:

```bash
diff-ai score --repo . --config .diff-ai.toml --base "<BASE_REV>" --head "<HEAD_REV>" --format json --fail-above <TARGET_SCORE>
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
diff-ai prompt --repo . --config .diff-ai.toml --base "<BASE_REV>" --head "<HEAD_REV>" \
  --target-score <TARGET_SCORE> \
  --include-diff top-hunks \
  --max-bytes 120000 \
  --redact-secrets \
  --format markdown
```

```bash
diff-ai bundle --repo . --config .diff-ai.toml --base "<BASE_REV>" --head "<HEAD_REV>" \
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
