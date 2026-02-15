---
name: diff-ai-feature-oneshot
description: Optimize one-shot feature delivery with diff-ai by finding logical, integration, and test-adequacy gaps in a git diff, then driving a minimal fix loop to reduce risk. Use when an AI-generated or human-authored feature needs higher first-pass correctness, stronger cross-layer wiring, better failure-path coverage, or faster review confidence before merge.
---

# Diff-AI Feature Oneshot

## Overview

Use `diff-ai` to run an objective-driven, deterministic review loop focused on logical feature completeness. Favor `feature_oneshot` objective by default and switch to `security_strict` only when requested.

## Run Workflow

1. Ensure config exists and validates.
2. Preview plugin schedule under current mode/budget.
3. Run baseline score.
4. Patch minimally to address highest-value logic/integration/test findings.
5. Add or update tests that prove changed behavior.
6. Re-score until at or below target.

Run:

```bash
diff-ai config-init --out .diff-ai.toml
diff-ai config-validate --repo . --config .diff-ai.toml --format json
diff-ai plugins --repo . --config .diff-ai.toml --format json --dry-run
diff-ai score --repo . --config .diff-ai.toml --base "<BASE_REV>" --head "<HEAD_REV>" --format json
```

After edits and tests:

```bash
diff-ai score --repo . --config .diff-ai.toml --base "<BASE_REV>" --head "<HEAD_REV>" --format json --fail-above <TARGET_SCORE>
```

## Apply Objective Policy

- Default to `[objective].name = "feature_oneshot"`.
- Keep security pack opt-in unless user requests security-first analysis.
- Tune runtime with:
  - `[objective].mode = "fast" | "standard" | "deep"`
  - `[objective].budget_seconds = <N>`
- Tune plugin and pack coverage with:
  - `[objective.packs].enable/disable`
  - `[plugins].enable/disable`

## Emit Response Contract

Use this exact structure in responses:

1. `Commands Run`
2. `Risk Snapshot` (score, top findings, plugin schedule highlights)
3. `Patch Plan` (minimal edits and rationale)
4. `Tests` (changes and command summaries)
5. `Re-Score` (new score, delta, pass/fail)
6. `Residual Risk` (remaining gaps and smallest next step)

## Enforce Guardrails

- Run tools directly; do not ask the user to run commands.
- Report only observed command output.
- Keep patches behavior-preserving unless change is explicitly required.
- Add tests for changed behavior, contracts, and failure paths.
- If a command fails, show recovery attempt and smallest safe next action.

## Use References

- Read `references/workflows.md` for command recipes, objective tuning, and stop criteria.
