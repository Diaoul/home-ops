from pathlib import Path

import pytest

from fixtures import KS, SECRET
from yamlsorter import FileTypeDetector, Outcome, SortingTool, main

@pytest.mark.parametrize(
    ("doc", "expected"),
    [
        ({"kind": "HelmRelease", "spec": {"chartRef": {"name": "app-template"}}}, "helmrelease-apptemplate"),
        ({"kind": "HelmRelease", "spec": {"chart": {"spec": {"chart": "cilium"}}}}, "helmrelease-cilium"),
        ({"kind": "HelmRelease", "spec": {}}, "helmrelease"),
        (
            {"kind": "Kustomization", "apiVersion": "kustomize.toolkit.fluxcd.io/v1"},
            "flux-kustomization",
        ),
        (
            {"kind": "Kustomization", "apiVersion": "kustomize.config.k8s.io/v1beta1"},
            "kustomization",
        ),
        ({"kind": "Component", "apiVersion": "kustomize.config.k8s.io/v1alpha1"}, "component"),
        ({"kind": "Secret"}, "generic"),
        ({}, "generic"),
    ],
)
def test_detect(doc: dict[str, object], expected: str):
    assert FileTypeDetector.detect(doc) == expected


def test_unsupported_document_is_skipped_not_failed(tmp_path: Path, config_dir: Path):
    target = tmp_path / "secret.sops.yaml"
    _ = target.write_text(SECRET, encoding="utf-8")

    result = SortingTool(config_dir).processor.process(target)

    assert result.outcome is Outcome.SKIPPED
    assert target.read_text(encoding="utf-8") == SECRET


def test_unparseable_file_fails_without_writing(tmp_path: Path, config_dir: Path):
    target = tmp_path / "ks.yaml"
    _ = target.write_text("apiVersion: [unclosed\n", encoding="utf-8")

    result = SortingTool(config_dir).processor.process(target)

    assert result.outcome is Outcome.FAILED
    assert target.read_text(encoding="utf-8") == "apiVersion: [unclosed\n"


def test_missing_config_dir_is_reported(tmp_path: Path):
    tool = SortingTool(tmp_path / "absent")

    assert tool.run([tmp_path], ["ks.yaml"], audit=False) == 2


def test_empty_config_dir_is_reported(tmp_path: Path):
    empty = tmp_path / "config"
    empty.mkdir()

    assert SortingTool(empty).run([tmp_path], ["ks.yaml"], audit=False) == 2


def test_directory_walk_only_picks_up_named_files(tmp_path: Path, config_dir: Path):
    (tmp_path / "app").mkdir()
    _ = (tmp_path / "app" / "secret.sops.yaml").write_text(SECRET, encoding="utf-8")
    _ = (tmp_path / "app" / "httproute.yaml").write_text(SECRET, encoding="utf-8")

    tool = SortingTool(config_dir)
    collected = list(tool._collect([tmp_path / "app"], ["ks.yaml", "helmrelease.yaml"]))

    assert collected == []


def test_explicit_file_argument_bypasses_the_name_filter(tmp_path: Path, config_dir: Path):
    target = tmp_path / "oddly-named.yaml"
    _ = target.write_text(SECRET, encoding="utf-8")

    collected = list(SortingTool(config_dir)._collect([target], ["ks.yaml"]))

    assert collected == [target]


def test_hidden_directories_are_not_walked(tmp_path: Path, config_dir: Path):
    (tmp_path / ".git").mkdir()
    _ = (tmp_path / ".git" / "ks.yaml").write_text(SECRET, encoding="utf-8")

    collected = list(SortingTool(config_dir)._collect([tmp_path], ["ks.yaml"]))

    assert collected == []


def test_check_mode_reports_without_writing(tmp_path: Path, config_dir: Path):
    target = tmp_path / "ks.yaml"
    _ = target.write_text(KS, encoding="utf-8")

    status = SortingTool(config_dir, dry_run=True).run([target], ["ks.yaml"], audit=False)

    assert status == 1
    assert target.read_text(encoding="utf-8") == KS


def test_check_mode_passes_on_sorted_files(tmp_path: Path, config_dir: Path):
    target = tmp_path / "ks.yaml"
    _ = target.write_text(KS, encoding="utf-8")
    _ = SortingTool(config_dir).run([target], ["ks.yaml"], audit=False)

    assert SortingTool(config_dir, dry_run=True).run([target], ["ks.yaml"], audit=False) == 0


def test_missing_template_type_is_skipped_rather_than_failing(tmp_path: Path, config_dir: Path):
    (config_dir / "flux-kustomization.yaml.tpl").unlink()
    target = tmp_path / "ks.yaml"
    _ = target.write_text(KS, encoding="utf-8")

    assert SortingTool(config_dir).processor.process(target).outcome is Outcome.SKIPPED


def test_cli_exit_code_on_check(tmp_path: Path, config_dir: Path):
    target = tmp_path / "ks.yaml"
    _ = target.write_text(KS, encoding="utf-8")

    assert main([str(target), "--config-dir", str(config_dir), "--check"]) == 1
    assert main([str(target), "--config-dir", str(config_dir)]) == 0
    assert main([str(target), "--config-dir", str(config_dir), "--check"]) == 0


def test_comment_after_a_list_dash_blocks_the_rewrite(tmp_path: Path, config_dir: Path):
    """ruamel reattaches such a comment to the previous entry, so refuse to rewrite."""
    body = (
        "---\n"
        "apiVersion: kustomize.toolkit.fluxcd.io/v1\n"
        "kind: Kustomization\n"
        "metadata:\n"
        "  name: app\n"
        "spec:\n"
        "  prune: true\n"
        "  path: ./path\n"
        "  sourceRef:\n"
        "    kind: GitRepository\n"
        "  dependsOn:\n"
        "    - # first dependency\n"
        "      name: one\n"
        "    - # second dependency\n"
        "      name: two\n"
    )
    target = tmp_path / "ks.yaml"
    _ = target.write_text(body, encoding="utf-8")

    result = SortingTool(config_dir).processor.process(target)

    assert result.outcome is Outcome.SKIPPED
    assert result.error is not None
    assert "documents" in result.error
    assert target.read_text(encoding="utf-8") == body


def test_a_header_comment_does_not_block_the_rewrite(tmp_path: Path, config_dir: Path):
    """Nothing reorders above the schema header, so it anchors to apiVersion either way."""
    target = tmp_path / "ks.yaml"
    _ = target.write_text(KS, encoding="utf-8")

    result = SortingTool(config_dir).processor.process(target)

    assert result.outcome is Outcome.CHANGED
    assert target.read_text(encoding="utf-8").startswith(
        "---\n# yaml-language-server: $schema=https://example.invalid/kustomization.json\n"
        "apiVersion:"
    )
