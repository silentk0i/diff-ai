---
description: Run diff-ai one-shot feature hardening loop focused on logic, integration, and tests.
argument-hint: [base_ref] [head_ref] [target_score]
---

Use `diff-ai` to reduce feature risk with `feature_oneshot` objective by default.

Parse arguments:
- `base_ref`: default `origin/main`
- `head_ref`: default `HEAD`
- `target_score`: default `30`

Execute this workflow:

1. Ensure config exists and validates.
```bash
diff-ai config-init --out .diff-ai.toml
diff-ai config-validate --repo . --config .diff-ai.toml --format json
```

2. Preview plugin schedule under current mode/budget.
```bash
diff-ai plugins --repo . --config .diff-ai.toml --format json --dry-run
```

3. Baseline score and findings.
```bash
diff-ai score --repo . --config .diff-ai.toml --base "<base_ref>" --head "<head_ref>" --format json
```

4. Build prompt artifact for patch planning.
```bash
diff-ai prompt --repo . --config .diff-ai.toml --base "<base_ref>" --head "<head_ref>" \
  --target-score <target_score> \
  --include-diff top-hunks \
  --max-bytes 120000 \
  --redact-secrets \
  --format markdown
```

5. Propose and apply the smallest safe patch plus tests, then re-score.
```bash
diff-ai score --repo . --config .diff-ai.toml --base "<base_ref>" --head "<head_ref>" --format json --fail-above <target_score>
```

Response format:
1. Commands Run
2. Risk Snapshot
3. Patch Plan
4. Tests
5. Re-Score
6. Residual Risk
