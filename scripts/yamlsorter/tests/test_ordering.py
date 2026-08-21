from pathlib import Path

from ruamel.yaml import YAML

from fixtures import KS
from yamlsorter import Outcome, SortingTool, extract_key_order

def sort_file(path: Path, config_dir: Path, **kwargs: object) -> Outcome:
    tool = SortingTool(config_dir, **kwargs)  # type: ignore[arg-type]
    return tool.processor.process(path).outcome


def test_extract_key_order_flattens_nested_sections():
    orders = extract_key_order({"spec": {"a": 1, "b": {"c": 2, "d": 3}}, "kind": "X"})

    assert orders["root"] == ["spec", "kind"]
    assert orders["spec"] == ["a", "b"]
    assert orders["spec.b"] == ["c", "d"]


def test_extract_key_order_merges_list_entry_keys():
    orders = extract_key_order({"spec": {"deps": [{"a": 1}, {"b": 2, "a": 3}]}})

    assert orders["spec.deps"] == ["a", "b"]


def test_spec_keys_follow_template(tmp_path: Path, config_dir: Path, yaml: YAML):
    target = tmp_path / "ks.yaml"
    _ = target.write_text(KS, encoding="utf-8")

    assert sort_file(target, config_dir) is Outcome.CHANGED

    doc = yaml.load(target.read_text(encoding="utf-8"))
    assert list(doc["spec"]) == [
        "sourceRef",
        "path",
        "interval",
        "targetNamespace",
        "prune",
        "wait",
    ]
    assert list(doc["spec"]["sourceRef"]) == ["kind", "name"]


def test_schema_comment_and_document_start_survive(tmp_path: Path, config_dir: Path):
    target = tmp_path / "ks.yaml"
    _ = target.write_text(KS, encoding="utf-8")

    _ = sort_file(target, config_dir)
    text = target.read_text(encoding="utf-8")

    assert text.startswith("---\n# yaml-language-server: $schema=")


def test_already_sorted_file_is_untouched(tmp_path: Path, config_dir: Path):
    target = tmp_path / "ks.yaml"
    _ = target.write_text(KS, encoding="utf-8")
    _ = sort_file(target, config_dir)
    once = target.read_text(encoding="utf-8")

    assert sort_file(target, config_dir) is Outcome.UNCHANGED
    assert target.read_text(encoding="utf-8") == once


def test_untemplated_keys_keep_their_order_after_templated_ones(
    tmp_path: Path, config_dir: Path, yaml: YAML
):
    target = tmp_path / "ks.yaml"
    _ = target.write_text(
        KS.replace("  interval: 10m\n", "  interval: 10m\n  zebra: 1\n  alpha: 2\n"),
        encoding="utf-8",
    )

    _ = sort_file(target, config_dir)

    doc = yaml.load(target.read_text(encoding="utf-8"))
    assert list(doc["spec"])[-2:] == ["zebra", "alpha"]


def test_wildcard_template_orders_container_keys(
    tmp_path: Path, config_dir: Path, yaml: YAML
):
    target = tmp_path / "helmrelease.yaml"
    _ = target.write_text(
        "---\n"
        "apiVersion: helm.toolkit.fluxcd.io/v2\n"
        "kind: HelmRelease\n"
        "metadata:\n"
        "  name: app\n"
        "spec:\n"
        "  chartRef:\n"
        "    kind: OCIRepository\n"
        "    name: app-template\n"
        "  interval: 30m\n"
        "  values:\n"
        "    controllers:\n"
        "      app:\n"
        "        containers:\n"
        "          app:\n"
        "            resources: {}\n"
        "            securityContext: {}\n"
        "            env:\n"
        "              TZ: Europe/Paris\n"
        "            image:\n"
        "              tag: v1\n"
        "              repository: repo\n",
        encoding="utf-8",
    )

    assert sort_file(target, config_dir) is Outcome.CHANGED

    doc = yaml.load(target.read_text(encoding="utf-8"))
    container = doc["spec"]["values"]["controllers"]["app"]["containers"]["app"]
    assert list(container) == ["image", "env", "securityContext", "resources"]
    assert list(container["image"]) == ["repository", "tag"]


def test_anchors_and_aliases_survive(tmp_path: Path, config_dir: Path):
    target = tmp_path / "helmrelease.yaml"
    _ = target.write_text(
        "---\n"
        "apiVersion: helm.toolkit.fluxcd.io/v2\n"
        "kind: HelmRelease\n"
        "metadata:\n"
        "  name: &app app\n"
        "spec:\n"
        "  values:\n"
        "    controllers:\n"
        "      *app: {}\n"
        "  interval: 30m\n"
        "  chartRef:\n"
        "    kind: OCIRepository\n"
        "    name: other\n",
        encoding="utf-8",
    )

    _ = sort_file(target, config_dir)
    text = target.read_text(encoding="utf-8")

    assert "&app" in text
    assert "*app" in text


def test_quoted_scalars_keep_their_quotes(tmp_path: Path, config_dir: Path):
    target = tmp_path / "ks.yaml"
    _ = target.write_text(
        KS.replace("  interval: 10m\n", '  interval: 10m\n  quoted: "1"\n'),
        encoding="utf-8",
    )

    _ = sort_file(target, config_dir)

    assert 'quoted: "1"' in target.read_text(encoding="utf-8")


def test_file_permissions_are_preserved(tmp_path: Path, config_dir: Path):
    target = tmp_path / "ks.yaml"
    _ = target.write_text(KS, encoding="utf-8")
    target.chmod(0o640)

    _ = sort_file(target, config_dir)

    assert target.stat().st_mode & 0o777 == 0o640


def test_multi_document_file_sorts_every_document(tmp_path: Path, config_dir: Path):
    target = tmp_path / "ks.yaml"
    _ = target.write_text(KS + KS.replace("name: app", "name: other"), encoding="utf-8")

    assert sort_file(target, config_dir) is Outcome.CHANGED

    text = target.read_text(encoding="utf-8")
    assert text.count("---") == 2
    assert text.count("sourceRef") == 2
