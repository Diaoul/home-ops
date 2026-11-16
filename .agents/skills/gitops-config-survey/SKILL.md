---
name: gitops-config-survey
description: >
  Use when asked how other homelab GitOps repos configure an app, or when a pull request's
  Precedent line needs a peer count. Discovers the kubesearch repos that run the app, counts their
  HelmRelease values and topology facts, and writes the pull request's survey block.
---

# Surveying how peers configure an app

Answer "how do others do X for app Y" with counts from real repositories, not from one repo you
remember: a single repo is an anecdote, twenty give the majority, the outliers, and which outlier
is reasoned. The survey also earns a run on an app already deployed here, to catch a convention
that moved or a feature that landed since.

## The denominator

**N is the number of repositories that run the app**, never the number looked at. The script
keeps scanning candidates until `--want N` repositories contain the app, counts a repository once
however many instances it runs (`app-4k`), and prints `n/N` on every line. Never reuse one app's
repo list for another: the survivors are whatever was popular for unrelated reasons, and the
denominator shrinks without saying so.

## Running it

From the repository root, with `uv`; PyYAML is declared inline, so nothing is installed:

```bash
survey=.agents/skills/gitops-config-survey/scripts/survey.py

uv run $survey --app immich --facts                           # keys, then the facts table
uv run $survey --app immich --filter persistence,DB_ --top 40 # keys only, filtered
uv run $survey --app immich --facts --markdown survey.md      # the pull request's survey block
uv run $survey --app immich --facts --offline                 # instant rerun from the cache
```

Give it a token: it reads `GITHUB_TOKEN`, `GH_TOKEN` or `gh auth token`. Without one, the search
API allows ten calls a minute shared with everything else on the address, and once refused the
script stops with an explanation rather than an empty list. A cold run takes a few minutes.

- `--want N` — the denominator to reach (default 20).
- `--facts` — the per-repository table and its counts, described below.
- `--markdown FILE` (with `--facts`) — the `<details><summary>Peer survey</summary>` block for a
  pull request: the run line with its totals, one table per fact with its `n/N` counts, then the
  left-out repositories by reason. Paste it; never retype the rows. Add a table by hand only for a
  fact the tool does not derive (a Dragonfly flag), and keep its rows to the same repositories.
- `--library NAME_OR_MOUNT` — the persistence entry holding the app's data, when the guess is
  wrong. It applies to every repository it matches; the others keep the guess.
- `--candidates FILE` — `owner/name` lines instead of the topic search. Each still goes through
  the app-existence test, so the denominator stays the repositories that run the app.
- `--filter`, `--top`, `--min-repos`, `--chart` — key substrings to keep, values shown per key,
  keys seen in fewer repositories dropped, chart name substring.
- `--json FILE` — the full result (`keys`, `facts`, `discovery`, `skipped`), for anything the
  reports do not show.
- `--out-repos`, `--out-skipped` — the matched list, and one reason per left-out candidate:
  `fork`, `archived`, `chart-library`, `no-app`, `no-helmrelease`, `truncated-tree`, `error`.

The run line always adds up: looked at = matched + left out, where looked at includes the
repositories dropped before their tree was checked. Quote it from `--markdown` rather than
recomputing it.

### Cache

Under `$TMPDIR/gitops-config-survey/<app>` when `TMPDIR` is set, as in Hermes, whose scratch
directory is pruned a day after its last use; otherwise under `$XDG_CACHE_HOME` (`~/.cache`).
`--workdir` moves it, never into the repository. Search results, tree listings and clones are
reused for `--max-age` hours (default 24); `--refresh` refetches the API ones now. Files are
cached by their git blob sha, so they are never stale. `--offline` uses only the cache, whatever
its age, and never touches the network; anything missing is reported.

`--listing auto|api|git` chooses how a tree is listed: the trees API, or a blob-less clone that
costs no API quota. `auto`, the default, falls back to the clone when the API refuses.

## What is counted

A repository runs the app when its tree has a path segment equal to the app name with a
`helmrelease.yaml` or `helm-release.yaml` (either extension) under it, outside
`charts/**/templates`. It stays in the denominator even when that document cannot be read as the
app's; the script says so and counts no values for it. A repository whose facts cannot be derived
stays too, as `unknown` in every fact table. A helper release beside it (`immich/restic/`) is
counted only when its own name or path says it is the app.

Keys are `spec.values` flattened to dotted paths. Lists of objects with a `name` (`env`, `ports`,
`volumes`) are keyed by that name, so `controllers.immich.containers.app.env.DB_HOSTNAME` lines up
across repositories where `env[12]` would not. Values keep their literal text, `${SECRET_DOMAIN}`
and `{{ .Release.Name }}` included: whether a repository hardcodes or templates a value is itself
a finding.

## What `--facts` derives

- **components** — the Kustomization's `spec.components`, plus the sub-directories its
  Kustomizations point at (`app`, `database`).
- **library** — the persistence entry holding the app's data rather than its config, cache or
  scratch space: a data-like name or mount (`media`, `library`, `data`, `upload`, …), NFS breaking
  a tie. Its type is how it is mounted.
- **library store** — where that data lives: `nas`, `network` (replicated block), `node-local`,
  `ephemeral` or `unknown`, with the evidence in `via`. An `existingClaim` is followed to its PVC
  and PV in git, so an NFS-backed claim counts as `nas`. Count a "where does the data live"
  decision on this, not on the mount type.
- **db cluster** — the database host from the app's env (`DB_HOSTNAME`, `DB_URL`, `POSTGRES_*`),
  matched to a CNPG `Cluster` in the repository by host, by the secret a `valueFrom` names, by a
  Cluster in the app's directory or named after it, or, when the app has some database setting,
  as the repository's only cluster. `unresolved (secret-ref:…)` means the host is in a Secret that
  is not in git: say so rather than guess.
- **db image, extensions, storage** — the image repository, `postgresql.extensions` plus the app's
  `Database` CR extensions on a shared cluster, `shared_preload_libraries`, storage class and size.
  Flux substitutions are resolved, `${VAR:=default}` included, with `APP` as the app name.
- **db cluster role** — `dedicated` (in the app's directory or named after it), `shared`,
  `other-operator` (Crunchy, Zalando), `unresolved` or `none`.
- **HPA, zeroscaler, ext-auth, own postgres controller** — an HPA in the app's tree or its
  components, a component of that name, or a `postgres` controller in the release.

## Needs review

The facts are generic: nothing in the script knows one app from another. Where a fact rests on a
guess, `--facts` ends with a `needs review` list, also in `--json` as each row's `review`: a
database cluster taken because it is the repository's only one or carries the app's name, a host
held in a Secret, no data volume or no `persistence` block recognised, a library whose store is
unknown, a repository running several releases of the app, a release that could not be read.

Before quoting a count that a flagged repository is part of, open the file the item names and
settle it. A wrong data volume is fixed with `--library`; anything else is a correction under the
table it changes, giving the repository and the fact as read. Anything the decision needs that no
fact covers (whether a shared cluster carries the extension the app needs, a chart-specific
setting) is the same manual read, in the repositories the tables already list.

## Reading the output

- Give the count with the denominator, `13/19`. "7 use X" says nothing; "13 of 19 use X, and the
  outlier says why in a comment" is an answer.
- Repositories descended from `onedr0p/home-ops` share values, so eight agreeing can be one
  opinion copied. Say so when the `[who]` lists are one family.
- A key nobody sets usually means the chart default already does the job.
- The survey says what people wrote, not what is valid: check a promising value against the
  upstream chart or app before proposing it.
- Image tags differ by Renovate pin (`7.0.2.10888`, `7.0.2@sha256:…`); they show the current
  line, never a consensus.
- `--filter` matches the whole dotted path, so `auth` also catches `DB_USERNAME`.
- When a corrected run changes a number already published, give the old and the new count.
- Off by one or two on an unusual setup is fine: the counts back a decision, they are not a census.

## Changing the script

Run the tests after any change:

```bash
uv run --with pytest --with pyyaml pytest .agents/skills/gitops-config-survey/tests
```

A new fact is a key in `facts_for`, a tally in `report_facts` and a table in `write_markdown`.
Before committing, compare `--json` output from the old and new script on the same cache with
`--offline`; any difference in `keys` or `facts` should be one you meant.
