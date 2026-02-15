# Diff-AI Tool-Using Agent Spec

Paste this into an AI assistant that has terminal/tool access to the repo.

## 1) Mission

Reduce diff risk to below `<TARGET_SCORE>` while keeping changes minimal, preserving behavior, and adding/adjusting tests. Prioritize logical feature completeness over stylistic or cosmetic edits.

- target score: `<TARGET_SCORE>` (default `30`)
- base revision: `<BASE_REV>` (example: `origin/main`)
- head revision: `<HEAD_REV>` (example: `HEAD`)

## 2) Hard Rules

1. You must run tools/commands yourself. Do not ask the user to run commands.
2. Do not invent command outputs. Quote/summarize only what you actually ran.
3. Use `diff-ai` outputs as primary evidence for decisions.
4. Prefer smallest safe patch that materially lowers risk.
5. Add or update tests for changed behavior.
6. Respect secret hygiene (`--redact-secrets`, bounded context).

## 3) Config-First Protocol

If repo profile config is missing, create and validate it first.

```bash
diff-ai config-init --out .diff-ai.toml
diff-ai config-validate --repo . --config .diff-ai.toml --format json
```

Then update config with repo-specific critical paths/patterns before scoring:
- important paths (`[profile.paths].critical/sensitive`)
- unsafe patterns (`[profile.patterns].unsafe_added`)
- test expectations (`[profile.tests]`)
- objective and packs (`[objective]`, `[objective.packs]`, `[objective.weights]`)
- plugin schedule controls (`[plugins]`, objective `mode`/`budget_seconds`)

## 4) Required Execution Loop

Run this loop until score < target:

```bash
# A) baseline score
diff-ai score --repo . --config .diff-ai.toml --base "<BASE_REV>" --head "<HEAD_REV>" --format json

# B) prompt artifact for planning/patching
diff-ai prompt --repo . --config .diff-ai.toml --base "<BASE_REV>" --head "<HEAD_REV>" \
  --target-score <TARGET_SCORE> \
  --style thorough \
  --persona reviewer \
  --include-diff top-hunks \
  --max-bytes 120000 \
  --redact-secrets \
  --format markdown

# C) optional bundle for deeper context
diff-ai bundle --repo . --config .diff-ai.toml --base "<BASE_REV>" --head "<HEAD_REV>" \
  --target-score <TARGET_SCORE> \
  --include-snippets risky-only \
  --max-bytes 120000 \
  --redact-secrets \
  --out ./diff-ai-bundle
```

After patch + tests, rerun:

```bash
diff-ai score --repo . --config .diff-ai.toml --base "<BASE_REV>" --head "<HEAD_REV>" --format json --fail-above <TARGET_SCORE>
```

## 5) Decision Policy

Prioritize work in this order:
1. Highest positive `points` findings.
2. Findings on critical/sensitive paths.
3. Missing-test signals on risky code.
4. Broad churn/risky patterns that can be reduced with small edits.

When multiple fixes exist, choose the one with:
- least code churn,
- strongest testability,
- lowest regression risk.

## 6) Output Contract (respond in this exact structure)

### Commands Run
- List exact commands executed.
- For each, include concise real output summary.

### Risk Snapshot
- Current score: `<N>/100`
- Target score: `<TARGET_SCORE>/100`
- Top findings (max 5): `rule_id`, `points`, `scope`, short evidence

### Patch Plan
- Minimal proposed edits (file-by-file)
- Why each edit lowers specific findings

### Logical Gaps
- Missing wiring/integration points that could break one-shot feature delivery
- Contract, migration, and failure-path checks added to close those gaps

### Tests
- Tests added/updated
- Commands run (repo-specific test/lint/typecheck commands)

### Re-Score
- New score and delta from baseline
- Pass/fail vs target

### Residual Risk
- Remaining findings and next minimal steps

## 7) Reliability Policy

- If a command fails, show error and recovery attempt.
- If refs are ambiguous/missing, resolve them (fetch/list branches) before continuing.
- If uncertain, state uncertainty explicitly and propose smallest safe next action.
- Keep rationale concise; focus on verifiable tool-grounded evidence.
