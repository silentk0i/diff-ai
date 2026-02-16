---
name: diff-ai-feature-oneshot
description: Optimize one-shot feature delivery with diff-ai by finding logical, integration, and test-adequacy gaps in a git diff, then driving a minimal fix loop to reduce risk. Use when an AI-generated or human-authored feature needs higher first-pass correctness, stronger cross-layer wiring, better failure-path coverage, or faster review confidence before merge.
---

# Diff-AI Feature Oneshot

## Overview

Use `diff-ai` to run an objective-driven, deterministic review loop focused on logical feature completeness. Favor `feature_oneshot` objective by default and switch to `security_strict` only when requested.

Resolve the bundled runtime command first:

```bash
DIFF_AI_BIN="${CODEX_HOME:-$HOME/.codex}/skills/diff-ai-feature-oneshot/scripts/diff-ai"
```

## Run Workflow

1. Ensure config exists and validates.
2. Preview plugin schedule under current mode/budget.
3. Run baseline score.
4. Update config profile sections to match the repo.
5. Patch minimally to address highest-value logic/integration/test findings.
6. Add or update tests that prove changed behavior.
7. Re-score until at or below target.

Run:

```bash
"$DIFF_AI_BIN" config-init --out .diff-ai.toml
"$DIFF_AI_BIN" config-validate --repo . --config .diff-ai.toml --format json
"$DIFF_AI_BIN" plugins --repo . --config .diff-ai.toml --format json --dry-run
"$DIFF_AI_BIN" score --repo . --config .diff-ai.toml --base "<BASE_REV>" --head "<HEAD_REV>" --format json
```

After edits and tests:

```bash
"$DIFF_AI_BIN" score --repo . --config .diff-ai.toml --base "<BASE_REV>" --head "<HEAD_REV>" --format json --fail-above <TARGET_SCORE>
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
- Keep `[rules].enable` explicit and stable unless the user explicitly asks to change rule coverage.
- Keep repo-specific profile sections current:
  - `[profile.paths]` (critical/sensitive paths)
  - `[profile.patterns]` (unsafe patterns)
  - `[profile.tests]` (required_for/test_globs)
- Add obsolete entry cleanup to every config update pass.

## Emit Response Contract

Use this exact structure in responses:

1. `Commands Run`
2. `Risk Snapshot` (score, top findings, plugin schedule highlights)
3. `Patch Plan` (minimal edits and rationale)
4. `Tests` (changes and command summaries)
5. `Re-Score` (new score, delta, pass/fail)
6. `Residual Risk` (remaining gaps and smallest next step)

Do not append raw full diffs, full prompt markdown, or full changed-file dumps after the response.

## Enforce Guardrails

- Run tools directly; do not ask the user to run commands.
- Report only observed command output.
- Keep patches behavior-preserving unless change is explicitly required.
- Add tests for changed behavior, contracts, and failure paths.
- If a command fails, show recovery attempt and smallest safe next action.
- Never reduce score by disabling rules/plugins/packs unless the user explicitly requests a policy change.
- Keep final output concise and end at `Residual Risk`.

## Use References

- Read `references/workflows.md` for command recipes, objective tuning, and stop criteria.
