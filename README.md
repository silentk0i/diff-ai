# diff-ai

`diff-ai` is an offline, deterministic CLI that scores the risk of a git diff.

It exists to make review risk visible early, before merge:
- Produce a numeric risk score (`0-100`).
- Explain why risk is high (findings, evidence, suggestions).
- Support machine-readable JSON for CI gates.
- Generate LLM-ready handoff docs without making any API calls.
- Optimize one-shot feature delivery with a logic-first default objective.

## Why Use It

`diff-ai` helps teams:
- Prioritize risky changes during code review.
- Gate pull requests with a simple threshold (`--fail-above`).
- Run repeatable local/CI checks without external dependencies.
- Hand off a structured review packet to any LLM workflow.

## Install

### With `pipx` (recommended for CLI usage)

```bash
pipx install diff-ai
```

### With `pip` (local project / editable dev install)

```bash
pip install diff-ai
```

For local development in this repo:

```bash
pip install -e ".[dev]"
```

## Commands

Show all commands:

```bash
diff-ai --help
```

Current CLI commands:
- `diff-ai score`
- `diff-ai explain`
- `diff-ai prompt`
- `diff-ai bundle`
- `diff-ai rules`
- `diff-ai plugins`
- `diff-ai config`
- `diff-ai config-init`
- `diff-ai config-validate`

## Quickstart

Score your current working tree:

```bash
diff-ai score --repo . --format human
```

Score a revision range:

```bash
diff-ai score --repo . --base origin/main --head HEAD --format json
```

Read diff from stdin:

```bash
git diff --no-color origin/main..HEAD | diff-ai score --stdin --format json
```

Use include/exclude path filters:

```bash
git diff --no-color origin/main..HEAD | diff-ai score --stdin \
  --include "src/**" \
  --exclude "docs/**"
```

## Typical Workflows

### 1) Manual Review

Use this in local review loops:

```bash
diff-ai score --repo . --base origin/main --head HEAD
diff-ai explain --repo . --base origin/main --head HEAD
```

If score is high, inspect findings and reduce risky patterns before opening/merging.

### 2) CI Gate

Fail CI when risk exceeds threshold:

```bash
diff-ai score --repo . --base "$BASE_SHA" --head "$HEAD_SHA" --format json --fail-above 45
```

### 3) LLM Patch Loop

1. Run risk analysis.
2. Ensure repo config/profile is initialized.
3. Generate a prompt or bundle.
4. Paste prompt into your LLM tool.
5. Apply patch and add tests.
6. Re-run score until below target.

Example:

```bash
# 1) analyze
diff-ai score --repo . --base origin/main --head HEAD --format human
diff-ai explain --repo . --base origin/main --head HEAD

# 2) create and validate repo config/profile
diff-ai config-init --out .diff-ai.toml
diff-ai config-validate --repo . --config .diff-ai.toml --format json

# 3) generate prompt
git diff --no-color origin/main..HEAD | diff-ai prompt --stdin --config .diff-ai.toml \
  --target-score 30 \
  --persona reviewer \
  --style thorough \
  --include-diff top-hunks \
  --redact-secrets > prompt.md

# or generate a full bundle
git diff --no-color origin/main..HEAD | diff-ai bundle --stdin --config .diff-ai.toml \
  --out ./artifacts/diff-ai-bundle \
  --include-snippets risky-only \
  --redact-secrets

# 4) paste prompt.md into your LLM
# 5) apply patch + add tests

# 6) re-check until score is below target
diff-ai score --repo . --config .diff-ai.toml --base origin/main --head HEAD --fail-above 30
```

## LLM Handoff

### `diff-ai prompt`

Build a single markdown document for LLM review:

```bash
git diff --no-color origin/main..HEAD | diff-ai prompt --stdin --config .diff-ai.toml \
  --target-score 30 \
  --style thorough \
  --persona security \
  --include-diff risky-only \
  --max-bytes 120000 \
  --redact-secrets \
  --format markdown > prompt.md
```

### `diff-ai bundle`

Create a handoff package with:
- `findings.json`
- `findings.md`
- `patch.diff`
- `prompt.md`

```bash
git diff --no-color origin/main..HEAD | diff-ai bundle --stdin --config .diff-ai.toml \
  --out ./diff-ai-bundle \
  --include-snippets minimal \
  --redact-secrets
```

Write zip instead of directory:

```bash
git diff --no-color origin/main..HEAD | diff-ai bundle --stdin --config .diff-ai.toml \
  --out ./diff-ai-bundle.zip \
  --zip
```

## Configuration

Config search order (when `--config` is not provided):
1. `.diff-ai.toml`
2. `diff-ai.toml`
3. `pyproject.toml` under `[tool.diff_ai]` or `[tool."diff-ai"]`

Override config path explicitly:

```bash
diff-ai score --repo . --config ./configs/risk.toml --base origin/main --head HEAD --format json
```

Example:

```toml
format = "json"
fail_above = 40
include = ["src/**"]
exclude = ["docs/**"]

[objective]
name = "feature_oneshot" # or "security_strict"
mode = "standard"        # fast|standard|deep
budget_seconds = 15

[plugins]
include_builtin = true
enable = []              # optional explicit plugin IDs
disable = []

[objective.packs]
enable = []              # example: ["security"]
disable = []

[objective.weights]
logic = 1.30
integration = 1.15
test_adequacy = 1.35
security = 0.60
quality = 1.00
profile = 1.00

[rules]
enable = ["magnitude", "critical_paths", "test_signals", "profile_signals"] # optional override
disable = ["docs_only"]

[llm]
style = "paranoid"
persona = "security"
target_score = 25
include_diff = "top-hunks"
include_snippets = "risky-only"
max_bytes = 100000
redact_secrets = true
rubric = [
  "do not break API contracts",
  "add regression tests for security-sensitive changes",
]

[profile.paths]
critical = [
  { glob = "src/payments/**", points = 20, reason = "money movement path" },
  { glob = "src/auth/**", points = 16, reason = "authentication boundary" },
]
sensitive = [
  { glob = "infra/**", points = 10, reason = "deploy surface" },
]

[profile.patterns]
unsafe_added = [
  { regex = "\\beval\\(", points = 12, reason = "dynamic eval introduced" },
  { regex = "shell\\s*=\\s*True", points = 10, reason = "shell execution enabled" },
]

[profile.tests]
required_for = ["src/payments/**", "infra/**"]
test_globs = ["tests/**", "**/*_test.py"]
```

Objective notes:
- `feature_oneshot` (default): logic/integration/test coverage first; security pack is opt-in.
- `security_strict`: enables security-focused rules and higher security weighting.
- Explicit `[rules].enable` still overrides pack defaults when you need a custom set.
- Plugins are scheduled by `objective.mode` and `objective.budget_seconds`.
  - `fast`: run only low-cost plugins.
  - `standard`: balanced plugin coverage (default).
  - `deep`: allows higher-cost plugins.
- Built-in plugins:
  - `deferred_work_markers` (logic, ~1s)
  - `cross_layer_touchpoints` (integration, ~4s)
  - `network_exposure_probe` (security, ~3s)

Inspect resolved config:

```bash
diff-ai config --repo . --format json
```

Bootstrap and validate config:

```bash
diff-ai config-init --out .diff-ai.toml
diff-ai config-validate --repo . --config .diff-ai.toml --format json
```

List active/available rules:

```bash
diff-ai rules --repo . --format human
```

List plugins and preview scheduler decisions:

```bash
diff-ai plugins --repo . --format json --dry-run
```

See also:
- `examples/config.toml`
- `examples/llm-review-packet.md`
- `examples/llm-review-packet-security.md`

## Prompting Strategy

`examples/llm-review-packet.md` uses current tool-agent prompt design patterns:
- explicit objective and hard constraints
- mandatory tool-use protocol (no simulated output)
- config-first setup for repo-specific risk signals
- iterative execute-verify loop with stop criteria
- strict response contract for reproducibility
- bounded context and secret-redaction requirements

## Security Notes

- Diffs may contain credentials, tokens, or private data.
- Use `--redact-secrets` when generating `prompt` or `bundle`.
- Use `--max-bytes` to limit exposed context in handoff docs.
- Prefer `--include-diff risky-only` or `top-hunks` for least exposure.
- Review generated artifacts before sharing externally.

## CI (GitHub Actions)

Add a PR workflow that runs quality checks and a diff risk gate.

```yaml
name: ci

on:
  pull_request:

jobs:
  checks:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install project
        run: |
          python -m pip install --upgrade pip
          pip install -e ".[dev]"

      - name: Lint
        run: ruff check .

      - name: Tests
        run: pytest

      - name: Type check
        run: mypy

      - name: Diff risk gate
        run: |
          git fetch origin "${{ github.base_ref }}"
          BASE="origin/${{ github.base_ref }}"
          diff-ai score --repo . --base "$BASE" --head HEAD --format json --fail-above 45
```

## Development

Run local quality checks:

```bash
ruff check .
pytest
mypy
```

Install in editable mode:

```bash
pip install -e ".[dev]"
```
