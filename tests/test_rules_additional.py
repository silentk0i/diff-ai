"""Additional rule tests for Step 4 expansion."""

from __future__ import annotations

from diff_ai.config import (
    ProfileConfig,
    ProfilePathSignal,
    ProfilePatternSignal,
    ProfileTestsConfig,
)
from diff_ai.diff_parser import parse_unified_diff
from diff_ai.rules import build_rules, default_rules
from diff_ai.rules.api_surface import ApiSurfaceRule
from diff_ai.rules.config_changes import ConfigChangesRule
from diff_ai.rules.dangerous_patterns import DangerousPatternsRule
from diff_ai.rules.dependency_changes import DependencyChangesRule
from diff_ai.rules.destructive_changes import DestructiveChangesRule
from diff_ai.rules.docs_only import DocsOnlyRule
from diff_ai.rules.error_handling import ErrorHandlingRule
from diff_ai.rules.profile_signals import ProfileSignalsRule


def test_default_rules_use_feature_oneshot_pack_defaults() -> None:
    rules = default_rules()
    rule_ids = {rule.rule_id for rule in rules}
    assert len(rules) >= 8
    assert len(rule_ids) == len(rules)
    assert "critical_paths" not in rule_ids
    assert "dangerous_patterns" not in rule_ids


def test_security_strict_objective_includes_security_pack_rules() -> None:
    rules = build_rules(objective_name="security_strict")
    rule_ids = {rule.rule_id for rule in rules}
    assert "critical_paths" in rule_ids
    assert "dangerous_patterns" in rule_ids


def test_dependency_changes_rule_flags_manifests_and_lockfiles() -> None:
    diff_text = "\n".join(
        [
            _build_replace_diff("pyproject.toml", ['version = "0.1.0"'], ['version = "0.2.0"']),
            _build_replace_diff("requirements.txt", ["typer==0.22.0"], ["typer==0.23.1"]),
            _build_replace_diff("poetry.lock", ["package-a==1.0.0"], ["package-a==1.1.0"]),
        ]
    )
    findings = DependencyChangesRule().evaluate(parse_unified_diff(diff_text))
    scopes = {finding.scope for finding in findings}
    assert "file:pyproject.toml" in scopes
    assert "file:requirements.txt" in scopes
    assert "file:poetry.lock" in scopes
    assert any(finding.scope == "overall" for finding in findings)


def test_config_changes_rule_flags_config_and_env_updates() -> None:
    diff_text = "\n".join(
        [
            _build_replace_diff("config/settings.yml", ["debug: false"], ["debug=true"]),
            _build_replace_diff(".env", ["API_HOST=127.0.0.1"], ["API_HOST=0.0.0.0"]),
        ]
    )
    findings = ConfigChangesRule().evaluate(parse_unified_diff(diff_text))
    assert len(findings) == 2
    assert all(finding.points >= 7 for finding in findings)
    assert {finding.scope for finding in findings} == {
        "file:config/settings.yml",
        "file:.env",
    }


def test_dangerous_patterns_rule_flags_eval_and_shell_usage() -> None:
    diff_text = _build_replace_diff(
        "src/runner.py",
        ["def run(cmd):", "    return cmd"],
        [
            "def run(cmd):",
            "    eval(cmd)",
            "    subprocess.run(cmd, shell=True)",
            "    return cmd",
        ],
    )
    findings = DangerousPatternsRule().evaluate(parse_unified_diff(diff_text))
    assert len(findings) >= 2
    assert any("eval" in finding.message.lower() for finding in findings)
    assert any("shell" in finding.message.lower() for finding in findings)


def test_error_handling_rule_flags_bare_except_and_removed_raise() -> None:
    diff_text = _build_replace_diff(
        "src/worker.py",
        [
            "try:",
            "    run()",
            "except ValueError:",
            "    raise ValueError('bad')",
        ],
        [
            "try:",
            "    run()",
            "except:",
            "    pass",
        ],
    )
    findings = ErrorHandlingRule().evaluate(parse_unified_diff(diff_text))
    assert len(findings) == 2
    assert any("Bare except" in finding.message for finding in findings)
    assert any("removed" in finding.message.lower() for finding in findings)


def test_api_surface_rule_flags_signature_churn_in_api_paths() -> None:
    diff_text = _build_replace_diff(
        "src/api/routes.py",
        ["def get_user():", "    return {}"],
        [
            "def get_user(user_id: str):",
            "    return {}",
            "def create_user(payload):",
            "    return payload",
            "class UsersController:",
            "    pass",
        ],
    )
    findings = ApiSurfaceRule().evaluate(parse_unified_diff(diff_text))
    assert len(findings) == 1
    assert findings[0].scope == "file:src/api/routes.py"
    assert findings[0].points >= 8


def test_docs_only_rule_reduces_risk_for_docs_diff() -> None:
    diff_text = "\n".join(
        [
            _build_replace_diff("docs/guide.md", ["old"], ["new"]),
            _build_replace_diff("README.md", ["line1"], ["line2"]),
        ]
    )
    findings = DocsOnlyRule().evaluate(parse_unified_diff(diff_text))
    assert len(findings) == 1
    assert findings[0].scope == "overall"
    assert findings[0].points < 0


def test_destructive_changes_rule_flags_deleted_file_and_deletion_heavy_diff() -> None:
    diff_text = "\n".join(
        [
            _build_delete_diff("src/legacy.py", [f"line-{idx}" for idx in range(1, 41)]),
            _build_replace_diff(
                "src/keep.py",
                [f"old-{idx}" for idx in range(1, 31)],
                [f"new-{idx}" for idx in range(1, 6)],
            ),
        ]
    )
    findings = DestructiveChangesRule().evaluate(parse_unified_diff(diff_text))
    assert any(finding.scope == "file:src/legacy.py" for finding in findings)
    assert any(finding.scope == "overall" for finding in findings)


def test_profile_signals_rule_flags_paths_patterns_and_missing_tests() -> None:
    diff_text = _build_replace_diff(
        "src/payments/charge.py",
        ["def run(cmd):", "    return cmd"],
        ["def run(cmd):", "    eval(cmd)", "    return cmd"],
    )
    files = parse_unified_diff(diff_text)
    rule = ProfileSignalsRule(
        ProfileConfig(
            critical=[
                ProfilePathSignal(
                    glob="src/payments/**",
                    points=20,
                    reason="money path",
                )
            ],
            unsafe_added=[
                ProfilePatternSignal(
                    regex=r"\beval\(",
                    points=12,
                    reason="eval usage",
                )
            ],
            tests=ProfileTestsConfig(required_for=["src/payments/**"], test_globs=["tests/**"]),
        )
    )
    findings = rule.evaluate(files)
    rule_ids = {finding.rule_id for finding in findings}
    assert rule_ids == {"profile_signals"}
    assert any("critical path matched" in finding.message.lower() for finding in findings)
    assert any("unsafe pattern" in finding.message.lower() for finding in findings)
    assert any("requires tests" in finding.message.lower() for finding in findings)


def _build_replace_diff(path: str, old_lines: list[str], new_lines: list[str]) -> str:
    old_count = len(old_lines)
    new_count = len(new_lines)
    header = [
        f"diff --git a/{path} b/{path}",
        "index 1111111..2222222 100644",
        f"--- a/{path}",
        f"+++ b/{path}",
        f"@@ -1,{old_count} +1,{new_count} @@",
    ]
    body = [f"-{line}" for line in old_lines] + [f"+{line}" for line in new_lines]
    return "\n".join(header + body)


def _build_delete_diff(path: str, old_lines: list[str]) -> str:
    old_count = len(old_lines)
    header = [
        f"diff --git a/{path} b/{path}",
        "deleted file mode 100644",
        "index 1111111..0000000",
        f"--- a/{path}",
        "+++ /dev/null",
        f"@@ -1,{old_count} +0,0 @@",
    ]
    body = [f"-{line}" for line in old_lines]
    return "\n".join(header + body)
