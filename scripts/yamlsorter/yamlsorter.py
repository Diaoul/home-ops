#!/usr/bin/env python3
"""Reorder keys in Flux manifests to match per-type templates.

Key order is not semantic to Kubernetes, but a stable order makes diffs readable
and reviews mechanical. The desired order is declared by example: each file in the
config directory is a manifest skeleton whose *keys* define the order for its type.
Values there are ignored.

Keys absent from a template keep their relative order and sort after the templated
ones, so a template never has to be exhaustive.
"""

from __future__ import annotations

import argparse
import io
import logging
import os
import shutil
import sys
import tempfile
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Final, final

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

type YAMLValue = str | int | float | bool | list["YAMLValue"] | dict[str, "YAMLValue"] | None

GENERIC: Final = "generic"
WILDCARD: Final = "*"
ROOT_SECTION: Final = "root"
PATH_SEP: Final = "."
# Templates are skeletons, not manifests: the suffix keeps repo-wide Flux scanners
# (Konflate, flux-local) from rendering the placeholder values as real resources.
TEMPLATE_SUFFIX: Final = ".yaml.tpl"

log = logging.getLogger("yamlsorter")


class Outcome(Enum):
    """What happened to one file."""

    CHANGED = "changed"
    UNCHANGED = "unchanged"
    SKIPPED = "skipped"
    FAILED = "failed"


@final
@dataclass(frozen=True, slots=True)
class Result:
    path: Path
    outcome: Outcome
    file_type: str = GENERIC
    error: str | None = None


@final
@dataclass(slots=True)
class Stats:
    total: int = 0
    changed: int = 0
    unchanged: int = 0
    skipped: int = 0
    failed: int = 0
    missing_keys: dict[str, set[str]] = field(default_factory=dict)

    def record(self, result: Result) -> None:
        self.total += 1
        match result.outcome:
            case Outcome.CHANGED:
                self.changed += 1
            case Outcome.UNCHANGED:
                self.unchanged += 1
            case Outcome.SKIPPED:
                self.skipped += 1
            case Outcome.FAILED:
                self.failed += 1


class YAMLSorterError(Exception):
    """Base class for errors this tool raises deliberately."""


class ConfigError(YAMLSorterError):
    """A template is missing or unusable."""


class ParseError(YAMLSorterError):
    """A manifest could not be parsed."""


def _yaml_reader() -> YAML:
    """Round-trip parser. Comments, anchors and quoting survive a load/dump cycle."""
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.map_indent = 2
    yaml.sequence_indent = 4
    yaml.sequence_dash_offset = 2
    yaml.width = 4096
    yaml.default_flow_style = None
    return yaml


def extract_key_order(template: dict[str, YAMLValue]) -> dict[str, list[str]]:
    """Flatten a template manifest into {dotted.section: [keys in order]}."""
    orders: dict[str, list[str]] = {}

    def walk(node: YAMLValue, path: list[str]) -> None:
        if not isinstance(node, dict):
            return

        orders[PATH_SEP.join(path) if path else ROOT_SECTION] = list(node.keys())

        for key, value in node.items():
            child = [*path, key]
            if isinstance(value, dict):
                walk(value, child)
            elif isinstance(value, list):
                # A list in a template describes the shape of its entries, not their
                # count: merge every entry's keys into one order for that section.
                entries = [item for item in value if isinstance(item, dict)]
                merged: list[str] = []
                for entry in entries:
                    merged.extend(k for k in entry if k not in merged)
                    walk(entry, child)
                if merged:
                    orders[PATH_SEP.join(child)] = merged

    walk(template, [])
    return orders


@final
class FileTypeDetector:
    """Names the template a document should be sorted against."""

    KIND_TYPES: Final[dict[str, str]] = {"Component": "component"}

    @classmethod
    def detect(cls, data: dict[str, YAMLValue]) -> str:
        kind = data.get("kind")
        api_version = data.get("apiVersion")

        if kind == "HelmRelease":
            chart = cls._chart_name(data)
            return f"helmrelease-{chart}" if chart else "helmrelease"

        if kind == "Kustomization":
            is_flux = isinstance(api_version, str) and "kustomize.toolkit.fluxcd.io" in api_version
            return "flux-kustomization" if is_flux else "kustomization"

        if isinstance(kind, str) and kind in cls.KIND_TYPES:
            return cls.KIND_TYPES[kind]

        return GENERIC

    @staticmethod
    def _chart_name(data: dict[str, YAMLValue]) -> str | None:
        """Chart backing a HelmRelease, via chartRef (this repo) or inline chart."""
        spec = data.get("spec")
        if not isinstance(spec, dict):
            return None

        chart_ref = spec.get("chartRef")
        if isinstance(chart_ref, dict):
            name = chart_ref.get("name")
            if isinstance(name, str):
                return name.replace("-", "")

        chart = spec.get("chart")
        if isinstance(chart, dict):
            chart_spec = chart.get("spec")
            if isinstance(chart_spec, dict):
                name = chart_spec.get("chart")
                if isinstance(name, str):
                    return name.replace("-", "")

        return None


@final
class ConfigManager:
    """Loads templates, falling back from chart-specific to generic HelmRelease."""

    def __init__(self, config_dir: Path) -> None:
        self.config_dir = config_dir
        self._orders: dict[str, dict[str, list[str]]] = {}
        self._yaml = YAML(typ="safe")

    def validate(self) -> None:
        if not self.config_dir.is_dir():
            raise ConfigError(f"config directory not found: {self.config_dir}")
        if not any(self.config_dir.glob(f"*{TEMPLATE_SUFFIX}")):
            raise ConfigError(f"no templates in {self.config_dir}")

    def has_template(self, file_type: str) -> bool:
        return self._resolve(file_type) is not None

    def load(self, file_type: str) -> dict[str, list[str]]:
        if file_type in self._orders:
            return self._orders[file_type]

        path = self._resolve(file_type)
        if path is None:
            raise ConfigError(f"no template for type {file_type!r} in {self.config_dir}")

        try:
            with path.open(encoding="utf-8") as handle:
                template = self._yaml.load(handle)
        except Exception as exc:
            raise ConfigError(f"failed to read template {path}: {exc}") from exc

        if not isinstance(template, dict):
            raise ConfigError(f"template {path} is not a mapping")

        orders = extract_key_order(template)
        self._orders[file_type] = orders
        return orders

    def _resolve(self, file_type: str) -> Path | None:
        exact = self.config_dir / f"{file_type}{TEMPLATE_SUFFIX}"
        if exact.is_file():
            return exact
        if file_type.startswith("helmrelease-"):
            fallback = self.config_dir / f"helmrelease{TEMPLATE_SUFFIX}"
            if fallback.is_file():
                return fallback
        return None


@final
class KeySorter:
    """Applies a template's key order to a parsed document, in place."""

    def __init__(self, config: ConfigManager) -> None:
        self.config = config

    def sort_document(self, doc: CommentedMap, orders: dict[str, list[str]]) -> CommentedMap:
        return self._sort_node(doc, orders, [])

    def _sort_node(
        self, node: dict[str, YAMLValue], orders: dict[str, list[str]], path: list[str]
    ) -> CommentedMap:
        ordered = self._reorder(node, self._order_for(orders, path))

        for key, value in ordered.items():
            child = [*path, key]
            if isinstance(value, dict):
                ordered[key] = self._sort_node(value, orders, child)
            elif isinstance(value, list):
                for index, item in enumerate(value):
                    if isinstance(item, dict):
                        value[index] = self._sort_node(item, orders, child)

        return ordered

    @staticmethod
    def _reorder(node: dict[str, YAMLValue], order: list[str]) -> CommentedMap:
        """Rewrite a mapping in `order`, untemplated keys keeping their order after.

        A CommentedMap is refilled in place: comments, anchors and flow style hang off
        the container, so replacing it would drop them.
        """
        if not order:
            return node if isinstance(node, CommentedMap) else CommentedMap(node)

        templated = [key for key in order if key in node]
        if not templated:
            return node if isinstance(node, CommentedMap) else CommentedMap(node)

        rest = [key for key in node if key not in order]
        target = [*templated, *rest]

        if list(node.keys()) == target:
            return node if isinstance(node, CommentedMap) else CommentedMap(node)

        if not isinstance(node, CommentedMap):
            return CommentedMap((key, node[key]) for key in target)

        values = dict(node)
        node.clear()
        for key in target:
            node[key] = values[key]
        return node

    @staticmethod
    def _order_for(orders: dict[str, list[str]], path: list[str]) -> list[str]:
        if not path:
            return orders.get(ROOT_SECTION, [])

        section = PATH_SEP.join(path)
        if section in orders:
            return orders[section]

        # `controllers.*.containers.*` style templates: a literal path component is
        # matched exactly, `*` matches whatever the manifest called that level.
        for candidate, order in orders.items():
            parts = candidate.split(PATH_SEP)
            if len(parts) != len(path):
                continue
            if all(p == WILDCARD or p == actual for p, actual in zip(parts, path, strict=True)):
                return order

        return []


def _comment_anchors(text: str) -> list[tuple[str, str]]:
    """Pair every comment with the first line of content beneath it."""
    lines = [line.strip() for line in text.splitlines()]
    anchors: list[tuple[str, str]] = []

    for index, line in enumerate(lines):
        if not line.startswith("#"):
            continue
        following = next(
            (later for later in lines[index + 1 :] if later and not later.startswith("#")),
            "",
        )
        anchors.append((line, following))

    return anchors


def _detached_comments(original: str, rendered: str) -> str | None:
    """Name a comment the round-trip re-anchored, if any.

    ruamel cannot faithfully re-emit a comment that sits after a list dash
    (`- # note`): it reattaches to the preceding entry, so the note ends up
    describing the wrong item. Rewriting such a file would silently mislead.
    """
    before = _comment_anchors(original)
    after = _comment_anchors(rendered)

    if len(before) != len(after):
        return "a comment"

    for (comment, was), (_, now) in zip(before, after, strict=True):
        if was != now:
            return repr(comment)

    return None


@final
class FileProcessor:
    """Parses, sorts and rewrites one file."""

    def __init__(self, sorter: KeySorter, config: ConfigManager, dry_run: bool) -> None:
        self.sorter = sorter
        self.config = config
        self.dry_run = dry_run
        self._yaml = _yaml_reader()

    def process(self, path: Path) -> Result:
        try:
            original = path.read_text(encoding="utf-8")
        except OSError as exc:
            return Result(path, Outcome.FAILED, error=str(exc))

        try:
            docs = list(self._yaml.load_all(original))
        except Exception as exc:
            return Result(path, Outcome.FAILED, error=f"unparseable: {exc}")

        typed = [
            (doc, FileTypeDetector.detect(doc)) for doc in docs if isinstance(doc, CommentedMap)
        ]
        sortable = [
            (doc, kind)
            for doc, kind in typed
            if kind != GENERIC and self.config.has_template(kind)
        ]
        if not sortable:
            return Result(path, Outcome.SKIPPED)

        file_type = sortable[0][1]
        try:
            for doc, kind in sortable:
                self.sorter.sort_document(doc, self.config.load(kind))
        except (ConfigError, ParseError) as exc:
            return Result(path, Outcome.FAILED, file_type, str(exc))

        rendered = self._render(docs, explicit_start=original.lstrip().startswith("---"))
        if rendered.strip() == original.strip():
            return Result(path, Outcome.UNCHANGED, file_type)

        moved = _detached_comments(original, rendered)
        if moved:
            return Result(
                path,
                Outcome.SKIPPED,
                file_type,
                f"round-trip would move {moved} away from what it documents",
            )

        if not self.dry_run:
            try:
                self._write(path, rendered)
            except OSError as exc:
                return Result(path, Outcome.FAILED, file_type, str(exc))

        return Result(path, Outcome.CHANGED, file_type)

    def _render(self, docs: list[YAMLValue], explicit_start: bool) -> str:
        buffer = io.StringIO()
        for index, doc in enumerate(docs):
            if index > 0 or explicit_start:
                _ = buffer.write("---\n")
            self._yaml.dump(doc, buffer)
        return buffer.getvalue()

    @staticmethod
    def _write(path: Path, content: str) -> None:
        """Replace the file atomically, keeping its permissions."""
        mode = path.stat().st_mode
        tmp = tempfile.NamedTemporaryFile(
            mode="w", dir=path.parent, delete=False, encoding="utf-8", suffix=".yamlsorter"
        )
        try:
            with tmp:
                _ = tmp.write(content)
                tmp.flush()
                os.fsync(tmp.fileno())
            os.chmod(tmp.name, mode & 0o7777)
            shutil.move(tmp.name, path)
        except Exception:
            Path(tmp.name).unlink(missing_ok=True)
            raise


@final
class MissingKeyAuditor:
    """Reports manifest keys no template mentions, so templates can be grown."""

    def __init__(self, config: ConfigManager, substitution_markers: set[str]) -> None:
        self.config = config
        self.markers = substitution_markers

    def audit(self, docs: Iterable[CommentedMap], stats: Stats) -> None:
        for doc in docs:
            file_type = FileTypeDetector.detect(doc)
            if file_type == GENERIC or not self.config.has_template(file_type):
                continue

            try:
                orders = self.config.load(file_type)
            except ConfigError:
                continue

            known = {key for keys in orders.values() for key in keys if key != WILDCARD}
            wildcard_sections = {
                section for section, keys in orders.items() if WILDCARD in keys
            }

            # A chart-specific template covers spec.values; the generic one does not,
            # so auditing it there would flag every chart option as missing.
            skip_values = not (self.config.config_dir / f"{file_type}{TEMPLATE_SUFFIX}").is_file()

            used = self._keys(doc, [], wildcard_sections, skip_values)
            missing = used - known
            if missing:
                stats.missing_keys.setdefault(file_type, set()).update(missing)

    # Keys inside these are user-chosen names, not schema, so they are never "missing".
    OPAQUE_MAPS: Final[frozenset[str]] = frozenset(
        {"labels", "annotations", "matchLabels", "nodeSelector", "data", "stringData", "env"}
    )

    def _keys(
        self,
        node: dict[str, YAMLValue],
        path: list[str],
        wildcard_sections: set[str],
        skip_values: bool,
    ) -> set[str]:
        found: set[str] = set()

        for key, value in node.items():
            child = [*path, key]

            if skip_values and child[:2] == ["spec", "values"]:
                continue
            if self._is_substitution(key):
                continue
            if self._under_wildcard(child, wildcard_sections):
                continue

            found.add(key)

            if key in self.OPAQUE_MAPS:
                continue

            if isinstance(value, dict):
                found |= self._keys(value, child, wildcard_sections, skip_values)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        found |= self._keys(item, child, wildcard_sections, skip_values)

        return found

    def _is_substitution(self, key: str) -> bool:
        if "ALL_CAPS" in self.markers and key.isupper() and key.replace("_", "").isalpha():
            return True
        return any(marker != "ALL_CAPS" and marker in key for marker in self.markers)

    @staticmethod
    def _under_wildcard(path: list[str], wildcard_sections: set[str]) -> bool:
        """True for names the template stands in for with `*` (app names, env vars)."""
        prefix = PATH_SEP.join(path[:-1])
        return any(
            prefix == section or prefix.startswith(f"{section}{PATH_SEP}")
            for section in wildcard_sections
        )


@final
class SortingTool:
    def __init__(
        self,
        config_dir: Path,
        *,
        dry_run: bool = False,
        substitution_markers: set[str] | None = None,
    ) -> None:
        self.config = ConfigManager(config_dir)
        self.sorter = KeySorter(self.config)
        self.processor = FileProcessor(self.sorter, self.config, dry_run)
        self.auditor = MissingKeyAuditor(
            self.config, substitution_markers or {"ALL_CAPS"}
        )
        self.dry_run = dry_run

    def run(self, paths: list[Path], names: list[str], *, audit: bool) -> int:
        try:
            self.config.validate()
        except ConfigError as exc:
            log.error("%s", exc)
            return 2

        files = sorted(set(self._collect(paths, names)))
        if not files:
            log.warning("no matching files found")
            return 0

        stats = Stats()
        for path in files:
            result = self.processor.process(path)
            stats.record(result)

            match result.outcome:
                case Outcome.CHANGED:
                    log.info("%s %s (%s)", "would sort" if self.dry_run else "sorted", path, result.file_type)
                case Outcome.FAILED:
                    log.error("%s: %s", path, result.error)
                case Outcome.SKIPPED if result.error:
                    log.warning("skipped %s: %s", path, result.error)
                case Outcome.SKIPPED:
                    log.debug("skipped %s", path)
                case Outcome.UNCHANGED:
                    log.debug("unchanged %s", path)

            if audit and result.outcome is not Outcome.FAILED:
                self._audit(path, stats)

        self._report(stats)
        if stats.failed:
            return 2
        # In check mode an unsorted file is the finding, so it has to fail the run.
        return 1 if self.dry_run and stats.changed else 0

    def _audit(self, path: Path, stats: Stats) -> None:
        try:
            docs = self.processor._yaml.load_all(path.read_text(encoding="utf-8"))
            self.auditor.audit((d for d in docs if isinstance(d, CommentedMap)), stats)
        except Exception:  # auditing is advisory; never fail a run over it
            log.debug("audit failed for %s", path, exc_info=True)

    @staticmethod
    def _collect(paths: list[Path], names: list[str]) -> Iterator[Path]:
        """Yield the files to sort. Explicit file arguments bypass the name filter."""
        wanted = set(names)
        for path in paths:
            if path.is_file():
                yield path
            elif path.is_dir():
                for root, dirs, filenames in os.walk(path):
                    dirs[:] = [d for d in dirs if not d.startswith(".")]
                    yield from (
                        Path(root) / name for name in filenames if name in wanted
                    )
            else:
                log.warning("no such path: %s", path)

    def _report(self, stats: Stats) -> None:
        log.info(
            "%d files: %d %s, %d unchanged, %d skipped, %d failed",
            stats.total,
            stats.changed,
            "to sort" if self.dry_run else "sorted",
            stats.unchanged,
            stats.skipped,
            stats.failed,
        )

        for file_type, keys in sorted(stats.missing_keys.items()):
            log.info("keys absent from %s%s: %s", file_type, TEMPLATE_SUFFIX, ", ".join(sorted(keys)))


DEFAULT_NAMES: Final = ["helmrelease.yaml", "kustomization.yaml", "ks.yaml"]
DEFAULT_MARKERS: Final = ["ALL_CAPS", "kustomize.toolkit.fluxcd.io/substitute"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yamlsorter",
        description="Reorder keys in Flux manifests to match per-type templates.",
    )
    _ = parser.add_argument("paths", type=Path, nargs="+", help="files or directories to sort")
    _ = parser.add_argument(
        "--config-dir",
        type=Path,
        default=Path("scripts/config"),
        help="directory of template manifests (default: %(default)s)",
    )
    _ = parser.add_argument(
        "--check",
        action="store_true",
        help="report what would change without writing, exit 1 if anything would",
    )
    _ = parser.add_argument("--dry-run", action="store_true", help="alias for --check")
    _ = parser.add_argument(
        "--names",
        nargs="+",
        default=DEFAULT_NAMES,
        metavar="NAME",
        help="filenames to pick up when walking directories (default: %(default)s)",
    )
    _ = parser.add_argument(
        "--audit",
        action="store_true",
        help="also list manifest keys no template mentions",
    )
    _ = parser.add_argument("--verbose", "-v", action="store_true", help="log skipped files too")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s",
        stream=sys.stderr,
    )

    tool = SortingTool(
        config_dir=args.config_dir,
        dry_run=args.check or args.dry_run,
        substitution_markers=set(DEFAULT_MARKERS),
    )
    return tool.run(args.paths, args.names, audit=args.audit)


if __name__ == "__main__":
    sys.exit(main())
