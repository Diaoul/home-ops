#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["pyyaml"]
# ///
"""Survey how homelab GitOps repos configure one app's HelmRelease values.

kubesearch.dev-style: discover repos that actually run an app, read that app's
HelmRelease, flatten spec.values into dotted key paths, count how often each
key -> value pair appears, and (with --facts) derive the topology facts that
live outside spec.values: Kustomization components, persistence types, the
CNPG cluster behind the app, HPA / scale-to-zero / ext-auth.

Two ways to get the repo set:

  --discover           app-first: enumerate the `kubesearch` topic, test each
                       candidate for the app's HelmRelease with the git trees
                       API (no clone), fetch only the matched blobs, stop once
                       --want repos run the app. This is the default answer to
                       "how do the N repos that run this app configure it".
  --repos FILE         legacy: one owner/name per line, shallow-cloned. Kept
                       because it is what earlier runs used; it does NOT fix
                       the denominator, so never report `repos_scanned` as N.

Usage:
  survey.py --app immich --discover --want 20 --facts
  survey.py --app immich --discover --want 20 --filter persistence --top 40
  survey.py --app immich --discover --offline --facts      # instant rerun
  survey.py --repos repos.txt --app radarr                 # legacy clone mode
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import posixpath
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

import yaml

YAML_SUFFIXES = (".yaml", ".yml")
CLONE_BASE = "https://github.com"
API_BASE = "https://api.github.com"
RAW_BASE = "https://raw.githubusercontent.com"
HELMRELEASE_NAMES = ("helmrelease.yaml", "helm-release.yml")
TOPIC = "topic:kubesearch"
# Chart libraries / templates: they publish charts, they do not run the app.
CHART_LIB_REPOS = {
    "bjw-s-labs/helm-charts",
    "bjw-s/helm-charts",
    "trueforge-org/truecharts",
    "onedr0p/cluster-template",
    "onedr0p/flux-cluster-template",
    "home-operations/containers",
}
DB_HOST_KEYS = (
    "DB_HOSTNAME", "DB_HOST", "DB_URL", "DATABASE_URL", "POSTGRES_HOST",
    "POSTGRES_HOSTNAME", "POSTGRES_URL", "PGHOST", "POSTGRESQL_HOST",
    "DB_CONNECTION_STRING", "DATABASE_HOST",
)
LOCAL_SC_HINTS = ("hostpath", "local", "topolvm", "node", "openebs-hostpath", "miroir-local")
NETWORK_SC_HINTS = ("nfs", "ceph", "longhorn", "democratic", "truenas", "synology", "smb", "zfs",
                    "network", "rook", "juicefs", "csi-driver-nfs")


# --------------------------------------------------------------------------- #
# github access
# --------------------------------------------------------------------------- #
class GitHubError(RuntimeError):
    pass


class RateLimited(GitHubError):
    pass


def github_token() -> str | None:
    for var in ("GITHUB_TOKEN", "GH_TOKEN", "GITHUB_PAT"):
        tok = os.environ.get(var)
        if tok and tok.strip():
            return tok.strip()
    gh = shutil.which("gh")
    if gh:
        proc = subprocess.run([gh, "auth", "token"], capture_output=True, text=True)
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip()
    return None


class GitHub:
    """Tiny cached GitHub client (REST + raw)."""

    def __init__(self, workdir: Path, offline: bool = False):
        self.workdir = workdir
        self.offline = offline
        self.token = github_token()
        self.core_left: int | None = None
        self.core_reset: int | None = None
        self.api_calls = 0
        self.git_calls = 0
        # ref the last tree listing belongs to: a commit sha when we listed via git,
        # the branch name when we listed via the API. raw.githubusercontent.com
        # accepts both, but not a blob sha.
        self.last_rev: str = ""

    # -- plumbing ---------------------------------------------------------- #
    def _cache_path(self, kind: str, name: str) -> Path:
        p = self.workdir / kind / name
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def _request(self, url: str, what: str) -> tuple[int, dict | list | None, dict]:
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "home-ops-survey"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = resp.read()
                self.api_calls += 1
                hdrs = dict(resp.headers)
                self.core_left = int(hdrs.get("x-ratelimit-remaining", -1))
                self.core_reset = int(hdrs.get("x-ratelimit-reset", 0) or 0)
                return resp.status, json.loads(body or b"null"), hdrs
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")[:300]
            self.api_calls += 1
            hdrs = dict(exc.headers or {})
            left = hdrs.get("x-ratelimit-remaining")
            if left is not None and str(left).isdigit():
                self.core_left = int(left)
            reset = hdrs.get("x-ratelimit-reset")
            if reset is not None and str(reset).isdigit():
                self.core_reset = int(reset)
            if exc.code in (403, 429) and ("rate limit" in body.lower() or left == "0"):
                raise RateLimited(f"{what}: GitHub rate limit hit ({body})") from exc
            raise GitHubError(f"{what}: HTTP {exc.code}: {body}") from exc

    def get_json(self, path: str, what: str, refresh: bool = False,
                 cache_key: str | None = None) -> dict | list:
        cache = self._cache_path("api", (cache_key or path).replace("/", "_") + ".json")
        if cache.exists() and not refresh:
            return json.loads(cache.read_text())
        if self.offline:
            raise GitHubError(f"{what}: no cached response and --offline is set")
        status, data, _ = self._request(f"{API_BASE}{path}", what)
        cache.write_text(json.dumps(data))
        return data

    # -- search ------------------------------------------------------------ #
    def search_repos(self, query: str, pages: int = 5, per_page: int = 100,
                     refresh: bool = False) -> list[dict]:
        items: list[dict] = []
        for page in range(1, pages + 1):
            qs = urllib.parse.urlencode({"q": query, "per_page": per_page, "page": page,
                                         "sort": "stars", "order": "desc"})
            cache_key = f"search_{query.replace(':', '-').replace('/', '-')}_p{page}"
            try:
                data = self.get_json(f"/search/repositories?{qs}", f"search {query} p{page}",
                                     refresh=refresh, cache_key=cache_key)
            except RateLimited as exc:
                # Search is the one call with no quota-free fallback: say so loudly.
                raise GitHubError(
                    "GitHub search API refused the topic crawl (403 / rate limited).\n"
                    "The search endpoint needs a token; unauthenticated crawls get throttled to a\n"
                    "shared 10/min bucket and answer 403. Export GITHUB_TOKEN (or `gh auth login`)\n"
                    "and rerun, or pass --candidates FILE with an owner/name list — the app-existence\n"
                    "test still runs, so the denominator stays app-first.\n"
                    f"  underlying: {exc}"
                ) from exc
            if not isinstance(data, dict):
                break
            batch = data.get("items") or []
            items.extend(batch)
            if len(batch) < per_page:
                break
        return items

    # -- tree listing ------------------------------------------------------ #
    def list_tree_api(self, slug: str, branch: str, refresh: bool = False) -> tuple[list[dict], bool]:
        data = self.get_json(f"/repos/{slug}/git/trees/{branch}?recursive=1",
                             f"tree {slug}", refresh=refresh,
                             cache_key=f"tree_{slug.replace('/', '__')}")
        if not isinstance(data, dict):
            raise GitHubError(f"tree {slug}: unexpected payload")
        entries = [{"path": e.get("path", ""), "sha": e.get("sha", ""), "type": e.get("type", "blob")}
                   for e in data.get("tree") or []]
        self.last_rev = branch
        return entries, bool(data.get("truncated"))

    def list_tree_git(self, slug: str, branch: str) -> tuple[list[dict], bool]:
        """Quota-free equivalent of the trees API: blob-less shallow clone.

        `--filter=blob:none --no-checkout` fetches commits+trees only (a few
        hundred KB) and `git ls-tree -r` prints exactly the same (path, blob
        sha) pairs the trees API returns. Used when the API quota is spent.
        """
        dest = self.workdir / "git" / slug.replace("/", "__")
        if not (dest / ".git").exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            url = f"{CLONE_BASE}/{slug}.git"
            # no --branch: HEAD is the default branch, whatever it is called
            proc = subprocess.run(
                ["git", "clone", "--filter=blob:none", "--no-checkout", "--depth", "1",
                 "--quiet", "--no-tags", url, str(dest)],
                capture_output=True, text=True, timeout=300,
            )
            if proc.returncode != 0:
                raise GitHubError(f"git list {slug}: {proc.stderr.strip()[:200]}")
        self.git_calls += 1
        proc = subprocess.run(["git", "-C", str(dest), "rev-parse", "HEAD"],
                              capture_output=True, text=True, timeout=60)
        self.last_rev = proc.stdout.strip() if proc.returncode == 0 else branch
        proc = subprocess.run(["git", "-C", str(dest), "ls-tree", "-r", "HEAD"],
                              capture_output=True, text=True, timeout=120)
        if proc.returncode != 0:
            raise GitHubError(f"git ls-tree {slug}: {proc.stderr.strip()[:200]}")
        entries = []
        for line in proc.stdout.splitlines():
            # "<mode> <type> <sha>\t<path>"
            meta, _, path = line.partition("\t")
            parts = meta.split()
            if len(parts) < 3:
                continue
            entries.append({"path": path, "sha": parts[2], "type": parts[1]})
        return entries, False

    def list_tree_walk(self, slug: str, branch: str) -> list[dict]:
        """Fallback for `truncated: true`: BFS the contents API (one call per dir)."""
        entries: list[dict] = []
        queue = [""]
        seen = 0
        while queue:
            d = queue.pop(0)
            path = f"/repos/{slug}/contents/{d}?ref={branch}"
            data = self.get_json(path, f"contents {slug}:{d or '/'}")
            if not isinstance(data, list):
                continue
            for item in data:
                seen += 1
                if seen > 20000:
                    return entries
                if item.get("type") == "dir":
                    queue.append(item["path"])
                elif item.get("type") == "file":
                    entries.append({"path": item["path"], "sha": item.get("sha", ""), "type": "blob"})
        return entries

    # -- blobs ------------------------------------------------------------- #
    def blob(self, slug: str, rev: str, path: str) -> str | None:
        cache = self.workdir / "blobs" / slug.replace("/", "__") / path
        if cache.exists():
            return cache.read_text(encoding="utf-8", errors="replace")
        if self.offline:
            return None
        refs = [rev] if rev else []
        refs += [r for r in ("HEAD",) if r not in refs]
        last_exc: Exception | None = None
        for ref in refs:
            url = f"{RAW_BASE}/{slug}/{ref}/{urllib.parse.quote(path)}"
            req = urllib.request.Request(url, headers={"User-Agent": "home-ops-survey"})
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    text = resp.read().decode("utf-8", "replace")
                break
            except (urllib.error.URLError, urllib.error.HTTPError) as exc:
                last_exc = exc
                continue
        else:
            print(f"  ! blob fetch failed {slug}:{path}: {last_exc}", file=sys.stderr)
            return None
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(text, encoding="utf-8")
        return text


# --------------------------------------------------------------------------- #
# repo material: one interface over "clone on disk" and "tree + blob cache"
# --------------------------------------------------------------------------- #
def _dedupe_anchors(text: str) -> str:
    """Rename repeated YAML anchors so PyYAML can parse files Kubernetes accepts.

    Some repos reuse `&probes` in several containers of one document. go-yaml
    tolerates it (the later definition wins); PyYAML raises ComposerError and
    the whole HelmRelease would be dropped. Rename the 2nd+ definition and the
    aliases that follow it, which is what the loader would have resolved.
    """
    current: dict[str, str] = {}
    seen: Counter = Counter()
    out: list[str] = []
    pos = 0
    for m in re.finditer(r"(?<![\w*&])([&*])([A-Za-z0-9_-]+)", text):
        out.append(text[pos:m.start()])
        sigil, name = m.group(1), m.group(2)
        if sigil == "&":
            seen[name] += 1
            new = name if seen[name] == 1 else f"{name}__dup{seen[name]}"
            current[name] = new
            out.append(f"&{new}")
        else:
            out.append(f"*{current.get(name, name)}")
        pos = m.end()
    out.append(text[pos:])
    return "".join(out)


def yaml_docs_of(text: str) -> list[dict]:
    docs: list[dict] = []
    for attempt in (text, _dedupe_anchors(text)):
        try:
            docs = [d for d in yaml.safe_load_all(attempt) if isinstance(d, dict)]
            return docs
        except yaml.YAMLError:
            docs = []
            continue
    return docs


class Material:
    def __init__(self, slug: str, paths: list[str] | None = None, root: Path | None = None,
                 shas: dict[str, str] | None = None, gh: GitHub | None = None,
                 branch: str = "", rev: str = ""):
        self.slug = slug
        self.paths = paths or []
        self.root = root
        self.shas = shas or {}
        self.gh = gh
        self.branch = branch
        self.rev = rev
        self._docs: dict[str, list[dict]] = {}

    def read(self, path: str) -> str | None:
        if self.root is not None:
            f = self.root / path
            try:
                return f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                return None
        if self.gh is None or path not in self.shas:
            return None
        return self.gh.blob(self.slug, self.rev, path)

    def yaml_docs(self, path: str) -> list[dict]:
        if path in self._docs:
            return self._docs[path]
        text = self.read(path)
        docs = yaml_docs_of(text) if text else []
        self._docs[path] = docs
        return docs

    def has(self, path: str) -> bool:
        if self.root is not None:
            return (self.root / path).is_file()
        return path in self.shas


# --------------------------------------------------------------------------- #
# flattening (unchanged behaviour — radarr/sonarr runs must reproduce)
# --------------------------------------------------------------------------- #
def is_named_list(value) -> bool:
    """True for k8s-shaped lists of {name: ..., value/path/...: ...}."""
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(i, dict) and "name" in i for i in value)
    )


def flatten(value, prefix: str = "", out: dict | None = None) -> dict:
    """Flatten to {dotted.path: scalar}."""
    if out is None:
        out = {}
    if isinstance(value, dict):
        for key, sub in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            flatten(sub, path, out)
    elif is_named_list(value):
        for item in value:
            name = str(item["name"])
            path = f"{prefix}.{name}" if prefix else name
            rest = {k: v for k, v in item.items() if k != "name"}
            if not rest:
                out[path] = True
            elif len(rest) == 1:
                flatten(next(iter(rest.values())), path, out)
            else:
                flatten(rest, path, out)
    elif isinstance(value, list):
        scalars = [v for v in value if not isinstance(v, (dict, list))]
        if scalars and len(scalars) == len(value):
            out[prefix] = ",".join(str(v) for v in scalars)
        elif value:
            out[prefix] = "<list>"
    else:
        out[prefix] = value
    return out


# --------------------------------------------------------------------------- #
# app matching
# --------------------------------------------------------------------------- #
def looks_like_app(doc: dict, app: str, path: str, chart: str | None) -> bool:
    if not isinstance(doc, dict) or doc.get("kind") != "HelmRelease":
        return False
    name = str((doc.get("metadata") or {}).get("name", "")).lower()
    if name != app:
        segments = path.strip("/").lower().split("/")
        owns_dir = len(segments) >= 2 and segments[-2] == app
        owns_app_dir = any(
            segments[i] == app
            and (segments[i + 1] == "app" or segments[i + 1].startswith("app-"))
            for i in range(len(segments) - 1)
        )
        if not (owns_dir or owns_app_dir):
            return False
    if chart:
        spec = doc.get("spec") or {}
        chart_name = ""
        ref = spec.get("chartRef") or {}
        if isinstance(ref, dict):
            chart_name = str(ref.get("name", ""))
        chart_spec = (spec.get("chart") or {}).get("spec") or {}
        chart_name += " " + str(chart_spec.get("chart", ""))
        if chart.lower() not in chart_name.lower():
            return False
    return True


def app_helmrelease_paths(paths: list[str], app: str) -> tuple[list[str], bool]:
    """(paths whose tree contains the app's HelmRelease, whether the app dir exists).

    Directory rule, same as the crawler: a path segment equal to the app name,
    basename helmrelease.yaml / helm-release.yml, charts/**/templates excluded.
    """
    hits: list[str] = []
    app_seen = False
    for p in paths:
        low = p.lower()
        if "/charts/" in f"/{low}" and "/templates/" in f"/{low}":
            continue
        segments = low.split("/")
        if app not in segments:
            continue
        app_seen = True
        if segments[-1] in HELMRELEASE_NAMES:
            hits.append(p)
    return hits, app_seen


# --------------------------------------------------------------------------- #
# discovery
# --------------------------------------------------------------------------- #
def discover(args, gh: GitHub) -> tuple[list[dict], list[dict], list[dict], int]:
    """Return (matched candidates, skipped, search items, candidates examined)."""
    app = args.app.lower()
    candidates: list[dict] = []

    if args.candidates:
        lines = Path(args.candidates).read_text().splitlines()
        for line in lines:
            line = line.split("#", 1)[0].strip()
            if not line or "/" not in line:
                continue
            slug = line.split()[0]
            candidates.append({"full_name": slug, "default_branch": "main",
                               "fork": False, "archived": False, "stargazers_count": None,
                               "source": "candidates-file"})
    else:
        items = gh.search_repos(TOPIC, pages=args.search_pages, refresh=args.refresh)
        for it in items:
            candidates.append({
                "full_name": it.get("full_name", ""),
                "default_branch": it.get("default_branch") or "main",
                "fork": bool(it.get("fork")),
                "archived": bool(it.get("archived")),
                "stargazers_count": it.get("stargazers_count"),
                "source": "topic-search",
            })

    # de-dupe, keep star order
    seen: set[str] = set()
    uniq: list[dict] = []
    for c in candidates:
        slug = (c["full_name"] or "").lower()
        if not slug or slug in seen:
            continue
        seen.add(slug)
        uniq.append(c)
    candidates = uniq[: args.max_candidates]

    matched: list[dict] = []
    skipped: list[dict] = []
    examined = 0
    for idx, cand in enumerate(candidates, 1):
        # Before the pre-filters, so nothing past the last match lands in `skipped`:
        # matched + skipped is then every candidate the run looked at.
        if len(matched) >= args.want:
            break
        slug = cand["full_name"]
        low = slug.lower()
        if cand["fork"]:
            skipped.append({"repo": slug, "reason": "fork"})
            continue
        if cand["archived"]:
            skipped.append({"repo": slug, "reason": "archived"})
            continue
        if low in CHART_LIB_REPOS or re.search(r"(^|/)(helm-)?charts?$", low) \
                or low.endswith("cluster-template"):
            skipped.append({"repo": slug, "reason": "chart-library"})
            continue
        examined += 1

        branch = cand["default_branch"] or "main"
        entries: list[dict] = []
        truncated = False
        try:
            entries, truncated = gh.list_tree_api(slug, branch, refresh=args.refresh)
        except GitHubError as exc:
            # Any API failure (quota, 404 on a guessed branch, outage) falls back to
            # the quota-free blob-less git listing, which uses the real default branch.
            if args.listing == "api":
                print(f"  ~ api tree failed for {slug} ({str(exc)[:80]}); "
                      f"using git listing", file=sys.stderr)
            try:
                entries, truncated = gh.list_tree_git(slug, branch)
            except GitHubError as exc2:
                skipped.append({"repo": slug, "reason": "error", "detail": str(exc2)[:120]})
                continue

        if truncated:
            try:
                entries = gh.list_tree_walk(slug, branch)
            except GitHubError as exc:
                skipped.append({"repo": slug, "reason": "truncated-tree", "detail": str(exc)[:120]})
                continue

        paths = [e["path"] for e in entries if e.get("type") in ("blob", "")]
        shas = {e["path"]: e["sha"] for e in entries if e.get("type") in ("blob", "")}
        hits, app_seen = app_helmrelease_paths(paths, app)
        if not app_seen:
            skipped.append({"repo": slug, "reason": "no-app"})
            continue
        if not hits:
            skipped.append({"repo": slug, "reason": "no-helmrelease"})
            continue

        matched.append({**cand, "branch": branch, "rev": gh.last_rev or branch,
                        "paths": paths, "shas": shas,
                        "helmrelease_paths": hits, "scanned_at": idx})
        print(f"  + [{len(matched)}/{args.want}] {slug}  ({'; '.join(hits[:3])})", file=sys.stderr)

    if len(matched) < args.want:
        print(f"  ! only {len(matched)} repos with app={app!r} found among "
              f"{len(candidates)} candidates (wanted {args.want})", file=sys.stderr)
    return matched, skipped, candidates, examined


# --------------------------------------------------------------------------- #
# facts
# --------------------------------------------------------------------------- #
def _get(d, *keys, default=None):
    cur = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
        if cur is None:
            return default
    return cur


def app_root_of(path: str, app: str) -> str:
    segments = path.split("/")
    idx = None
    for i, seg in enumerate(segments[:-1]):
        if seg.lower() == app:
            idx = i
    if idx is None:
        return posixpath.dirname(path)
    return "/".join(segments[: idx + 1])


def collect_components(mat: Material, ks_paths: list[str], app_root: str) -> dict:
    """spec.components (basenames) + dependsOn + sub-dirs of the app root."""
    components: list[str] = []
    depends: list[str] = []
    dirs: list[str] = []
    substitutes: dict[str, str] = {}
    for ks in ks_paths:
        for doc in mat.yaml_docs(ks):
            if doc.get("kind") != "Kustomization":
                continue
            spec = doc.get("spec") or {}
            for comp in spec.get("components") or []:
                if isinstance(comp, str):
                    components.append(posixpath.basename(comp.rstrip("/")))
            for dep in spec.get("dependsOn") or []:
                if isinstance(dep, dict) and dep.get("name"):
                    depends.append(str(dep["name"]))
                elif isinstance(dep, str):
                    depends.append(dep)
            path = str(spec.get("path") or "")
            if path:
                norm = posixpath.normpath(posixpath.join(posixpath.dirname(ks), path))
                if norm.startswith(app_root + "/"):
                    dirs.append(posixpath.basename(norm))
            subs = _get(spec, "postBuild", "substitute") or {}
            if isinstance(subs, dict):
                for k, v in subs.items():
                    substitutes[str(k)] = "" if v is None else str(v)
    return {
        "components": sorted(set(components)),
        "depends_on": sorted(set(depends)),
        "dirs": sorted(set(dirs)),
        "substitutes": substitutes,
    }


def render(value, substitutes: dict[str, str]) -> str:
    """Best-effort substitution of ks postBuild vars into a Cluster CR string.

    Flux's default syntax is honoured: `${VAR:=fallback}` / `${VAR:-fallback}`
    resolve to the fallback when VAR is not among the substitutes, which is
    usually what the cluster ends up using.
    """
    text = str(value)
    for k, v in substitutes.items():
        text = re.sub(r"\$\{" + re.escape(k) + r":?[=-][^}]*\}", str(v), text)
        text = text.replace("${" + k + "}", str(v)).replace("$" + k, str(v))

    def defaulted(m):
        var, val = m.group(1), m.group(3)
        return substitutes.get(var, val)

    text = re.sub(r"\$\{([A-Za-z0-9_]+):([=-])([^}]*)\}", defaulted, text)
    return text


def walk_env(values) -> list[tuple[str, object]]:
    """Every (KEY, VALUE-object) pair in any `env:` map/list anywhere in values."""
    found: list[tuple[str, object]] = []

    def visit(node):
        if isinstance(node, dict):
            for key, sub in node.items():
                if key == "env":
                    if isinstance(sub, dict):
                        for k, v in sub.items():
                            found.append((str(k), v))
                    elif isinstance(sub, list):
                        for item in sub:
                            if isinstance(item, dict) and item.get("name"):
                                val = item.get("value")
                                if val is None and item.get("valueFrom"):
                                    val = {"valueFrom": item["valueFrom"]}
                                found.append((str(item["name"]), val))
                visit(sub)
        elif isinstance(node, list):
            for item in node:
                visit(item)

    visit(values)
    return found


def service_of(raw) -> tuple[str, str]:
    """(service-name-ish, source) from a DB host/url/env value."""
    if isinstance(raw, dict):
        ref = raw.get("valueFrom", raw)
        name = _get(ref, "secretKeyRef", "name") or _get(ref, "configMapKeyRef", "name") or "?"
        return f"unresolved:{name}", "secret-ref"
    text = str(raw or "").strip().strip("'\"")
    if not text:
        return "", "none"
    text = text.replace("{{ .Release.Name }}", "").replace("{{.Release.Name}}", "")
    if "://" in text:
        text = text.split("://", 1)[1]
        text = text.split("@")[-1]
        text = text.split("/")[0]
    text = text.split("?")[0].strip().strip("'\"")
    if ":" in text:
        text = text.split(":")[0]
    first = text.split(".")[0]
    if "${" in first or "{{" in first:
        return first, "template"
    return first, "literal"


def cluster_candidates(mat: Material, app_root: str) -> list[dict]:
    """CNPG `Cluster` CRs in the repo: parse the plausible yaml blobs."""
    out: list[dict] = []
    for path in mat.paths:
        low = path.lower()
        if not low.endswith(YAML_SUFFIXES):
            continue
        # disabled/old manifests are not deployed: ignore archive trees
        if low.startswith(".archive/") or "/.archive/" in f"/{low}" or "/archive/" in f"/{low}":
            continue
        if "/charts/" in f"/{low}" and "/templates/" in f"/{low}":
            continue
        base = posixpath.basename(low)
        if not (base.startswith("cluster") or base in ("postgres.yaml", "postgresql.yaml",
                                                       "database.yaml", "db.yaml", "pg.yaml")
                or "/database/" in f"/{low}" or "/db/" in f"/{low}"
                or "/patches/" in f"/{low}" or "/cnpg/" in f"/{low}" or "/postgres/" in f"/{low}"):
            continue
        for doc in mat.yaml_docs(path):
            if doc.get("kind") != "Cluster":
                continue
            if "cnpg.io" not in str(doc.get("apiVersion", "")):
                continue
            if not (doc.get("metadata") or {}).get("name"):
                continue  # a patch fragment we cannot identify
            out.append({"path": path, "doc": doc})
    return out


def with_app_vars(subs: dict, app: str) -> dict:
    """Flux vars every repo that uses them sets to the app: APP / APP_NAME."""
    out = dict(subs)
    for var in ("APP", "APP_NAME", "APPNAME"):
        if var not in out:
            out[var] = app
    return out


def find_persistence(values: dict) -> dict:
    """Locate the persistence map: top-level (app-template) or nested (upstream charts).

    Charts carry it as `values.persistence` (app-template) or deeper, e.g. the
    immich chart's `values.immich.persistence`. Take the shallowest map whose
    values look like persistence entries.
    """
    def looks_like(entries) -> bool:
        if not isinstance(entries, dict) or not entries:
            return False
        keys = {"type", "existingClaim", "globalMounts", "advancedMounts", "storageClass",
                "nfs", "hostPath", "size", "server", "path", "accessMode"}
        return any(isinstance(v, dict) and (keys & set(v)) for v in entries.values())

    candidates: list[tuple[int, int, dict]] = []

    def walk(node, depth):
        if isinstance(node, dict):
            for key, sub in node.items():
                if key == "persistence" and looks_like(sub):
                    candidates.append((depth, -len(sub), sub))
                walk(sub, depth + 1)
        elif isinstance(node, list):
            for item in node:
                walk(item, depth + 1)

    walk(values, 0)
    if not candidates:
        return {}
    candidates.sort(key=lambda c: (c[0], c[1]))
    return candidates[0][2]


def persistence_of(values: dict) -> dict[str, dict]:
    """`persistence.<name>` entries, from app-template values or a chart's nested block."""
    entries = find_persistence(values)
    if not isinstance(entries, dict):
        return {}
    out: dict[str, dict] = {}
    for name, spec in entries.items():
        if not isinstance(spec, dict):
            continue
        typ = spec.get("type")
        if not typ:
            if spec.get("existingClaim"):
                typ = "existingClaim"
            elif spec.get("nfs"):
                typ = "nfs"
            elif spec.get("hostPath"):
                typ = "hostPath"
            else:
                typ = "persistentVolumeClaim"
        mounts: list[str] = []
        for m in spec.get("globalMounts") or []:
            if isinstance(m, dict) and m.get("path"):
                mounts.append(str(m["path"]))
        adv = spec.get("advancedMounts") or {}
        if isinstance(adv, dict):
            for ctrl, containers in adv.items():
                if not isinstance(containers, dict):
                    continue
                for cname, mlist in containers.items():
                    for m in mlist or []:
                        if isinstance(m, dict) and m.get("path"):
                            mounts.append(f"{ctrl}/{cname}:{m['path']}")
        out[str(name)] = {
            "type": str(typ),
            "storage_class": spec.get("storageClass") or "",
            "size": str(spec.get("size") or ""),
            "server": str(spec.get("server") or ""),
            "path": str(spec.get("path") or ""),
            "claim": str(spec.get("existingClaim") or ""),
            "mounts": mounts,
        }
    return out


def storage_class_kind(sc: str) -> str:
    if not sc:
        return "unknown"
    low = sc.lower()
    if any(h in low for h in LOCAL_SC_HINTS):
        return "node-local"
    if any(h in low for h in NETWORK_SC_HINTS):
        return "network"
    return "unknown"


NAS_SC_HINTS = ("nfs", "smb", "cifs", "synology", "truenas", "freenas", "democratic", "qnap",
                "unraid", "nas")
PV_SCAN_LIMIT = 60


def store_kind(sc: str) -> str:
    """Where a storage class keeps data: nas, network (replicated block), node-local, unknown."""
    low = sc.lower()
    if any(h in low for h in NAS_SC_HINTS):
        return "nas"
    return storage_class_kind(sc)


def _pv_store(pv: dict) -> str:
    spec = pv.get("spec") or {}
    if spec.get("nfs"):
        return "nas"
    # Pinned to a node, whatever the driver (OpenEBS ZFS/LVM LocalPV, local-path).
    if _get(spec, "nodeAffinity", "required"):
        return "node-local"
    driver = str(_get(spec, "csi", "driver") or "").lower()
    if driver:
        return "nas" if any(h in driver for h in NAS_SC_HINTS) else store_kind(driver)
    if spec.get("local") or spec.get("hostPath"):
        return "node-local"
    sc = str(spec.get("storageClassName") or "")
    return store_kind(sc) if sc else "unknown"


def _volume_manifests(mat: Material, app_root: str, component_dirs: list[str]) -> list[str]:
    """YAML that can declare the library's PVC/PV: the app tree, its components, and
    volume-looking files anywhere else (a namespace-level `nfs-pv.yaml`)."""
    dirs = [app_root] + component_dirs
    near = [p for p in mat.paths if p.endswith(YAML_SUFFIXES)
            and any(p.startswith(d + "/") for d in dirs)]
    named = [p for p in mat.paths if p.endswith(YAML_SUFFIXES) and p not in near
             and re.search(r"(^|[/_.-])(pvc|pv|volumes?|storage|nfs|claims?)([/_.-]|$)",
                           p.lower())
             and "/charts/" not in p]
    return near + named[:PV_SCAN_LIMIT]


def library_store(mat: Material, library: dict, app_root: str, component_dirs: list[str],
                  subs: dict, release_name: str) -> dict:
    """Where the library's data lives, as opposed to how it is mounted.

    `via` names the evidence, weakest last: the mount type, a storage class, a PVC or PV
    found in git, or only the claim's name.
    """
    if not library:
        return {"store": "none", "via": "no library entry"}
    typ = library.get("type") or ""
    if typ == "nfs":
        return {"store": "nas", "via": f"nfs mount {library.get('server') or ''}".strip()}
    if typ == "hostPath":
        return {"store": "node-local", "via": "hostPath"}
    if typ == "emptyDir":
        return {"store": "ephemeral", "via": "emptyDir"}
    sc = render(library.get("storage_class") or "", subs)
    if sc:
        return {"store": store_kind(sc), "via": f"storageClass {sc}"}
    if typ != "existingClaim":
        return {"store": "unknown", "via": f"{typ} with the cluster's default class"}

    claim = render(library.get("claim") or "", subs)
    claim = re.sub(r"\{\{-?\s*\.Release\.Name\s*-?\}\}", release_name, claim)
    pvs: dict[str, dict] = {}
    pvc = None
    for path in _volume_manifests(mat, app_root, component_dirs):
        for doc in mat.yaml_docs(path):
            kind = doc.get("kind")
            name = render(_get(doc, "metadata", "name") or "", subs)
            if kind == "PersistentVolume":
                pvs[name] = doc
            elif kind == "PersistentVolumeClaim" and name == claim and pvc is None:
                pvc = (path, doc)
    if pvc:
        path, doc = pvc
        spec = doc.get("spec") or {}
        sc = render(spec.get("storageClassName") or "", subs)
        volume = render(spec.get("volumeName") or "", subs)
        if volume and volume not in pvs:
            # The PV can live anywhere; look in files whose path names it.
            tokens = [t for t in re.split(r"[-_.]", volume.lower()) if len(t) >= 3]
            hinted = [p for p in mat.paths if p.endswith(YAML_SUFFIXES) and "/charts/" not in p
                      and (volume.lower() in p.lower()
                           or sum(t in p.lower() for t in tokens) >= 2)]
            for p in hinted[:PV_SCAN_LIMIT]:
                for d in mat.yaml_docs(p):
                    if d.get("kind") == "PersistentVolume":
                        pvs[render(_get(d, "metadata", "name") or "", subs)] = d
        if volume in pvs:
            return {"store": _pv_store(pvs[volume]), "via": f"PV {volume}"}
        bound = [pv for pv in pvs.values()
                 if render(_get(pv, "spec", "claimRef", "name") or "", subs) == claim]
        if bound:
            return {"store": _pv_store(bound[0]), "via": f"PV bound to {claim}"}
        # Static provisioning: a PVC and a PV sharing a non-provisioner class bind
        # to each other (`manual`, or the empty class).
        static = [pv for pv in pvs.values()
                  if render(_get(pv, "spec", "storageClassName") or "", subs) == sc]
        if len(static) == 1:
            return {"store": _pv_store(static[0]),
                    "via": f"PV sharing storageClass {sc or '\"\"'} with PVC {claim}"}
        if sc:
            return {"store": store_kind(sc), "via": f"PVC {claim} storageClass {sc} ({path})"}
        return {"store": "unknown", "via": f"PVC {claim} with the cluster's default class ({path})"}
    if re.search(r"(^|[-_])(nfs|nas)([-_]|$)", claim.lower()):
        return {"store": "nas", "via": f"claim name {claim} only, no PVC in git"}
    return {"store": "unknown", "via": f"claim {claim} not declared in git"}


def ext_names(spec: dict) -> list[str]:
    names: list[str] = []
    pg = spec.get("postgresql") or {}
    for ext in pg.get("extensions") or []:
        if isinstance(ext, dict) and ext.get("name"):
            names.append(str(ext["name"]))
        elif isinstance(ext, str):
            names.append(ext)
    for lib in pg.get("shared_preload_libraries") or []:
        names.append(str(lib).replace(".so", ""))
    return sorted(set(n for n in names if n))


def hpa_paths(mat: Material, app_root: str, component_dirs: list[str]) -> list[str]:
    out: list[str] = []
    for path in mat.paths:
        low = path.lower()
        if not (low.startswith(app_root + "/") or any(low.startswith(c + "/") for c in component_dirs)):
            continue
        if not low.endswith(YAML_SUFFIXES):
            continue
        base = posixpath.basename(low)
        if "horizontalpodautoscaler" in base or base in ("hpa.yaml", "hpa.yml"):
            out.append(path)
            continue
        if "hpa" not in base and "auto" not in low:
            continue
        for doc in mat.yaml_docs(path):
            if doc.get("kind") == "HorizontalPodAutoscaler":
                out.append(path)
                break
    return out


def resolve_db(values: dict, mat: Material, app: str, app_root: str, subs: dict) -> dict:
    """Which Postgres the app talks to, and what that cluster is.

    Order of evidence: a literal host in DB_*/POSTGRES_* env, then the secret
    name a `valueFrom` points at (a CNPG cluster's `<name>-rw`/`<name>-pguser-*
    secrets name it), then envFrom secretRefs (unresolved unless the name
    identifies a cluster), then a Cluster CR in the app's own directory, then
    one named after the app, then the repo's only cluster.
    """
    env_hits = [(k, v) for k, v in walk_env(values) if k in DB_HOST_KEYS]
    host_raw = next((v for k, v in env_hits
                     if k in ("DB_HOSTNAME", "DB_HOST", "POSTGRES_HOST",
                              "POSTGRES_HOSTNAME", "PGHOST")), None)
    if host_raw is None:
        host_raw = next((v for k, v in env_hits
                         if k in ("DB_URL", "DATABASE_URL", "POSTGRES_URL",
                                  "DB_CONNECTION_STRING", "DATABASE_HOST")), None)
    service, source = service_of(host_raw) if host_raw is not None else ("", "none")
    if source == "none":
        refs = [v.get("secretRef", {}).get("name") for v in _env_from_secret_refs(values)]
        refs = [r for r in refs if r]
        if refs:
            service = f"unresolved:{refs[0]}"
            source = "envFrom-secret"

    clusters = cluster_candidates(mat, app_root)
    chosen, db_match = None, ""

    def name_of(c):
        return render(str((c["doc"].get("metadata") or {}).get("name", "")), subs)

    # 1. a host/service name, literal or recovered from a secret name
    tokens = []
    if service and source in ("literal", "template"):
        bare = service
        for prefix in ("pooler-", "pooler."):
            if bare.startswith(prefix):
                bare = bare[len(prefix):]
        tokens.extend([bare, re.sub(r"-(rw|ro|pooler|primary|replica)$", "", bare)])
    if source in ("secret-ref", "envFrom-secret"):
        secret = service.split(":", 1)[-1]
        tokens.extend([t for t in re.split(r"[._-]", secret) if t and t not in (
            "pguser", "secret", "svc", "cluster", "postgres", "pg", "db", "rw", "user",
            "host", "app")])
        tokens.append(re.sub(r"-(pguser|pg|secret|host).*$", "", secret))
    def pick(cands: list[dict]) -> dict | None:
        """Prefer the app's own directory, then the most specific CR, then shortest path."""
        if not cands:
            return None
        return sorted(cands, key=lambda c: (
            0 if c["path"].startswith(app_root + "/") else 1,
            0 if (c["doc"].get("spec") or {}).get("imageName") else 1,
            0 if (c["doc"].get("spec") or {}).get("postgresql") else 1,
            len(c["path"]),
        ))[0]

    for tok in tokens:
        if not tok:
            continue
        hits = [c for c in clusters
                if tok == name_of(c) or tok == f"{name_of(c)}-rw"
                or (len(tok) > 3 and tok in name_of(c))]
        if hits:
            chosen = pick(hits)
            db_match = "host-match" if source == "literal" else "secret-name"
            break

    # 2. a Cluster CR living in the app's own directory, then one named after it
    if chosen is None:
        chosen = pick([c for c in clusters
                       if app in name_of(c).lower() and c["path"].startswith(app_root + "/")])
        if chosen:
            db_match = "app-dir"
    if chosen is None:
        chosen = pick([c for c in clusters if app in name_of(c).lower()])
        if chosen:
            db_match = "app-name"
    if chosen is None:
        # `postgresVector: "true"` on the controller is the app declaring it wants a
        # vector-capable cluster; take it when the repo has exactly one.
        wants_vector = any(
            str(k).lower() in ("postgresvector", "postgres_vector") and str(v).lower() == "true"
            for k, v in _iter_labels(values)
        )
        if wants_vector:
            vecs = [c for c in clusters if _is_vector_cluster(c, subs)]
            if len(vecs) == 1:
                chosen, db_match = vecs[0], "vector-label"
    if chosen is None and len(clusters) == 1:
        chosen, db_match = clusters[0], "single-cluster"

    db: dict = {"service": service, "source": source, "cluster": "",
                "match": db_match or "none", "other_operator": ""}
    if chosen:
        cspec = chosen["doc"].get("spec") or {}
        name = render(name_of(chosen), subs)
        image = render(cspec.get("imageName") or "", subs)
        pg = cspec.get("postgresql") or {}
        exts = [e.replace(".so", "") for e in ext_names(cspec)]
        ext_images: list[str] = []
        for ext in pg.get("extensions") or []:
            if not isinstance(ext, dict):
                continue
            ref = (_get(ext, "image", "reference")
                   or _get(ext, "image", "volume", "name")
                   or _get(ext, "image", "volume", "reference"))
            if ref:
                ext_images.append(render(ref, subs))
        preload = [render(x, subs).replace(".so", "")
                   for x in (pg.get("shared_preload_libraries") or [])]
        # Per-app extensions live on the app's `Database` CR when the cluster is shared.
        app_exts: list[str] = []
        for path in mat.paths:
            if not path.lower().endswith(YAML_SUFFIXES):
                continue
            if not path.startswith(app_root + "/"):
                continue
            for d in mat.yaml_docs(path):
                if d.get("kind") == "Database" and "cnpg.io" in str(d.get("apiVersion", "")):
                    ref = _get(d, "spec", "cluster", "name") or ""
                    if ref and ref != name:
                        continue
                    for ext in _get(d, "spec", "extensions") or []:
                        if isinstance(ext, dict) and ext.get("name"):
                            app_exts.append(render(ext["name"], subs))
                        elif isinstance(ext, str):
                            app_exts.append(render(ext, subs))
        if not app_exts and "${DATABASE_EXTENSIONS" in str(pg.get("extensions")):
            app_exts = re.findall(r"name:\s*([a-z0-9_]+)", subs.get("DATABASE_EXTENSIONS", ""))
        storage = cspec.get("storage") or {}
        short = re.sub(r"@sha256:.*$", "", image).split("/")[-1] if image else ""
        if "$" in short or "{{" in short:
            short = short.split(":")[0] + ":<unresolved-substitution>"
        db.update({
            "cluster": name,
            "image": image,
            "image_short": short,
            "extensions": sorted(set(exts + app_exts)),
            "ext_images": sorted(set(ext_images)),
            "preload": sorted(set(preload)),
            "storage_class": render(storage.get("storageClass") or "", subs),
            "storage_size": render(storage.get("size") or "", subs),
            "instances": cspec.get("instances"),
            "dedicated": app in name.lower() or chosen["path"].startswith(app_root + "/"),
            "path": chosen["path"],
            "substituted": any("${" in str(v) for v in [cspec.get("imageName") or ""]),
        })
        vectorish = db["extensions"] + db["preload"]
        db["vector_capable"] = any("vchord" in x or "vector" in x for x in vectorish) \
            or "vector" in (db.get("image") or "").lower()
        if db["vector_capable"] and db["dedicated"]:
            db["class"] = "vector-dedicated"
        elif db["vector_capable"]:
            db["class"] = "vector-shared"
        elif db["dedicated"]:
            db["class"] = "general-dedicated"
        else:
            db["class"] = "general-shared"
        return db

    # No CNPG Cluster: is it a different Postgres operator (crunchy, zalando, …)?
    for path in mat.paths:
        if not path.lower().endswith(YAML_SUFFIXES) or not path.startswith(app_root + "/"):
            continue
        for d in mat.yaml_docs(path):
            kind = str(d.get("kind") or "")
            api = str(d.get("apiVersion") or "")
            if kind in ("PostgresCluster", "PostgresqlCluster", "Postgres") or \
                    "crunchy" in api or "zalando" in api or "percona" in api:
                db["other_operator"] = kind
                db["class"] = "other-operator"
                return db

    if db.get("class"):
        return db
    db["class"] = "unresolved" if source in ("secret-ref", "envFrom-secret", "template") else "none"
    return db


def _iter_labels(values):
    def visit(node):
        if isinstance(node, dict):
            for key, sub in node.items():
                if key in ("labels", "annotations") and isinstance(sub, dict):
                    for k, v in sub.items():
                        yield str(k), v
                yield from visit(sub)
        elif isinstance(node, list):
            for item in node:
                yield from visit(item)

    return visit(values)


def _is_vector_cluster(c: dict, subs: dict) -> bool:
    spec = c["doc"].get("spec") or {}
    image = render(spec.get("imageName") or "", subs).lower()
    if "vector" in image or "vchord" in image:
        return True
    return any("vchord" in x or "vector" in x for x in ext_names(spec))


def _env_from_secret_refs(values) -> list[dict]:
    found: list[dict] = []

    def visit(node):
        if isinstance(node, dict):
            for key, sub in node.items():
                if key == "envFrom" and isinstance(sub, list):
                    for item in sub:
                        if isinstance(item, dict) and "secretRef" in item:
                            found.append(item)
                visit(sub)
        elif isinstance(node, list):
            for item in node:
                visit(item)

    visit(values)
    return found


def facts_for(mat: Material, app: str, release_paths: list[str]) -> dict:
    app_root = app_root_of(release_paths[0], app)
    release_path = release_paths[0]
    releases = [d for d in mat.yaml_docs(release_path)
                if d.get("kind") == "HelmRelease" and looks_like_app(d, app, release_path, None)]
    doc = releases[0] if releases else {}
    values = _get(doc, "spec", "values") or {}
    if not isinstance(values, dict):
        values = {}

    # The Kustomization that points at the app: usually ks.yaml, sometimes a
    # hand-written flux-kustomization.yml next to the release.
    ks_paths = [p for p in (f"{app_root}/ks.yaml", f"{app_root}/ks.yml",
                            f"{app_root}/kustomization.yaml", f"{app_root}/kustomization.yml",
                            f"{app_root}/flux-kustomization.yml", f"{app_root}/flux-kustomization.yaml",
                            posixpath.dirname(app_root) + "/ks.yaml") if mat.has(p)]
    ks_paths = [p for p in ks_paths
                if any(d.get("kind") == "Kustomization" for d in mat.yaml_docs(p))]
    comp = collect_components(mat, ks_paths, app_root)
    subs = with_app_vars(comp["substitutes"], app)
    component_dirs = []
    for ks in ks_paths:
        for d in mat.yaml_docs(ks):
            spec = d.get("spec") or {}
            # flux resolves spec.components relative to spec.path (repo-root relative),
            # not to the ks.yaml's own directory.
            base = app_root
            sp = str(spec.get("path") or "")
            if sp:
                norm = posixpath.normpath(sp)
                base = "" if norm == "." else norm
            for c in spec.get("components") or []:
                if isinstance(c, str):
                    component_dirs.append(posixpath.normpath(posixpath.join(base, c)))
    # kustomize `components:` declared in the app dir's own kustomization.yaml
    kust_comps: list[str] = []
    for kust in (f"{app_root}/kustomization.yaml", f"{app_root}/kustomization.yml"):
        if not mat.has(kust):
            continue
        for d in mat.yaml_docs(kust):
            for c in d.get("components") or []:
                if isinstance(c, str):
                    component_dirs.append(posixpath.normpath(
                        posixpath.join(app_root, c)))
                    kust_comps.append(posixpath.basename(c.rstrip("/")))
    if kust_comps:
        comp["components"] = sorted(set(comp["components"] + kust_comps))
    # keep only component dirs that actually exist in the tree
    known = set(mat.paths)
    component_dirs = [d for d in dict.fromkeys(component_dirs)
                      if d and any(p == d or p.startswith(d + "/") for p in known)]

    persistence = persistence_of(values)

    # --- database -------------------------------------------------------- #
    db = resolve_db(values, mat, app, app_root, subs)

    if "vchord-scratch" in (db.get("image") or ""):
        db["image_kind"] = "vchord-scratch"
    elif "cloudnative-vectorchord" in (db.get("image") or ""):
        db["image_kind"] = "cloudnative-vectorchord"
    elif "cloudnative-pg/postgresql" in (db.get("image") or ""):
        db["image_kind"] = "cloudnative-pg-postgresql"
    elif db.get("image"):
        db["image_kind"] = "other"
    else:
        db["image_kind"] = "none"
    db["sc_kind"] = storage_class_kind(db.get("storage_class") or "")

    # where the vchord library comes from: an extension image volume (CNPG >= 1.28,
    # ghcr.io/tensorchord/vchord-scratch) or baked into the cluster's base image
    # (ghcr.io/tensorchord/cloudnative-vectorchord).
    ext_images = db.get("ext_images") or []
    if any("vchord" in e.lower() for e in ext_images):
        db["vchord_source"] = "extension-image"
    elif "cloudnative-vectorchord" in (db.get("image") or ""):
        db["vchord_source"] = "base-image"
    elif db.get("cluster") and any("vchord" in x for x in (db.get("extensions") or [])):
        db["vchord_source"] = "other-base-image"
    else:
        db["vchord_source"] = "none"

    lib_name = ""
    for n, spec in persistence.items():
        mounts = " ".join(spec.get("mounts") or [])
        if any(p in mounts for p in ("/usr/src/app/upload", "/data", "/photos", "/library")):
            lib_name = n
            break
    if not lib_name:
        for keyword in ("library", "photos", "media", "upload", "images", "pictures", "storage"):
            lib_name = next((n for n in persistence if keyword in n.lower()), "")
            if lib_name:
                break
    library = {"name": lib_name, **persistence.get(lib_name, {})} if lib_name else {}
    release_name = str(_get(doc, "metadata", "name") or app)
    library.update(library_store(mat, library, app_root, component_dirs, subs, release_name))

    hpas = hpa_paths(mat, app_root, component_dirs)
    controllers = values.get("controllers") or {}
    comps = [c.lower() for c in comp["components"]]

    return {
        "repo": mat.slug,
        "app_root": app_root,
        "release_paths": release_paths,
        "ks_paths": ks_paths,
        "components": comp["components"],
        "components_extra": comp["dirs"],
        "depends_on": comp["depends_on"],
        "persistence": persistence,
        "library": library,
        "db": db,
        "hpa": bool(hpas),
        "hpa_paths": hpas,
        "zeroscaler": any("zeroscale" in c for c in comps),
        "ext_auth": any(("ext-auth" in c or "extauth" in c or "ext-auth" in d.lower())
                        for c in comps for d in [c]) or any(
                            "ext-auth" in d.lower() or "extauth" in d.lower()
                            for d in comp["components"] + comp["dirs"]),
        "postgres_controller": "postgres" in [str(k).lower() for k in (controllers or {})],
        "postgres_strategy": str(_get(doc, "spec", "strategy", "name") or ""),
    }


# --------------------------------------------------------------------------- #
# legacy clone mode
# --------------------------------------------------------------------------- #
def clone(repo: str, workdir: Path, refresh: bool = False) -> Path | None:
    dest = workdir / repo.replace("/", "__")
    if refresh and dest.exists():
        subprocess.run(["rm", "-rf", str(dest)], check=False)
    if dest.exists():
        return dest
    url = f"{CLONE_BASE}/{repo}.git"
    proc = subprocess.run(
        ["git", "clone", "--depth", "1", "--quiet", "--no-tags", url, str(dest)],
        capture_output=True, text=True, timeout=300,
    )
    if proc.returncode != 0:
        print(f"  ! clone failed for {repo}: {proc.stderr.strip()[:200]}", file=sys.stderr)
        return None
    return dest


def clone_material(repo: str, root: Path) -> Material:
    paths = []
    for p in root.rglob("*"):
        if p.is_file():
            rel = p.relative_to(root).as_posix()
            if "/charts/" in f"/{rel}" and "/templates/" in f"/{rel}":
                continue
            paths.append(rel)
    return Material(repo, paths=paths, root=root)


def iter_helmreleases(mat: Material):
    for path in mat.paths:
        if not path.lower().endswith(YAML_SUFFIXES):
            continue
        text = mat.read(path) or ""
        if "HelmRelease" not in text:
            continue
        for doc in mat.yaml_docs(path):
            if doc.get("kind") == "HelmRelease":
                yield path, doc


# --------------------------------------------------------------------------- #
# reporting
# --------------------------------------------------------------------------- #
def report_keys(agg, matched, app, chart, args):
    print(f"survey: app={app!r} chart={chart or '*'} repos_that_run_app={len(matched)}")
    for repo, relpath in matched:
        print(f"  - {repo}  {relpath}")
    print()

    filters = args.filter.lower().split(",") if args.filter else None
    keys = [
        key for key, vals in agg.items()
        if len({r for s in vals.values() for r in s}) >= args.min_repos
        and (not filters or any(f in key.lower() for f in filters))
    ]
    keys.sort(key=lambda k: (-len({r for s in agg[k].values() for r in s}), k))
    print(f"{len(keys)} of {len(agg)} keys shown, ordered by how many repos set them "
          f"(min-repos={args.min_repos}, filter={args.filter})\n")
    for key in keys:
        vals = agg[key]
        total = len({r for s in vals.values() for r in s})
        print(f"## {key}  ({total}/{len(matched)} repos)")
        for val, repo_set in sorted(vals.items(), key=lambda kv: (-len(kv[1]), kv[0]))[: args.top]:
            shown = val if len(val) <= 100 else val[:97] + "..."
            who = ",".join(sorted(r.split("/")[0] for r in repo_set))
            print(f"   {len(repo_set):>2}x  {shown!r}   [{who}]")
        print()


def _clip(text, width):
    text = "" if text is None else str(text)
    return text if len(text) <= width else text[: width - 1] + "…"


def _short_repo(slug: str) -> str:
    """`owner/repo`, with the `home-ops`-ish tail dropped when it is ambiguous-free."""
    owner, _, repo = slug.partition("/")
    return f"{owner}/{repo}"


def _db_label(db: dict) -> str:
    if db.get("cluster"):
        return db["cluster"] + (" (shared)" if db.get("dedicated") is False else "")
    if db.get("other_operator"):
        return f"{db['other_operator']} (non-CNPG)"
    if db.get("class") == "unresolved":
        src = db.get("source") or ""
        svc = (db.get("service") or "").split(":", 1)[-1]
        return f"unresolved ({src}:{svc})" if svc else f"unresolved ({src})"
    return "-"


def report_facts(rows: list[dict], app: str):
    n = len(rows)
    print(f"\nfacts: app={app!r}  N={n} repos (denominator = repos that run the app)\n")
    header = ["repo", "ks components", "library", "db cluster", "db image",
              "db ext", "db storage", "HPA", "zsc", "extauth", "pg ctrl"]
    table = []
    for r in rows:
        lib = r["library"]
        lib_s = f"{lib.get('name','-')}:{lib.get('type','-')}" if lib.get("name") else "none"
        if lib.get("storage_class"):
            lib_s += f"/{lib['storage_class']}"
        lib_s += f" -> {lib.get('store', 'none')}"
        db = r["db"]
        cls = _db_label(db)
        table.append([
            _short_repo(r["repo"]),
            ",".join(r["components"] + [d for d in r["components_extra"] if d not in r["components"]]) or "-",
            lib_s,
            cls,
            db.get("image_short") or "-",
            ",".join(db.get("extensions") or []) or "-",
            f"{db.get('storage_class') or '-'} {db.get('storage_size') or ''}".strip(),
            "y" if r["hpa"] else "-",
            "y" if r["zeroscaler"] else "-",
            "y" if r["ext_auth"] else "-",
            "y" if r["postgres_controller"] else "-",
        ])
    widths = [max(len(_clip(row[i], 40)) for row in [header] + table) for i in range(len(header))]
    fmt = " | ".join("{:<%d}" % w for w in widths)
    print(fmt.format(*header))
    print("-+-".join("-" * w for w in widths))
    for row in table:
        print(fmt.format(*[_clip(c, w) for c, w in zip(row, widths)]))

    print("\naggregate (n/N):")
    def tally(label, values):
        cnt = Counter(values)
        parts = ", ".join(f"{k} {v}/{n}" for k, v in sorted(cnt.items(), key=lambda kv: (-kv[1], kv[0])))
        print(f"  {label:<28} {parts}")

    tally("db cluster role", [r["db"].get("class", "none") for r in rows])
    tally("db image", [r["db"].get("image_kind", "none") for r in rows])
    tally("db storage class kind", [r["db"].get("sc_kind", "none") if r["db"].get("cluster") else "none"
                                    for r in rows])
    tally("db storage class", [(r["db"].get("storage_class") or "none") for r in rows])
    tally("library mount", [(r["library"].get("type") or "none") for r in rows])
    tally("library store", [(r["library"].get("store") or "none") for r in rows])
    tally("zeroscaler", ["present" if r["zeroscaler"] else "absent" for r in rows])
    tally("HPA", ["present" if r["hpa"] else "absent" for r in rows])
    tally("ext-auth", ["present" if r["ext_auth"] else "absent" for r in rows])
    tally("own postgres controller", ["yes" if r["postgres_controller"] else "no" for r in rows])
    tally("db extensions", [",".join(r["db"].get("extensions") or []) or "none" for r in rows])
    tally("db preload", [",".join(r["db"].get("preload") or []) or "none" for r in rows])
    vec = [r for r in rows if r["db"].get("vector_capable")]
    print(f"  {'vchord supplied by':<28} " + ", ".join(
        f"{k} {v}/{len(vec)}" for k, v in sorted(
            Counter(r["db"].get("vchord_source", "none") for r in vec).items(),
            key=lambda kv: (-kv[1], kv[0]))) + f"   (of {len(vec)} vector-capable)")


def _md_code(value) -> str:
    """A table cell as a code span that survives backticks and pipes in the value."""
    text = "" if value is None else str(value)
    if text in ("", "-"):
        return "-"
    text = text.replace("|", "\\|")
    run = max((len(m) for m in re.findall(r"`+", text)), default=0)
    fence = "`" * (run + 1)
    pad = " " if text.startswith("`") or text.endswith("`") or run else ""
    return f"{fence}{pad}{text}{pad}{fence}"


def _md_tally(values: list[str], n: int) -> str:
    cnt = Counter(values)
    return ", ".join(f"{k} {v}/{n}" for k, v in sorted(cnt.items(), key=lambda kv: (-kv[1], kv[0])))


def write_markdown(path: str, rows: list[dict], skipped: list[dict], discovery: dict,
                   app: str, argv: list[str]):
    """The peer-survey `<details>` block a pull request attaches, ready to paste."""
    n = len(rows)
    out = ["<details><summary>Peer survey</summary>", ""]
    cmd = "survey.py " + " ".join(a for a in argv if a != "--offline" and not a.startswith(
        ("--workdir", "--json", "--markdown", "/")))
    if discovery:
        out.append(
            f"`{cmd}`, run {datetime.date.today().isoformat()}: "
            f"{discovery['candidates']} candidates, {discovery['looked_at']} looked at until "
            f"{discovery['matched']} repositories running {app} were found "
            f"({discovery['prefiltered']} dropped before the tree check, "
            f"{discovery['tree_checked']} tree-checked). The {n} are the denominator; "
            f"{discovery['matched']} + {discovery['left_out']} left out = "
            f"{discovery['looked_at']} looked at.")
    else:
        out.append(f"`{cmd}`: {n} repositories running {app}.")
    out.append("")

    def table(title, header, cells, tally_values=None, tally_n=None):
        out.append(f"### {title}")
        out.append("")
        if tally_values is not None:
            out.append(f"Counts: {_md_tally(tally_values, tally_n or n)}.")
            out.append("")
        out.append("| Repository | " + " | ".join(header) + " |")
        out.append("|---" * (len(header) + 1) + "|")
        for repo, row in cells:
            out.append(f"| `{repo}` | " + " | ".join(row) + " |")
        out.append("")

    table("Postgres cluster", ["Cluster", "Role"],
          [(r["repo"], [_md_code(_db_label(r["db"])), _md_code(r["db"].get("class", "none"))])
           for r in rows], [r["db"].get("class", "none") for r in rows])
    vec = [r for r in rows if r["db"].get("vector_capable")]
    table(f"Vector extension source ({len(vec)} vector-capable)", ["Image", "Supplied by"],
          [(r["repo"], [_md_code(r["db"].get("image_short") or "-"),
                        _md_code(r["db"].get("vchord_source", "none"))]) for r in vec],
          [r["db"].get("vchord_source", "none") for r in vec], len(vec))
    table("Database storage", ["Storage class", "Size", "Kind"],
          [(r["repo"], [_md_code(r["db"].get("storage_class") or "-"),
                        _md_code(r["db"].get("storage_size") or "-"),
                        _md_code(r["db"].get("sc_kind", "none") if r["db"].get("cluster") else "none")])
           for r in rows],
          [r["db"].get("sc_kind", "none") if r["db"].get("cluster") else "none" for r in rows])
    table("Library", ["Mount", "Stored on", "Evidence"],
          [(r["repo"], [_md_code(f"{r['library'].get('name')}: {r['library'].get('type')}"
                                 if r["library"].get("name") else "-"),
                        _md_code(r["library"].get("store") or "none"),
                        _md_code(r["library"].get("via") or "-")]) for r in rows],
          [r["library"].get("store") or "none" for r in rows])
    table("Kustomization components", ["Components"],
          [(r["repo"], [_md_code(",".join(r["components"]) or "-")]) for r in rows])
    for title, key in (("HPA", "hpa"), ("`zeroscaler`", "zeroscaler"), ("ext-auth", "ext_auth")):
        table(title, ["Present"],
              [(r["repo"], ["yes" if r[key] else "no"]) for r in rows],
              ["yes" if r[key] else "no" for r in rows])

    if skipped:
        out.append("### Left out")
        out.append("")
        by_reason: dict[str, list[str]] = defaultdict(list)
        for s in skipped:
            by_reason[s["reason"]].append(s["repo"])
        for reason, repos in sorted(by_reason.items(), key=lambda kv: -len(kv[1])):
            out.append(f"- **{reason}** — {len(repos)}: " + ", ".join(f"`{r}`" for r in repos))
        out.append("")
    out.append("</details>")
    Path(path).write_text("\n".join(out) + "\n")
    print(f"markdown written to {path}")


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--app", required=True, help="app name, e.g. immich")
    ap.add_argument("--discover", action="store_true",
                    help="app-first discovery over the kubesearch topic (no clones)")
    ap.add_argument("--want", type=int, default=20, help="stop at N repos that run the app (default 20)")
    ap.add_argument("--facts", action="store_true", help="derive topology facts per repo")
    ap.add_argument("--candidates", default=None,
                    help="file of owner/name candidates instead of the topic search")
    ap.add_argument("--listing", choices=["auto", "api", "git"], default="auto",
                    help="how to list a repo's tree (default auto: API, git when the API quota is spent)")
    ap.add_argument("--max-candidates", type=int, default=400)
    ap.add_argument("--search-pages", type=int, default=5)
    ap.add_argument("--offline", action="store_true", help="use only cached API/blob responses")
    ap.add_argument("--workdir", default=None, help="cache dir (default: $XDG_CACHE_HOME/gitops-config-survey/<app>)")
    ap.add_argument("--refresh", action="store_true", help="ignore cached API responses")
    ap.add_argument("--out-repos", default=None, help="write matched owner/name lines here")
    ap.add_argument("--out-skipped", default=None, help="write skipped candidates (json) here")
    ap.add_argument("--repos", default=None, help="legacy: file with one owner/name per line")
    ap.add_argument("--chart", default=None, help="only HelmReleases whose chart name contains this")
    ap.add_argument("--filter", default=None, help="only report keys containing one of these substrings")
    ap.add_argument("--top", type=int, default=8, help="values shown per key (default 8)")
    ap.add_argument("--min-repos", type=int, default=2, help="drop keys seen in fewer repos")
    ap.add_argument("--json", default=None, help="write the full result here")
    ap.add_argument("--markdown", default=None,
                    help="write the PR's <details> peer-survey block here (needs --facts)")
    args = ap.parse_args()

    app = args.app.lower()
    cache_home = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    workdir = Path(args.workdir or cache_home / "gitops-config-survey" / app).expanduser().resolve()
    workdir.mkdir(parents=True, exist_ok=True)
    gh = GitHub(workdir, offline=args.offline)

    agg: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    matched: list[tuple[str, str]] = []
    facts: list[dict] = []
    skipped: list[dict] = []
    candidates: list[dict] = []
    materials: list[Material] = []
    discovery: dict = {}
    if args.markdown and not args.facts:
        ap.error("--markdown needs --facts")

    if args.repos and not args.discover:
        # ---- legacy clone mode (unchanged flattening behaviour) ---------- #
        repos = [line.strip() for line in Path(args.repos).read_text().splitlines()
                 if line.strip() and not line.startswith("#")]
        for repo in repos:
            dest = clone(repo, workdir / "clones", args.refresh)
            if dest is None:
                continue
            mat = clone_material(repo, dest)
            hit_paths = []
            for relpath, doc in iter_helmreleases(mat):
                if not looks_like_app(doc, app, f"/{relpath}", args.chart):
                    continue
                values = (doc.get("spec") or {}).get("values") or {}
                flat = flatten(values)
                if not flat:
                    continue
                hit_paths.append(relpath)
                matched.append((repo, relpath))
                for key, val in flat.items():
                    text = "" if val is None else str(val)
                    agg[key][text].add(repo)
            if hit_paths and args.facts:
                try:
                    facts.append(facts_for(mat, app, hit_paths))
                except Exception as exc:  # pragma: no cover - defensive
                    print(f"  ! facts failed for {repo}: {exc}", file=sys.stderr)
            materials.append(mat)
    else:
        # ---- app-first discovery ----------------------------------------- #
        if args.offline and not args.discover:
            args.discover = True
        matched_c, skipped, candidates, examined = discover(args, gh)
        for cand in matched_c:
            mat = Material(cand["full_name"], paths=cand["paths"], shas=cand["shas"],
                           gh=gh, branch=cand["branch"], rev=cand.get("rev", ""))
            hit_paths = []
            for relpath in cand["helmrelease_paths"]:
                for doc in mat.yaml_docs(relpath):
                    if not looks_like_app(doc, app, f"/{relpath}", args.chart):
                        continue
                    values = (doc.get("spec") or {}).get("values") or {}
                    flat = flatten(values)
                    hit_paths.append(relpath)
                    matched.append((cand["full_name"], relpath))
                    for key, val in flat.items():
                        text = "" if val is None else str(val)
                        agg[key][text].add(cand["full_name"])
            if not hit_paths:
                # The tree has the app's HelmRelease, so the repo runs the app: it
                # belongs in the denominator even when the document does not parse
                # (a duplicate YAML anchor, a kustomize patch, an unusual release
                # name). Nothing is aggregated for it, and the facts row says so.
                relpath = cand["helmrelease_paths"][0]
                hit_paths = [relpath]
                matched.append((cand["full_name"], relpath))
                print(f"  ~ {cand['full_name']}: release document not readable as the app's "
                      f"({relpath}); counted in the denominator, no values", file=sys.stderr)
            if args.facts:
                try:
                    facts.append(facts_for(mat, app, hit_paths))
                except Exception as exc:  # pragma: no cover - defensive
                    print(f"  ! facts failed for {cand['full_name']}: {exc}", file=sys.stderr)
            materials.append(mat)

        out_repos = Path(args.out_repos or (workdir / f"{app}-repos.txt"))
        out_repos.write_text("\n".join(sorted({c["full_name"] for c in matched_c})) + "\n")
        out_skipped = Path(args.out_skipped or (workdir / f"{app}-skipped.json"))
        out_skipped.write_text(json.dumps(skipped, indent=2))
        prefiltered = len(matched_c) + len(skipped) - examined
        discovery = {"candidates": len(candidates), "looked_at": len(matched_c) + len(skipped),
                     "prefiltered": prefiltered, "tree_checked": examined,
                     "matched": len(matched_c), "left_out": len(skipped), "wanted": args.want}
        print(f"discovery: candidates={len(candidates)} looked-at={discovery['looked_at']} "
              f"(prefiltered={prefiltered} fork/archived/chart-library, tree-checked={examined}) "
              f"= matched={len(matched_c)} + left-out={len(skipped)}; wanted={args.want}",
              file=sys.stderr)
        print(f"  repos -> {out_repos}\n  skipped -> {out_skipped}", file=sys.stderr)
        reasons = Counter(s["reason"] for s in skipped)
        print("  skipped reasons: " + ", ".join(f"{k}={v}" for k, v in reasons.items()),
              file=sys.stderr)

    if matched:
        report_keys(agg, matched, app, args.chart, args)
    else:
        print(f"survey: app={app!r} — no repo ran it "
              f"({len(candidates)} candidates checked)", file=sys.stderr)

    if args.facts and facts:
        report_facts(facts, app)
        if args.markdown:
            write_markdown(args.markdown, facts, skipped, discovery, app, sys.argv[1:])

    if args.json:
        payload = {
            "app": app,
            "chart": args.chart,
            "mode": "discover" if not (args.repos and not args.discover) else "clone",
            "n": len(matched),
            "candidates": [c["full_name"] for c in candidates],
            "matched": [{"repo": r, "path": p} for r, p in matched],
            "keys": {k: {v: sorted(s) for v, s in vals.items()} for k, vals in agg.items()},
            "discovery": discovery,
            "skipped": skipped,
            "facts": facts,
        }
        Path(args.json).write_text(json.dumps(payload, indent=2, default=str))
        print(f"json written to {args.json}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except GitHubError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(2)
