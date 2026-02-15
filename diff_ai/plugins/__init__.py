"""Plugin system for optional, budget-aware scoring augmentations."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import PurePosixPath

from diff_ai.diff_parser import FileDiff
from diff_ai.rules.base import Finding, Rule

MODE_MAX_PLUGIN_COST_SECONDS = {
    "fast": 2.5,
    "standard": 8.0,
    "deep": 60.0,
}


@dataclass(frozen=True, slots=True)
class PluginInfo:
    """Public plugin metadata."""

    plugin_id: str
    rule_id: str
    description: str
    category: str
    packs: tuple[str, ...]
    estimated_cost_seconds: float
    modes: tuple[str, ...]
    priority: int


@dataclass(slots=True)
class PluginRun:
    """Per-plugin scheduling/execution record."""

    plugin_id: str
    rule_id: str
    category: str
    packs: list[str]
    estimated_cost_seconds: float
    status: str
    reason: str
    elapsed_ms: int | None = None
    findings: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "plugin_id": self.plugin_id,
            "rule_id": self.rule_id,
            "category": self.category,
            "packs": list(self.packs),
            "estimated_cost_seconds": self.estimated_cost_seconds,
            "status": self.status,
            "reason": self.reason,
            "elapsed_ms": self.elapsed_ms,
            "findings": self.findings,
        }


class PluginBase:
    """Base class for rule-compatible plugins."""

    plugin_id: str = ""
    rule_id: str = ""
    category: str = "quality"
    packs: tuple[str, ...] = ("quality",)
    estimated_cost_seconds: float = 1.0
    modes: tuple[str, ...] = ("fast", "standard", "deep")
    priority: int = 50

    def evaluate(self, files: list[FileDiff]) -> list[Finding]:
        """Evaluate diff files and emit risk findings."""
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class _PluginSpec:
    factory: type[PluginBase]

    def info(self) -> PluginInfo:
        plugin = self.factory()
        return PluginInfo(
            plugin_id=plugin.plugin_id,
            rule_id=plugin.rule_id,
            description=(plugin.__class__.__doc__ or "").strip(),
            category=plugin.category,
            packs=plugin.packs,
            estimated_cost_seconds=plugin.estimated_cost_seconds,
            modes=plugin.modes,
            priority=plugin.priority,
        )


class _ScheduledPluginRule:
    """Wrap a plugin to capture runtime metadata without changing rule semantics."""

    def __init__(self, plugin: PluginBase, run: PluginRun) -> None:
        self._plugin = plugin
        self._run = run
        self.rule_id = run.rule_id

    def evaluate(self, files: list[FileDiff]) -> list[Finding]:
        start = time.perf_counter()
        try:
            findings = self._plugin.evaluate(files)
            self._run.status = "ran"
            self._run.reason = "completed"
            self._run.findings = len(findings)
            return findings
        except Exception as exc:  # pragma: no cover - defensive guardrail
            self._run.status = "failed"
            self._run.reason = f"{exc.__class__.__name__}: {exc}"
            self._run.findings = 0
            return []
        finally:
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            self._run.elapsed_ms = elapsed_ms


def list_plugin_info(*, include_builtin: bool = True) -> list[PluginInfo]:
    """List known plugins."""
    specs = _plugin_specs(include_builtin=include_builtin)
    return [spec.info() for spec in specs]


def schedule_plugin_rules(
    *,
    include_builtin: bool,
    active_packs: set[str],
    mode: str,
    budget_seconds: int,
    enabled_plugin_ids: list[str] | None,
    disabled_plugin_ids: list[str] | None,
) -> tuple[list[Rule], list[PluginRun]]:
    """Select plugin rules based on packs, mode, and total budget."""
    resolved_mode = mode.lower()
    if resolved_mode not in MODE_MAX_PLUGIN_COST_SECONDS:
        choices = ", ".join(sorted(MODE_MAX_PLUGIN_COST_SECONDS))
        raise ValueError(f"Unknown objective mode '{mode}'. Expected one of: {choices}")
    if budget_seconds <= 0:
        raise ValueError("objective.budget_seconds must be > 0")

    infos = list_plugin_info(include_builtin=include_builtin)
    if not infos:
        return ([], [])

    info_by_id = {info.plugin_id: info for info in infos}
    requested = set(enabled_plugin_ids or []) | set(disabled_plugin_ids or [])
    unknown = sorted(plugin_id for plugin_id in requested if plugin_id not in info_by_id)
    if unknown:
        raise ValueError(f"Unknown plugin ids: {', '.join(unknown)}")

    disabled = set(disabled_plugin_ids or [])
    if enabled_plugin_ids:
        candidate_ids = [
            plugin_id for plugin_id in _dedupe(enabled_plugin_ids) if plugin_id not in disabled
        ]
    else:
        candidate_ids = [
            info.plugin_id for info in sorted(infos, key=lambda item: item.priority, reverse=True)
            if info.plugin_id not in disabled
        ]

    wrappers: list[Rule] = []
    runs: list[PluginRun] = []
    spent = 0.0
    max_single = MODE_MAX_PLUGIN_COST_SECONDS[resolved_mode]

    for plugin_id in candidate_ids:
        info = info_by_id[plugin_id]
        run = PluginRun(
            plugin_id=info.plugin_id,
            rule_id=info.rule_id,
            category=info.category,
            packs=list(info.packs),
            estimated_cost_seconds=info.estimated_cost_seconds,
            status="skipped",
            reason="unscheduled",
        )

        if not active_packs.intersection(info.packs):
            run.reason = "pack-inactive"
            runs.append(run)
            continue
        if resolved_mode not in info.modes:
            run.reason = "mode-incompatible"
            runs.append(run)
            continue
        if info.estimated_cost_seconds > max_single:
            run.reason = "mode-cost-cap"
            runs.append(run)
            continue
        if spent + info.estimated_cost_seconds > float(budget_seconds):
            run.reason = "budget-exceeded"
            runs.append(run)
            continue

        spent += info.estimated_cost_seconds
        run.status = "scheduled"
        run.reason = "selected"
        plugin = _build_plugin_by_id(plugin_id, include_builtin=include_builtin)
        wrappers.append(_ScheduledPluginRule(plugin, run))
        runs.append(run)

    return (wrappers, runs)


class DeferredWorkMarkersPlugin(PluginBase):
    """Finds TODO/FIXME/NotImplemented markers in newly added implementation code."""

    plugin_id = "deferred_work_markers"
    rule_id = "plugin_deferred_work_markers"
    category = "logic"
    packs = ("logic",)
    estimated_cost_seconds = 1.0
    modes = ("fast", "standard", "deep")
    priority = 100

    _TOKENS = ("todo", "fixme", "xxx", "notimplemented", "not implemented")

    def evaluate(self, files: list[FileDiff]) -> list[Finding]:
        findings: list[Finding] = []
        for file_diff in files:
            path = file_diff.path
            if _is_test_or_doc_path(path):
                continue

            markers: set[str] = set()
            for hunk in file_diff.hunks:
                for line in hunk.lines:
                    if line.kind != "add":
                        continue
                    lowered = line.content.lower()
                    if any(token in lowered for token in self._TOKENS):
                        markers.add(_clip_line(line.content))

            if not markers:
                continue

            findings.append(
                Finding(
                    rule_id=self.rule_id,
                    points=min(10, 4 + len(markers)),
                    message="Deferred implementation marker added.",
                    evidence=(
                        f"{path} adds TODO/FIXME-style markers: "
                        f"{', '.join(sorted(markers)[:3])}."
                    ),
                    scope=f"file:{path}",
                    suggestion=(
                        "Complete the implementation or gate unfinished paths behind a safe flag "
                        "with tests for current behavior."
                    ),
                )
            )
        return findings


class CrossLayerTouchpointsPlugin(PluginBase):
    """Detects backend/schema changes without corresponding consumer or contract-test updates."""

    plugin_id = "cross_layer_touchpoints"
    rule_id = "plugin_cross_layer_touchpoints"
    category = "integration"
    packs = ("integration",)
    estimated_cost_seconds = 4.0
    modes = ("standard", "deep")
    priority = 90

    _BACKEND_MARKERS = (
        "/api/",
        "/route",
        "/controller",
        "/service",
        "/handler",
        "/server",
        "/resolver",
    )
    _CLIENT_MARKERS = (
        "/frontend/",
        "/web/",
        "/ui/",
        "/mobile/",
        "/ios/",
        "/android/",
        "/client/",
    )
    _SCHEMA_MARKERS = ("openapi", "swagger", "graphql", "/schema", ".proto", ".avsc")
    _CONTRACT_TEST_MARKERS = ("contract", "integration", "e2e", "api")

    def evaluate(self, files: list[FileDiff]) -> list[Finding]:
        changed_paths = [file_diff.path for file_diff in files]
        lowered_paths = [path.lower() for path in changed_paths]

        backend_paths = [
            path
            for path in lowered_paths
            if not _is_test_or_doc_path(path) and _contains_any(path, self._BACKEND_MARKERS)
        ]
        client_changed = any(_contains_any(path, self._CLIENT_MARKERS) for path in lowered_paths)
        contract_tests_changed = any(
            _is_test_path(path) and _contains_any(path, self._CONTRACT_TEST_MARKERS)
            for path in lowered_paths
        )
        schema_changed = any(_contains_any(path, self._SCHEMA_MARKERS) for path in lowered_paths)

        findings: list[Finding] = []
        if backend_paths and not client_changed and not contract_tests_changed:
            findings.append(
                Finding(
                    rule_id=self.rule_id,
                    points=9,
                    message="Backend touchpoints changed without consumer-side evidence.",
                    evidence=(
                        f"{len(backend_paths)} backend path(s) changed, "
                        "but no client/contract-test changes detected."
                    ),
                    scope="overall",
                    suggestion=(
                        "Update client integration points or add contract/integration tests "
                        "that prove compatibility."
                    ),
                )
            )

        if schema_changed and not client_changed and not contract_tests_changed:
            findings.append(
                Finding(
                    rule_id=self.rule_id,
                    points=10,
                    message="Schema/contract surface changed without downstream verification.",
                    evidence="Schema-like paths changed with no client or contract-test updates.",
                    scope="overall",
                    suggestion=(
                        "Add compatibility tests and update downstream consumers "
                        "for schema-level changes."
                    ),
                )
            )
        return findings


class NetworkExposureProbePlugin(PluginBase):
    """Flags added network-exposure patterns (security pack, optional by objective)."""

    plugin_id = "network_exposure_probe"
    rule_id = "plugin_network_exposure_probe"
    category = "security"
    packs = ("security",)
    estimated_cost_seconds = 3.0
    modes = ("standard", "deep")
    priority = 80

    _TOKENS = (
        "0.0.0.0",
        "allow_origins=[\"*\"]",
        "access-control-allow-origin: *",
        "verify=false",
        "insecure_skip_verify",
        "--allow-all",
    )

    def evaluate(self, files: list[FileDiff]) -> list[Finding]:
        findings: list[Finding] = []
        for file_diff in files:
            hits: list[str] = []
            for hunk in file_diff.hunks:
                for line in hunk.lines:
                    if line.kind != "add":
                        continue
                    lowered = line.content.lower()
                    if any(token in lowered for token in self._TOKENS):
                        hits.append(_clip_line(line.content))
            if not hits:
                continue
            findings.append(
                Finding(
                    rule_id=self.rule_id,
                    points=min(10, 6 + len(hits)),
                    message="Potential network-exposure pattern introduced.",
                    evidence=f"{file_diff.path}: {', '.join(hits[:3])}",
                    scope=f"file:{file_diff.path}",
                    suggestion=(
                        "Constrain exposure defaults and document why broad access "
                        "is safe for this feature change."
                    ),
                )
            )
        return findings


def _plugin_specs(*, include_builtin: bool) -> list[_PluginSpec]:
    specs: list[_PluginSpec] = []
    if include_builtin:
        specs.extend(
            [
                _PluginSpec(DeferredWorkMarkersPlugin),
                _PluginSpec(CrossLayerTouchpointsPlugin),
                _PluginSpec(NetworkExposureProbePlugin),
            ]
        )
    return specs


def _build_plugin_by_id(plugin_id: str, *, include_builtin: bool) -> PluginBase:
    for spec in _plugin_specs(include_builtin=include_builtin):
        info = spec.info()
        if info.plugin_id == plugin_id:
            return spec.factory()
    raise ValueError(f"Unknown plugin id: {plugin_id}")


def _is_test_or_doc_path(path: str) -> bool:
    lowered = path.lower()
    return _is_test_path(lowered) or _is_doc_path(lowered)


def _is_doc_path(path: str) -> bool:
    lowered = path.lower()
    suffix = PurePosixPath(lowered).suffix
    return (
        lowered.startswith("docs/")
        or "/docs/" in lowered
        or suffix in {".md", ".rst", ".adoc", ".txt"}
    )


def _is_test_path(path: str) -> bool:
    lowered = path.lower()
    name = PurePosixPath(lowered).name
    return (
        lowered.startswith("tests/")
        or "/tests/" in lowered
        or name.startswith("test_")
        or name.endswith("_test.py")
    )


def _contains_any(value: str, needles: tuple[str, ...]) -> bool:
    return any(needle in value for needle in needles)


def _clip_line(content: str, max_len: int = 80) -> str:
    stripped = content.strip()
    if len(stripped) <= max_len:
        return stripped
    return stripped[: max_len - 3] + "..."


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        output.append(item)
    return output
