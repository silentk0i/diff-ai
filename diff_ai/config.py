"""Configuration loading for diff-ai."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CONFIG_FILENAMES = (".diff-ai.toml", "diff-ai.toml")
PYPROJECT_FILENAME = "pyproject.toml"
PYPROJECT_TOOL_KEYS = ("diff_ai", "diff-ai")


@dataclass(slots=True)
class LlmConfig:
    """LLM-handoff defaults."""

    style: str = "thorough"
    persona: str = "reviewer"
    target_score: int = 30
    include_diff: str = "full"
    include_snippets: str = "none"
    max_bytes: int = 200000
    redact_secrets: bool = False
    rubric: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "style": self.style,
            "persona": self.persona,
            "target_score": self.target_score,
            "include_diff": self.include_diff,
            "include_snippets": self.include_snippets,
            "max_bytes": self.max_bytes,
            "redact_secrets": self.redact_secrets,
            "rubric": list(self.rubric),
        }


@dataclass(slots=True)
class ProfilePathSignal:
    """Path-based profile signal."""

    glob: str
    points: int
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"glob": self.glob, "points": self.points, "reason": self.reason}


@dataclass(slots=True)
class ProfilePatternSignal:
    """Pattern-based profile signal."""

    regex: str
    points: int
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"regex": self.regex, "points": self.points, "reason": self.reason}


@dataclass(slots=True)
class ProfileTestsConfig:
    """Profile-specific test expectations."""

    required_for: list[str] = field(default_factory=list)
    test_globs: list[str] = field(
        default_factory=lambda: ["tests/**", "**/test_*.py", "**/*_test.py"]
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "required_for": list(self.required_for),
            "test_globs": list(self.test_globs),
        }


@dataclass(slots=True)
class ProfileConfig:
    """Repo-specific risk profile signals."""

    critical: list[ProfilePathSignal] = field(default_factory=list)
    sensitive: list[ProfilePathSignal] = field(default_factory=list)
    unsafe_added: list[ProfilePatternSignal] = field(default_factory=list)
    tests: ProfileTestsConfig = field(default_factory=ProfileTestsConfig)

    def to_dict(self) -> dict[str, Any]:
        return {
            "paths": {
                "critical": [item.to_dict() for item in self.critical],
                "sensitive": [item.to_dict() for item in self.sensitive],
            },
            "patterns": {
                "unsafe_added": [item.to_dict() for item in self.unsafe_added],
            },
            "tests": self.tests.to_dict(),
        }

    def has_signals(self) -> bool:
        return bool(self.critical or self.sensitive or self.unsafe_added or self.tests.required_for)


@dataclass(slots=True)
class ObjectiveConfig:
    """Objective and time-budget controls for rule selection/scoring."""

    name: str = "feature_oneshot"
    mode: str = "standard"
    budget_seconds: int = 15
    enable_packs: list[str] = field(default_factory=list)
    disable_packs: list[str] = field(default_factory=list)
    category_weights: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "mode": self.mode,
            "budget_seconds": self.budget_seconds,
            "packs": {
                "enable": list(self.enable_packs),
                "disable": list(self.disable_packs),
            },
            "weights": dict(self.category_weights),
        }


@dataclass(slots=True)
class PluginsConfig:
    """Plugin execution and selection controls."""

    include_builtin: bool = True
    enable: list[str] = field(default_factory=list)
    disable: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "include_builtin": self.include_builtin,
            "enable": list(self.enable),
            "disable": list(self.disable),
        }


@dataclass(slots=True)
class AppConfig:
    """Runtime configuration values resolved from project files."""

    format: str = "human"
    fail_above: int | None = None
    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    rule_enable: list[str] | None = None
    rule_disable: list[str] = field(default_factory=list)
    llm: LlmConfig = field(default_factory=LlmConfig)
    profile: ProfileConfig = field(default_factory=ProfileConfig)
    objective: ObjectiveConfig = field(default_factory=ObjectiveConfig)
    plugins: PluginsConfig = field(default_factory=PluginsConfig)
    source: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": self.format,
            "fail_above": self.fail_above,
            "include": list(self.include),
            "exclude": list(self.exclude),
            "rules": {
                "enable": list(self.rule_enable) if self.rule_enable is not None else None,
                "disable": list(self.rule_disable),
            },
            "objective": self.objective.to_dict(),
            "plugins": self.plugins.to_dict(),
            "llm": self.llm.to_dict(),
            "profile": self.profile.to_dict(),
            "source": self.source,
        }


def load_app_config(repo: Path, config_path: Path | None = None) -> AppConfig:
    """Load config from explicit path or repository-local files with precedence."""
    repo = repo.resolve()
    if config_path is not None:
        resolved = config_path if config_path.is_absolute() else (repo / config_path)
        if not resolved.exists():
            raise ValueError(f"Config file does not exist: {resolved}")
        mapping = _extract_config_mapping(_load_toml(resolved), source_path=resolved)
        return _from_mapping(mapping, source=str(resolved))

    for filename in CONFIG_FILENAMES:
        resolved = repo / filename
        if resolved.exists():
            mapping = _extract_config_mapping(_load_toml(resolved), source_path=resolved)
            return _from_mapping(mapping, source=str(resolved))

    pyproject_path = repo / PYPROJECT_FILENAME
    if pyproject_path.exists():
        mapping = _extract_config_mapping(_load_toml(pyproject_path), source_path=pyproject_path)
        if mapping:
            return _from_mapping(mapping, source=str(pyproject_path))

    return AppConfig()


def default_config_template() -> str:
    """Return a starter config template users/AI can customize."""
    return "\n".join(
        [
            'format = "json"',
            "fail_above = 40",
            'include = ["src/**"]',
            'exclude = ["docs/**"]',
            "",
            "[objective]",
            'name = "feature_oneshot"',
            'mode = "standard"',
            "budget_seconds = 15",
            "",
            "[objective.packs]",
            '# enable = ["security"]',
            "disable = []",
            "",
            "[objective.weights]",
            "# logic = 1.30",
            "# test_adequacy = 1.35",
            "# integration = 1.15",
            "# security = 0.60",
            "",
            "[plugins]",
            "include_builtin = true",
            "enable = []",
            "disable = []",
            "",
            "[rules]",
            "enable = [",
            '  "magnitude",',
            '  "critical_paths",',
            '  "test_signals",',
            '  "dependency_changes",',
            '  "config_changes",',
            '  "dangerous_patterns",',
            '  "error_handling",',
            '  "api_surface",',
            '  "docs_only",',
            '  "destructive_changes",',
            '  "profile_signals",',
            "]",
            'disable = ["docs_only"]',
            "",
            "[llm]",
            'style = "thorough"',
            'persona = "reviewer"',
            "target_score = 30",
            'include_diff = "top-hunks"',
            'include_snippets = "risky-only"',
            "max_bytes = 120000",
            "redact_secrets = true",
            'rubric = ["keep patches minimal", "add regression tests"]',
            "",
            "[profile.paths]",
            "critical = [",
            '  { glob = "src/payments/**", points = 20, reason = "money movement path" },',
            '  { glob = "src/auth/**", points = 16, reason = "authentication boundary" },',
            "]",
            "sensitive = [",
            '  { glob = "infra/**", points = 10, reason = "deployment surface" },',
            "]",
            "",
            "[profile.patterns]",
            "unsafe_added = [",
            '  { regex = "\\\\beval\\\\(", points = 12, reason = "dynamic eval introduced" },',
            (
                '  { regex = "shell\\\\s*=\\\\s*True", points = 10, '
                'reason = "shell execution enabled" },'
            ),
            "]",
            "",
            "[profile.tests]",
            'required_for = ["src/**", "infra/**"]',
            'test_globs = ["tests/**", "**/*_test.py"]',
            "",
        ]
    )


def _load_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as file_obj:
            loaded = tomllib.load(file_obj)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"Invalid TOML in {path}: {exc}") from exc
    if not isinstance(loaded, dict):
        return {}
    return loaded


def _extract_config_mapping(loaded: dict[str, Any], *, source_path: Path) -> dict[str, Any]:
    if source_path.name == PYPROJECT_FILENAME:
        section = _find_pyproject_tool_section(loaded)
        return section if section is not None else {}

    tool_section = _find_pyproject_tool_section(loaded)
    if tool_section is not None:
        return tool_section
    return loaded


def _find_pyproject_tool_section(loaded: dict[str, Any]) -> dict[str, Any] | None:
    tool = loaded.get("tool")
    if not isinstance(tool, dict):
        return None
    for key in PYPROJECT_TOOL_KEYS:
        section = tool.get(key)
        if isinstance(section, dict):
            return section
    return None


def _from_mapping(mapping: dict[str, Any], *, source: str) -> AppConfig:
    rules_mapping = _as_table(mapping.get("rules"), "rules")
    objective_mapping = _as_table(mapping.get("objective"), "objective")
    plugins_mapping = _as_table(mapping.get("plugins"), "plugins")
    llm_mapping = _as_table(mapping.get("llm"), "llm")
    profile_mapping = _as_table(mapping.get("profile"), "profile")

    raw_format = mapping.get("format", "human")
    format_value = str(raw_format).lower()
    if format_value not in {"human", "json"}:
        format_value = "human"

    raw_fail = mapping.get("fail_above")
    if raw_fail is None:
        fail_value: int | None = None
    elif isinstance(raw_fail, int):
        fail_value = raw_fail
    else:
        raise ValueError("fail_above must be an integer")

    return AppConfig(
        format=format_value,
        fail_above=fail_value,
        include=_as_str_list(mapping.get("include")),
        exclude=_as_str_list(mapping.get("exclude")),
        rule_enable=_as_str_list_or_none(rules_mapping.get("enable")),
        rule_disable=_as_str_list(rules_mapping.get("disable")),
        objective=_parse_objective_config(objective_mapping),
        plugins=_parse_plugins_config(plugins_mapping),
        llm=_parse_llm_config(llm_mapping),
        profile=_parse_profile_config(profile_mapping),
        source=source,
    )


def _parse_objective_config(value: dict[str, Any]) -> ObjectiveConfig:
    packs = _as_table(value.get("packs"), "objective.packs")
    weights = _as_table(value.get("weights"), "objective.weights")
    budget = _as_int(value.get("budget_seconds", 15), "objective.budget_seconds")
    if budget <= 0:
        raise ValueError("objective.budget_seconds must be > 0")
    return ObjectiveConfig(
        name=_as_choice(
            value.get("name", "feature_oneshot"),
            {"feature_oneshot", "security_strict"},
            "objective.name",
        ),
        mode=_as_choice(
            value.get("mode", "standard"),
            {"fast", "standard", "deep"},
            "objective.mode",
        ),
        budget_seconds=budget,
        enable_packs=_as_str_list(packs.get("enable")),
        disable_packs=_as_str_list(packs.get("disable")),
        category_weights=_as_float_mapping(weights, "objective.weights"),
    )


def _parse_plugins_config(value: dict[str, Any]) -> PluginsConfig:
    return PluginsConfig(
        include_builtin=_as_bool(value.get("include_builtin", True), "plugins.include_builtin"),
        enable=_as_str_list(value.get("enable")),
        disable=_as_str_list(value.get("disable")),
    )


def _parse_profile_config(value: dict[str, Any]) -> ProfileConfig:
    paths = _as_table(value.get("paths"), "profile.paths")
    patterns = _as_table(value.get("patterns"), "profile.patterns")
    tests = _as_table(value.get("tests"), "profile.tests")
    return ProfileConfig(
        critical=_parse_profile_path_signal_list(paths.get("critical"), "profile.paths.critical"),
        sensitive=_parse_profile_path_signal_list(
            paths.get("sensitive"),
            "profile.paths.sensitive",
        ),
        unsafe_added=_parse_profile_pattern_signal_list(
            patterns.get("unsafe_added"), "profile.patterns.unsafe_added"
        ),
        tests=ProfileTestsConfig(
            required_for=_as_str_list(tests.get("required_for")),
            test_globs=_as_str_list(tests.get("test_globs"))
            or ["tests/**", "**/test_*.py", "**/*_test.py"],
        ),
    )


def _parse_profile_path_signal_list(value: Any, field_name: str) -> list[ProfilePathSignal]:
    items = _as_table_list(value, field_name)
    parsed: list[ProfilePathSignal] = []
    for item in items:
        parsed.append(
            ProfilePathSignal(
                glob=_as_str(item.get("glob"), f"{field_name}.glob"),
                points=_as_int(item.get("points"), f"{field_name}.points"),
                reason=_as_str(item.get("reason"), f"{field_name}.reason"),
            )
        )
    return parsed


def _parse_profile_pattern_signal_list(value: Any, field_name: str) -> list[ProfilePatternSignal]:
    items = _as_table_list(value, field_name)
    parsed: list[ProfilePatternSignal] = []
    for item in items:
        parsed.append(
            ProfilePatternSignal(
                regex=_as_str(item.get("regex"), f"{field_name}.regex"),
                points=_as_int(item.get("points"), f"{field_name}.points"),
                reason=_as_str(item.get("reason"), f"{field_name}.reason"),
            )
        )
    return parsed


def _parse_llm_config(value: dict[str, Any]) -> LlmConfig:
    style = _as_choice(
        value.get("style", "thorough"),
        {"concise", "thorough", "paranoid"},
        "llm.style",
    )
    persona = _as_choice(
        value.get("persona", "reviewer"),
        {"reviewer", "security", "sre", "maintainer"},
        "llm.persona",
    )
    include_diff = _as_choice(
        value.get("include_diff", "full"),
        {"full", "risky-only", "top-hunks"},
        "llm.include_diff",
    )
    include_snippets = _as_choice(
        value.get("include_snippets", "none"),
        {"none", "minimal", "risky-only"},
        "llm.include_snippets",
    )
    target_score = _as_int(value.get("target_score", 30), "llm.target_score")
    max_bytes = _as_int(value.get("max_bytes", 200000), "llm.max_bytes")
    redact_secrets = _as_bool(value.get("redact_secrets", False), "llm.redact_secrets")

    return LlmConfig(
        style=style,
        persona=persona,
        target_score=target_score,
        include_diff=include_diff,
        include_snippets=include_snippets,
        max_bytes=max_bytes,
        redact_secrets=redact_secrets,
        rubric=_as_str_list(value.get("rubric")),
    )


def _as_table(value: Any, field_name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be a table/object")
    return value


def _as_table_list(value: Any, field_name: str) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list of tables")
    output: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError(f"{field_name} must be a list of tables")
        output.append(item)
    return output


def _as_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("Expected a list of strings")
    items: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError("Expected a list of strings")
        items.append(item)
    return items


def _as_str_list_or_none(value: Any) -> list[str] | None:
    if value is None:
        return None
    return _as_str_list(value)


def _as_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    return value


def _as_choice(raw: Any, allowed: set[str], field_name: str) -> str:
    value = str(raw).lower()
    if value not in allowed:
        choices = ", ".join(sorted(allowed))
        raise ValueError(f"{field_name} must be one of: {choices}")
    return value


def _as_int(raw: Any, field_name: str) -> int:
    if not isinstance(raw, int):
        raise ValueError(f"{field_name} must be an integer")
    return raw


def _as_bool(raw: Any, field_name: str) -> bool:
    if not isinstance(raw, bool):
        raise ValueError(f"{field_name} must be a boolean")
    return raw


def _as_float_mapping(value: Any, field_name: str) -> dict[str, float]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be a table/object")

    parsed: dict[str, float] = {}
    for key, raw in value.items():
        if not isinstance(key, str):
            raise ValueError(f"{field_name} keys must be strings")
        parsed[key] = _as_float(raw, f"{field_name}.{key}")
    return parsed


def _as_float(raw: Any, field_name: str) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError(f"{field_name} must be a number")
    return float(raw)
