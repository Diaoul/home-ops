import sys
from pathlib import Path

import pytest
from ruamel.yaml import YAML

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

REPO_CONFIG = Path(__file__).resolve().parents[2] / "config"


@pytest.fixture
def yaml() -> YAML:
    reader = YAML()
    reader.preserve_quotes = True
    reader.width = 4096
    return reader


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    """A minimal template set, enough to exercise ordering without the real repo one."""
    directory = tmp_path / "config"
    directory.mkdir()

    (directory / "flux-kustomization.yaml.tpl").write_text(
        "apiVersion: kustomize.toolkit.fluxcd.io/v1\n"
        "kind: Kustomization\n"
        "metadata:\n"
        "  name: name\n"
        "  namespace: namespace\n"
        "spec:\n"
        "  sourceRef:\n"
        "    kind: kind\n"
        "    name: name\n"
        "    namespace: namespace\n"
        "  path: path\n"
        "  interval: interval\n"
        "  dependsOn:\n"
        "    - name: name\n"
        "      namespace: namespace\n"
        "  targetNamespace: targetNamespace\n"
        "  components: []\n"
        "  postBuild:\n"
        "    substituteFrom: []\n"
        "    substitute: {}\n"
        "  prune: prune\n"
        "  wait: wait\n",
        encoding="utf-8",
    )

    (directory / "helmrelease.yaml.tpl").write_text(
        "apiVersion: helm.toolkit.fluxcd.io/v2\n"
        "kind: HelmRelease\n"
        "metadata:\n"
        "  name: name\n"
        "spec:\n"
        "  interval: interval\n"
        "  chartRef:\n"
        "    kind: kind\n"
        "    name: name\n"
        "  install: {}\n"
        "  upgrade: {}\n"
        "  values: {}\n",
        encoding="utf-8",
    )

    (directory / "helmrelease-apptemplate.yaml.tpl").write_text(
        "apiVersion: helm.toolkit.fluxcd.io/v2\n"
        "kind: HelmRelease\n"
        "metadata:\n"
        "  name: name\n"
        "spec:\n"
        "  interval: interval\n"
        "  chartRef:\n"
        "    kind: kind\n"
        "    name: name\n"
        "  values:\n"
        "    controllers:\n"
        '      "*":\n'
        "        annotations: {}\n"
        "        containers:\n"
        '          "*":\n'
        "            image:\n"
        "              repository: repository\n"
        "              tag: tag\n"
        "            env: {}\n"
        "            envFrom: []\n"
        "            securityContext: {}\n"
        "            resources: {}\n",
        encoding="utf-8",
    )

    return directory
