import argparse
import http.client
import importlib.util
import sys
import urllib.request
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "survey", Path(__file__).resolve().parent.parent / "scripts" / "survey.py")
assert _spec and _spec.loader
survey = importlib.util.module_from_spec(_spec)
sys.modules["survey"] = survey
_spec.loader.exec_module(survey)


# --------------------------------------------------------------------------- #
# flattening and parsing
# --------------------------------------------------------------------------- #
def test_flatten_keys_named_lists_by_name():
    values = {"controllers": {"app": {"containers": {"app": {"env": [
        {"name": "DB_HOSTNAME", "value": "immich-rw"},
        {"name": "TZ", "value": "Europe/Paris"},
    ]}}}}}
    flat = survey.flatten(values)
    assert flat["controllers.app.containers.app.env.DB_HOSTNAME"] == "immich-rw"
    assert flat["controllers.app.containers.app.env.TZ"] == "Europe/Paris"


def test_flatten_collapses_scalar_lists_and_marks_unnamed_ones():
    flat = survey.flatten({"args": ["--a", "--b"], "mounts": [{"path": "/x"}]})
    assert flat == {"args": "--a,--b", "mounts": "<list>"}


def test_duplicate_anchors_still_parse():
    text = (
        "kind: HelmRelease\n"
        "a: &probes {x: 1}\n"
        "b: *probes\n"
        "c: &probes {x: 2}\n"
        "d: *probes\n"
    )
    (doc,) = survey.yaml_docs_of(text)
    assert doc["b"] == {"x": 1}
    assert doc["d"] == {"x": 2}


# --------------------------------------------------------------------------- #
# app matching
# --------------------------------------------------------------------------- #
def test_helmrelease_paths_skip_vendored_charts():
    paths = [
        "kubernetes/apps/media/immich/app/helmrelease.yaml",
        "charts/immich/templates/helmrelease.yaml",
        "kubernetes/apps/media/immich/ks.yaml",
    ]
    hits, seen = survey.app_helmrelease_paths(paths, "immich")
    assert hits == ["kubernetes/apps/media/immich/app/helmrelease.yaml"]
    assert seen


@pytest.mark.parametrize("name", ["helmrelease.yaml", "helmrelease.yml",
                                  "helm-release.yaml", "helm-release.yml"])
def test_helmrelease_paths_accept_every_spelling(name):
    assert survey.app_helmrelease_paths([f"k/immich/app/{name}"], "immich")[0]


def test_helmrelease_paths_tell_no_app_from_no_release():
    assert survey.app_helmrelease_paths(["apps/radarr/ks.yaml"], "immich") == ([], False)
    assert survey.app_helmrelease_paths(["apps/immich/ks.yaml"], "immich") == ([], True)


@pytest.mark.parametrize(("name", "path", "expected"), [
    ("immich", "/k/immich/app/helmrelease.yaml", True),
    ("radarr-4k", "/k/radarr/app-4k/helmrelease.yaml", True),
    ("photos", "/k/immich/helmrelease.yaml", True),
    ("immich-ml", "/k/immich/machine-learning/helmrelease.yaml", False),
])
def test_looks_like_app(name, path, expected):
    app = path.split("/")[2]
    doc = {"kind": "HelmRelease", "metadata": {"name": name}}
    assert survey.looks_like_app(doc, app, path, None) is expected


@pytest.mark.parametrize(("raw", "expected"), [
    ("immich-postgres-rw.media.svc.cluster.local", ("immich-postgres-rw", "literal")),
    ("postgres://u:p@pg-rw.database.svc:5432/immich?sslmode=disable", ("pg-rw", "literal")),
    ("${DB_HOST}", ("${DB_HOST}", "template")),
    ({"valueFrom": {"secretKeyRef": {"name": "immich-pguser"}}},
     ("unresolved:immich-pguser", "secret-ref")),
    ("", ("", "none")),
])
def test_service_of(raw, expected):
    assert survey.service_of(raw) == expected


@pytest.mark.parametrize(("text", "subs", "expected"), [
    ("postgres-${APP}", {"APP": "immich"}, "postgres-immich"),
    ("${SIZE:=5Gi}", {}, "5Gi"),
    ("${SIZE:=5Gi}", {"SIZE": "10Gi"}, "10Gi"),
    ("${SC:-ceph-block}", {}, "ceph-block"),
    ("$APP_NAME-$APP", {"APP": "immich", "APP_NAME": "photos"}, "photos-immich"),
    ("${APP:=x}", {"APP": "a\\1"}, "a\\1"),
])
def test_render(text, subs, expected):
    assert survey.render(text, subs) == expected


@pytest.mark.parametrize(("argv", "expected"), [
    (["--app", "immich", "--facts", "--markdown", "survey.md", "--json", "out.json"],
     ["--app", "immich", "--facts"]),
    (["--app=immich", "--workdir=/tmp/x", "--offline", "--want", "20"],
     ["--app=immich", "--want", "20"]),
    (["--app", "immich", "--candidates", "/home/me/cands.txt"],
     ["--app", "immich", "--candidates", "cands.txt"]),
])
def test_recorded_args_keep_a_runnable_command(argv, expected):
    assert survey.recorded_args(argv) == expected


@pytest.mark.parametrize(("value", "expected"), [
    ("plain", "`plain`"),
    ("a|b", "`a\\|b`"),
    ("has `tick`", "`` has `tick` ``"),
    ("", "-"),
    (None, "-"),
])
def test_md_code(value, expected):
    assert survey._md_code(value) == expected


# --------------------------------------------------------------------------- #
# discovery and the denominator
# --------------------------------------------------------------------------- #
class FakeGitHub:
    def __init__(self, repos: dict[str, list[str] | None], flags: dict[str, str] | None = None):
        self.repos = repos
        self.flags = flags or {}
        self.last_rev = "main"
        self.listed: list[str] = []

    def search_repos(self, *_args, **_kwargs):
        return [{"full_name": slug, "default_branch": "main",
                 "fork": self.flags.get(slug) == "fork",
                 "archived": self.flags.get(slug) == "archived"}
                for slug in self.repos]

    def list_tree(self, slug, _branch, _listing, refresh=False):
        self.listed.append(slug)
        paths = self.repos[slug]
        if paths is None:
            raise survey.GitHubError("boom")
        return [{"path": p, "sha": f"sha-{p}", "type": "blob"} for p in paths], False


def _args(**kw):
    base = {"app": "immich", "candidates": None, "search_pages": 1, "refresh": False,
            "max_candidates": 400, "want": 2, "listing": "auto"}
    return argparse.Namespace(**{**base, **kw})


def test_discover_totals_add_up_and_stop_at_want():
    release = "k/immich/app/helmrelease.yaml"
    gh = FakeGitHub({
        "a/fork": [release],
        "a/one": [release],
        "a/none": ["k/radarr/app/helmrelease.yaml"],
        "a/broken": None,
        "a/two": [release],
        "a/after": [release],
    }, flags={"a/fork": "fork"})
    matched, skipped, candidates, examined = survey.discover(_args(), gh)
    assert [m["full_name"] for m in matched] == ["a/one", "a/two"]
    assert [(s["repo"], s["reason"]) for s in skipped] == [
        ("a/fork", "fork"), ("a/none", "no-app"), ("a/broken", "error")]
    assert examined == 4
    assert "a/after" not in gh.listed
    assert len(candidates) == 6


def test_report_counts_a_second_instance_once(capsys):
    agg = {"image": {"radarr": {"a/one", "a/two"}}}
    matched = [("a/one", "radarr/app/helmrelease.yaml"),
               ("a/one", "radarr/app-4k/helmrelease.yaml"),
               ("a/two", "radarr/app/helmrelease.yaml")]
    args = argparse.Namespace(filter=None, min_repos=1, top=8)
    survey.report_keys(agg, matched, "radarr", None, args)
    out = capsys.readouterr().out
    assert "repos_that_run_app=2" in out
    assert "## image  (2/2 repos)" in out


# --------------------------------------------------------------------------- #
# cache and network
# --------------------------------------------------------------------------- #
def test_blob_cache_is_keyed_by_sha(tmp_path):
    gh = survey.GitHub(tmp_path, offline=True)
    cached = tmp_path / "blobs" / "ab" / "abcdef"
    cached.parent.mkdir(parents=True)
    cached.write_text("kind: HelmRelease\n")
    assert gh.blob("o/r", "main", "any/path.yaml", "abcdef") == "kind: HelmRelease\n"
    assert gh.blob("o/r", "main", "any/path.yaml", "other") is None


def test_listings_expire_unless_offline(tmp_path):
    cache = tmp_path / "api" / "x.json"
    cache.parent.mkdir(parents=True)
    cache.write_text("{}")
    assert survey.GitHub(tmp_path, max_age=3600)._fresh(cache)
    assert not survey.GitHub(tmp_path, max_age=-1)._fresh(cache)
    assert survey.GitHub(tmp_path, offline=True, max_age=-1)._fresh(cache)


def test_open_retries_a_dropped_connection(monkeypatch):
    calls = []

    class Resp:
        headers: dict = {}

        def __init__(self, body: bytes):
            self.body = body

        def read(self) -> bytes:
            return self.body

        def __enter__(self):
            return self

        def __exit__(self, *exc) -> None:
            return None

    def urlopen(_req, timeout):
        calls.append(timeout)
        if len(calls) < 3:
            raise http.client.RemoteDisconnected("closed")
        return Resp(b"{}")

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(survey.time, "sleep", lambda _s: None)
    body, _ = survey._open(urllib.request.Request("https://example.invalid"), "test")
    assert body == b"{}"
    assert len(calls) == 3


def test_open_gives_up_with_a_github_error(monkeypatch):
    def urlopen(_req, timeout):
        raise TimeoutError("slow")

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(survey.time, "sleep", lambda _s: None)
    with pytest.raises(survey.GitHubError):
        survey._open(urllib.request.Request("https://example.invalid"), "test")


# --------------------------------------------------------------------------- #
# where the data lives
# --------------------------------------------------------------------------- #
class FakeMaterial:
    def __init__(self, files: dict[str, str]):
        self.paths = list(files)
        self.files = files

    def yaml_docs(self, path):
        return survey.yaml_docs_of(self.files[path])


def test_library_store_follows_a_claim_to_its_nfs_pv():
    mat = FakeMaterial({
        "k/immich/app/pvc.yaml": (
            "kind: PersistentVolumeClaim\nmetadata: {name: immich-library}\n"
            "spec: {volumeName: immich-nfs}\n"),
        "k/storage/immich-nfs.yaml": (
            "kind: PersistentVolume\nmetadata: {name: immich-nfs}\n"
            "spec: {nfs: {server: nas, path: /photos}}\n"),
    })
    library = {"type": "existingClaim", "claim": "immich-library"}
    store = survey.library_store(mat, library, "k/immich", [], {}, "immich")
    assert store == {"store": "nas", "via": "PV immich-nfs"}


@pytest.mark.parametrize(("library", "store"), [
    ({"type": "nfs", "server": "nas"}, "nas"),
    ({"type": "hostPath"}, "node-local"),
    ({"type": "persistentVolumeClaim", "storage_class": "ceph-block"}, "network"),
    ({"type": "persistentVolumeClaim", "storage_class": "nfs-client"}, "nas"),
    ({"type": "existingClaim", "claim": "media-nfs"}, "nas"),
])
def test_library_store_by_mount(library, store):
    assert survey.library_store(FakeMaterial({}), library, "k/immich", [], {}, "immich")["store"] == store


def _entry(typ="persistentVolumeClaim", mounts=(), sc=""):
    return {"type": typ, "mounts": list(mounts), "storage_class": sc}


def test_pick_library_skips_config_cache_and_scratch():
    persistence = {
        "config": _entry("existingClaim", ["/config"]),
        "cache": _entry("emptyDir", ["/cache"]),
        "metadata": _entry(mounts=["/config/metadata"]),
        "media2": _entry(mounts=["/media2/library"]),
    }
    assert survey.pick_library(persistence) == "media2"


def test_pick_library_prefers_a_named_data_volume_over_any_nfs_mount():
    persistence = {
        "tv-guides": _entry("nfs", ["/tv-guides"]),
        "media": _entry("existingClaim", ["/media"]),
    }
    assert survey.pick_library(persistence) == "media"


def test_pick_library_hint_wins():
    persistence = {"library": _entry(mounts=["/usr/src/app/upload"]),
                   "thumbs": _entry(mounts=["/usr/src/app/upload/thumbs"])}
    assert survey.pick_library(persistence, "thumbs") == "thumbs"
    assert survey.pick_library(persistence, "/usr/src/app/upload") == "library"
    assert survey.pick_library(persistence, "missing") == "library"


def test_pick_library_reads_the_mount_path_not_the_controller():
    persistence = {"library": _entry("existingClaim", ["backup/restic:/data", "/usr/src/app/upload"])}
    assert survey.pick_library(persistence) == "library"


def test_pick_library_skips_the_database_volume():
    persistence = {"database": _entry(mounts=["postgres/app:/var/lib/postgresql/data"]),
                   "library": _entry(mounts=["/usr/src/app/upload"])}
    assert survey.pick_library(persistence) == "library"


@pytest.mark.parametrize("name", ["runner-data", "devices-media", "logos-media", "templates-library"])
def test_pick_library_does_not_veto_on_a_prefix(name):
    assert survey.pick_library({name: _entry(mounts=["/srv"])}) == name


def test_namespace_ks_keeps_only_the_apps_kustomizations():
    mat = FakeMaterial({"k/media/ks.yaml": (
        "kind: Kustomization\nmetadata: {name: immich}\n"
        "spec: {path: ./k/media/immich/app, postBuild: {substitute: {APP: immich}}}\n"
        "---\n"
        "kind: Kustomization\nmetadata: {name: radarr}\n"
        "spec: {path: ./k/media/radarr/app, components: [../../components/ext-auth],\n"
        "       postBuild: {substitute: {APP: radarr}}}\n")})
    docs = survey.app_kustomizations(mat, ["k/media/ks.yaml"], "immich", "k/media/immich")
    comp = survey.collect_components(docs, "k/media/immich")
    assert comp["substitutes"] == {"APP": "immich"}
    assert comp["components"] == []
    assert comp["dirs"] == ["app"]


def test_components_resolve_against_the_repo_root_path():
    docs = [{"kind": "Kustomization", "spec": {
        "path": "./k/media/immich/app", "components": ["../../../components/zeroscaler"]}},
        {"kind": "Kustomization", "spec": {"path": "./k/database/cnpg"}}]
    comp = survey.collect_components(docs, "k/media/immich")
    assert comp["component_dirs"] == ["k/components/zeroscaler"]
    assert comp["dirs"] == ["app"]


def test_components_of_a_root_path_resolve_from_the_root():
    docs = [{"kind": "Kustomization", "spec": {"path": "./", "components": ["k/components/x"]}}]
    assert survey.collect_components(docs, "k/media/immich")["component_dirs"] == ["k/components/x"]


def test_a_kustomize_kustomization_is_not_a_flux_one():
    mat = FakeMaterial({"k/media/immich/kustomization.yaml": (
        "apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\n"
        "resources: [./ks.yaml]\n")})
    assert survey.app_kustomizations(
        mat, ["k/media/immich/kustomization.yaml"], "immich", "k/media/immich") == []


def test_a_templated_db_host_matches_its_cluster():
    mat = FakeMaterial({"k/database/cluster.yaml": (
        "apiVersion: postgresql.cnpg.io/v1\nkind: Cluster\nmetadata: {name: postgres-immich}\n"
        "spec: {imageName: ghcr.io/tensorchord/cloudnative-vectorchord:17}\n"),
        "k/database/other.yaml": (
        "apiVersion: postgresql.cnpg.io/v1\nkind: Cluster\nmetadata: {name: postgres}\nspec: {}\n")})
    values = {"env": {"DB_HOSTNAME": "postgres-${APP}-rw.database.svc"}}
    db = survey.resolve_db(values, mat, "photos", "k/media/photos", {"APP": "immich"})
    assert db["cluster"] == "postgres-immich"
    assert db["match"] == "host-match"


def test_a_failed_facts_row_still_renders(tmp_path, capsys):
    rows = [survey.unknown_facts("a/one", ["k/immich/app/helmrelease.yaml"], "facts failed: x")]
    survey.report_facts(rows, "immich")
    out = tmp_path / "survey.md"
    survey.write_markdown(str(out), rows, [], {}, "immich", ["--app", "immich", "--facts"])
    text = out.read_text()
    assert "unresolved 1/1" in text
    assert "unknown 1/1" in text and "no 1/1" not in text
    assert "N=1 repos" in capsys.readouterr().out
