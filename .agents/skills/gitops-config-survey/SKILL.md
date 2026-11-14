---
name: gitops-config-survey
description: >
  Use when asked how other homelab GitOps repos configure an app, or when a pull request's
  Precedent line needs a peer count. Discovers the kubesearch repos that run the app, counts their
  HelmRelease values and topology facts, and writes the pull request's survey block.
---

# Survey how other homelab repos configure an app

Answer "how do other people do X for app Y" with counts from real repositories, the way
kubesearch.dev does: discover the repos that run the app, read its HelmRelease, flatten
`spec.values` into dotted keys, count each key -> value pair, and (with `--facts`) derive the
topology facts that live outside `spec.values`.

Never answer this kind of question from one repo you happen to remember. A single repo is an
anecdote; 20 repos give you the majority, the outliers, and which outlier is reasoned rather
than accidental.

## The denominator rule (read this first)

**N is the number of repos that actually run the app.** Not the number of repos you happened to
look at. A `repos.txt` assembled for one app is not a sample for another: the survivors are
whatever was popular for unrelated reasons, which is usually one fork lineage, and the denominator
silently shrinks. A published immich answer was computed this way from a radarr-era list: it said
`repos_scanned=20 matched=10` and read as "20 repos surveyed" when it was 10, chosen by accident.

So: never reuse a repo list across apps, never report the candidate count as N, and always print
`n/N` on every prevalence line. `--discover` enforces this by construction — it keeps scanning
candidates until `--want N` repos contain the app.

## When to Use

Load when the user asks how others configure an app (a values key, a workload pattern, a
persistence choice, a database setup), asks to check a config against community practice, or asks
"is there a setting for this" on a chart other people also run. Also worth running on an app
already deployed here, to catch a convention that moved or a feature that landed since.

## Discovery and counting are both scripted

Run it with `uv`, from the repository root: the script declares PyYAML inline (PEP 723), so
there is nothing to install.

```bash
survey=.agents/skills/gitops-config-survey/scripts/survey.py

# app-first discovery, then the table and the counts
uv run $survey --app immich --discover --want 20 --facts

# keys/values only, filtered
uv run $survey --app immich --discover --want 20 --filter persistence,DB_ --top 40

# instant rerun from the cache, no API calls
uv run $survey --app immich --discover --want 20 --facts --offline
```

Flags that matter:

- `--discover` — app-first. Enumerates `topic:kubesearch` (paginated, star-sorted), drops forks,
  archived repos and chart libraries, then tests each candidate for the app's HelmRelease with one
  `GET /repos/{o}/{r}/git/trees/{branch}?recursive=1`. Keeps going until `--want N` matches
  (default 20). Nothing is cloned: only the matched blobs are fetched from
  `raw.githubusercontent.com`.
- `--want N` — the denominator you are aiming for. Every report line prints it.
- `--facts` — per-repo topology table plus aggregate counts (components, persistence, CNPG cluster,
  HPA, scale-to-zero, ext-auth, own Postgres controller).
- `--candidates FILE` — enumerate from a list instead of the topic search (e.g. a kubesearch.dev
  app page, or the repos an earlier run named). Each line still goes through the same app-existence
  test, so the denominator stays app-first.
- `--offline` — reuse the workdir cache only; a warm rerun is instant and cannot hit a rate limit.
- `--workdir DIR` — cache (default `$XDG_CACHE_HOME/gitops-config-survey/<app>`): `api/` (search +
  tree responses), `blobs/` (fetched files), `git/` (blob-less listings). Never inside the
  repository.
- `--out-repos` / `--out-skipped` — the matched repo list, and one reason per candidate examined
  (`no-app`, `no-helmrelease`, `fork`, `archived`, `chart-library`, `truncated-tree`, `error`).
- `--json FILE` — full payload: candidates, matched, skipped, `keys`, `facts` (per-repo dicts with
  `db`, `library`, `components`, `depends_on`, `hpa_paths`, …) and `discovery` (the totals below).
  The stable interface for anything fancier.
- `--markdown FILE` (with `--facts`) — writes the pull request's
  `<details><summary>Peer survey</summary>` block: the run line with its totals, one table per fact
  with its `n/N` counts on top, then the left-out repos grouped by reason. Paste it; never retype
  the rows. Add a table by hand only for an app-specific fact the tool does not derive (e.g. a
  Dragonfly flag), and keep its rows to the same 20 repos.
- Discovery totals always add up: `looked-at = matched + left-out`, where `looked-at` counts the
  repos dropped before the tree check (fork, archived, chart library) as well as the tree-checked
  ones. Quote the run line from `--markdown` rather than recomputing it.
- `--listing auto|api|git` — how a repo's tree is listed. `api` is the trees endpoint; `git` is a
  quota-free equivalent (`git clone --filter=blob:none --no-checkout` + `ls-tree -r`, a few hundred
  KB, one second); `auto` (default) uses the API and falls back to git when the API refuses.
- `--repos FILE` — legacy clone mode, one `owner/name` per line, shallow-clones each repo. Kept only
  because its key flattening is what earlier answers were computed from: on the same clone cache the
  published script and this one produce identical `matched` and `keys` (radarr 18 matched/403 keys,
  sonarr 19/448). It does **not** fix the denominator — a hand-written list is a candidate set — so do
  not present its `repos_that_run_app` as a prevalence denominator for a new app.
- `--chart`, `--filter`, `--top`, `--min-repos`, `--refresh` — as before (chart name substring,
  dotted-key substring filter, values per key, drop singletons, re-fetch).

## How the app is found

Directory rule, identical in the crawler and in discovery: a path segment equal to the app name,
basename `helmrelease.yaml` / `helm-release.yml`, and `charts/**/templates` excluded (chart-vendored
YAML would otherwise dominate the counts). `immich/machine-learning/helmrelease.yaml` therefore
counts as the app's directory, while a helper release such as `immich/restic/` is kept in the repo
but only aggregated when its own name or path says it is the app.

Two files for one app is normal (a 4K or kids instance under `app-4k/`). A repo whose tree has the
app directory and a HelmRelease there is counted in N even if the document cannot be read as the
app's (odd release name, duplicate YAML anchor, kustomize patch): it runs the app, so it belongs in
the denominator — the tool prints a note and contributes no values for it.

## How the keys are formed

- dicts recurse as `parent.child`
- lists of dicts carrying a `name` (`env`, `volumes`, `ports`, `httpHeaders`) are keyed by that
  name: `controllers.immich.containers.app.env.DB_HOSTNAME`. This is the whole point — positional
  `env[12]` is meaningless across repos.
- lists of scalars collapse to one value (`a,b,c`); lists the script cannot name show as `<list>`
- values keep their literal text, `${SECRET_DOMAIN}` and `{{ .Release.Name }}` included. Never
  normalise them away: whether a repo hardcodes a name or templates it is itself the finding.

## What `--facts` derives, and how to read it

One row per repo, then counts with `n/N`:

- **ks components** — `spec.components` (basenames, e.g. `zeroscaler`, `ext-auth`, `dragonfly`) plus
  the sub-directories the Kustomizations point at (`app`, `database`, `cache`). Components are
  resolved relative to `spec.path`, which is repo-root relative — not relative to the `ks.yaml`.
- **library** — the persistence entry that holds the photo library, found by mount path
  (`/usr/src/app/upload`, `/data`, `/photos`, `/library`) and then by name keyword
  (`library`, `photos`, `media`, `upload`, …), with its `type` (`nfs`, `persistentVolumeClaim`,
  `existingClaim`, `emptyDir`, `secret`, `configMap`, `hostPath`) and storage class. This is what
  separates "library on NFS" from "library on a PVC"; a chart that keeps `persistence` under
  `values.<chart>.persistence` is handled too. The mount paths are Immich's: for another app, check
  that the picked entry is the one the question is about.
- **library store** — where that data lives, as opposed to how it is mounted: `nas`, `network`
  (replicated block), `node-local`, `ephemeral` or `unknown`, with the evidence in `via`. An
  `existingClaim` is followed to its PVC and PV in git (by `volumeName`, `claimRef`, or a static PV
  sharing the claim's class), so an NFS-backed claim counts as `nas`. Count a "where does the data
  live" decision on this, not on the mount type. Off by one or two on esoteric setups is fine.
- **db cluster** — `DB_HOSTNAME` / `DB_HOST` / `DB_URL` / `POSTGRES_*` reduced to a service name
  (`immich-postgres-rw.media.svc` -> `immich-postgres`), then matched against `postgresql.cnpg.io`
  `Cluster` CRs in the same repo: by host, by the secret name a `valueFrom` points at, by a Cluster
  in the app's own directory, by name, by the `postgresVector: "true"` controller label, or (when
  the repo has exactly one cluster) as the repo's single cluster. `unresolved (secret-ref:…)` means
  the value comes from a Secret that is not in git — say so instead of guessing.
- **db image / db ext / db storage** — `imageName`, `postgresql.extensions` (+ the app's `Database`
  CR extensions when the cluster is shared), `shared_preload_libraries`, `storage.storageClass` and
  `size`, `instances`. `${VAR:=default}` and `${APP}` are resolved (Flux semantics; `APP` is the app
  name), so a `postgres-${APP}` cluster reads as `postgres-immich`.
- **vchord supplied by** — `extension-image` when the cluster mounts an extension image volume
  (`postgresql.extensions[].image.reference`, i.e. `ghcr.io/tensorchord/vchord-scratch`) versus
  `base-image` when vchord is baked into `cloudnative-vectorchord`. These are different designs and
  the difference is invisible in `spec.values`.
- **db cluster role** — `vector-dedicated` (vector-capable and named for / living under the app),
  `vector-shared` (vector-capable but shared), `general-*` (CNPG, no vector extension),
  `other-operator` (crunchy/zalando CR instead of CNPG), `unresolved`, `none`.
- **HPA / zeroscaler / ext-auth / pg ctrl** — any `HorizontalPodAutoscaler` in the app tree or in a
  component it references; a `zeroscaler`-ish component; an `ext-auth`/`extauth` component; a
  `postgres` controller key in the release (the app running its own database pod).

Report the denominator with every count, and name the match reason when it matters: a
`single-cluster` or `vector-label` match is weaker evidence than a host match.

## Reading the output

- Always report the denominator (`13/19`), not just the top value. "7 use X" is noise; "13 of 19 use
  X, and the one outlier says why in a comment" is an answer.
- Deviations cluster by fork lineage. `onedr0p/home-ops` and its descendants share values, so 8
  repos agreeing is often one opinion copied, not eight independent confirmations. Say so when the
  `[who]` lists are all the same family.
- "Key absent" is a real result: if `--filter` returns nothing, most repos do not set it, which
  usually means the chart default already does what the user wants.
- Cross-check a promising value against the upstream source before proposing it — the survey says
  what people wrote, not what is valid. `gh api repos/<owner>/<repo>/contents/<path>` is cheap.
- When a corrected sample changes a number you already published, say both numbers explicitly
  (old n/N and new n/N plus the share). Do not quietly restate.

## Pitfalls

- The search endpoint needs a token. Unauthenticated `api.github.com/search/repositories` is a
  shared 10/min bucket and answers `403` "rate limit exceeded" as soon as anything else on the IP
  crawls; the script fails loudly with that explanation rather than returning an empty list. Export
  `GITHUB_TOKEN` (or `gh auth login`) — the script also reads `gh auth token`. `--candidates FILE`
  is the escape hatch: enumeration from elsewhere, existence test still in-script.
- Unauthenticated *core* quota is 60 requests/hour, so the trees API realistically covers ~50
  candidates per hour. That is why `--listing auto` falls back to the blob-less git listing, which
  costs one second per repo and no quota. Trees cache under `api/` so a rerun resumes.
- `raw.githubusercontent.com` accepts a branch, tag or **commit** sha — not a blob sha. The trees
  endpoint returns blob shas; the git listing returns the commit sha, which is what `blobs/` needs.
- `truncated: true` on a trees response (very large repos) falls back to a per-directory contents
  walk for that repo only; if that fails too the candidate is recorded as `truncated-tree`, not
  silently dropped.
- Duplicate YAML anchors (`liveness: &probes` reused in two containers of one document) make
  PyYAML raise `ComposerError` on files Kubernetes accepts. The loader renames the 2nd+ definition
  and the aliases after it; without this the HelmRelease silently vanishes from the counts.
- `spec.components` in Flux are relative to `spec.path`, which is itself repo-root relative. Joining
  them to the `ks.yaml` directory produces a plausible-looking path that does not exist — always
  filter resolved component dirs against the tree.
- Disabled manifests (`/.archive/`, `/archive/`) are not deployed; a Cluster found there is not the
  app's database. Discovery skips them.
- Chart-vendored YAML under `charts/**/templates` is skipped, otherwise library charts dominate the
  counts. A repo that inlines `spec.values` via YAML anchors still flattens correctly.
- Renovate-pinned tags differ per repo (`7.0.2.10888`, `7.0.2`, `7.0.2@sha256:...`): never rank
  image tags as consensus, only as "the current line".
- `--filter` matches the whole dotted path, so `--filter auth` also catches `DB_USERNAME`. Narrow
  with two or three `__`-qualified substrings when it matters.
- A cold `--repos` run clones ~190 MB; `--discover` fetches tens of small files instead. Prefer it
  for anything new.

## Extending

- Other HelmRelease-shaped questions (probes, resources, securityContext) need no code change — they
  are all just keys.
- `--json` is the stable interface for anything fancier: the `facts` list is one dict per repo with
  all derived fields, so new columns are a few lines in `report_facts` and a new key in `facts_for`.
- Broadening beyond the topic set: `--candidates FILE` with your own repo list; nothing else assumes
  kubesearch.
