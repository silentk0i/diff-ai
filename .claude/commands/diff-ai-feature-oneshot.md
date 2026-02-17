---
description: Run diff-ai one-shot feature hardening loop focused on logic, integration, and tests.
argument-hint: [review_mode] [base_ref] [head_ref] [target_score]
---

Use `diff-ai` to reduce feature risk with `feature_oneshot` objective by default.

Parse arguments:
- `review_mode`: default `ai-task`, allowed `ai-task|milestone`
- `base_ref`: default `origin/main`
- `head_ref`: default `HEAD`
- `target_score`: default `30`

Set runtime command:

```bash
DIFF_AI_BIN="./.claude/tools/diff-ai-feature-oneshot/scripts/diff-ai"
```

Execute this workflow:

1. Ensure config exists and validates.
```bash
"$DIFF_AI_BIN" config-init --out .diff-ai.toml
"$DIFF_AI_BIN" config-validate --repo . --config .diff-ai.toml --format json
```

2. Preview plugin schedule under current mode/budget.
```bash
"$DIFF_AI_BIN" plugins --repo . --config .diff-ai.toml --format json --dry-run
```

3. Ensure `.diff-ai.toml` profile sections are repo-specific and current:
- update/add/remove `[profile.paths]` entries based on actual critical/sensitive paths
- update/add/remove `[profile.patterns]` entries based on repo-specific risky patterns
- update/add/remove `[profile.tests]` entries based on real test layout and required coverage
- keep `[rules].enable` explicit; do not comment it out to lower score

4. Baseline score and findings.

If `review_mode=ai-task` (default), scope to changes since last AI checkpoint (includes committed and uncommitted work):
```bash
"$DIFF_AI_BIN" score --repo . --config .diff-ai.toml --review-mode ai-task --format json
```

If `review_mode=milestone`, scope to explicit commit range:
```bash
"$DIFF_AI_BIN" score --repo . --config .diff-ai.toml --review-mode milestone --base "<base_ref>" --head "<head_ref>" --format json
```

5. Build prompt artifact for patch planning and write to a file (do not print full markdown/diff in response).

For `review_mode=ai-task`:
```bash
"$DIFF_AI_BIN" prompt --repo . --config .diff-ai.toml --review-mode ai-task \
  --target-score <target_score> \
  --include-diff top-hunks \
  --max-bytes 120000 \
  --redact-secrets \
  --format markdown > /tmp/diff-ai-prompt.md
```

For `review_mode=milestone`:
```bash
"$DIFF_AI_BIN" prompt --repo . --config .diff-ai.toml --review-mode milestone --base "<base_ref>" --head "<head_ref>" \
  --target-score <target_score> \
  --include-diff top-hunks \
  --max-bytes 120000 \
  --redact-secrets \
  --format markdown > /tmp/diff-ai-prompt.md
```

6. Propose and apply the smallest safe patch plus tests, then re-score.

For `review_mode=ai-task`:
```bash
"$DIFF_AI_BIN" score --repo . --config .diff-ai.toml --review-mode ai-task --format json --fail-above <target_score>
```

For `review_mode=milestone`:
```bash
"$DIFF_AI_BIN" score --repo . --config .diff-ai.toml --review-mode milestone --base "<base_ref>" --head "<head_ref>" --format json --fail-above <target_score>
```

Response format:
1. Commands Run
2. Risk Snapshot
3. Patch Plan
4. Tests
5. Re-Score
6. Residual Risk

Output hygiene:
- Do not dump full diffs, full prompt markdown, or full changed-file content in the final response.
- Keep finish concise and stop at `Residual Risk`.
