# AGENTS.md — AI Agent Guide for home-ops

A Kubernetes homelab GitOps monorepo: Flux v2 on Talos Linux. Read this file before making
any change.

| Layer | Technology |
|---|---|
| OS | Talos Linux, upgraded with Kubernetes in place by tuppr |
| GitOps | Flux v2 (flux-operator + flux-instance) |
| CNI | Cilium (BGP, native routing, kube-proxy replacement) |
| Ingress | Envoy Gateway (Gateway API only) |
| Storage | Rook-Ceph (block) + miroir (node-local / DRBD-replicated) |
| Backup | kopiur (Kopia) → Garage S3 on the NAS (singularity.milkyway) |
| Database | CloudNative-PG (PostgreSQL, HA) |
| Secrets | SOPS + Age + PGP |
| Helm charts | bjw-s/app-template (OCI) for nearly all apps |
| Updates | Renovate (hourly GitHub Actions) |
| Auth | Kanidm (kaniop); oauth2-proxy for ext-auth |

Versions are deliberately absent: they go stale. Read the live value (`kubectl version`,
`talosctl version`, the pinned tag in a `helmrelease.yaml`).

Layout: `kubernetes/flux/cluster/ks.yaml` is the Flux entrypoint;
`kubernetes/apps/<namespace>/<app>/` holds a `ks.yaml` and an `app/` directory;
`kubernetes/components/` holds reusable Kustomize components; `talos/` the node configs.

## Skills

`.agents/skills/` holds the procedures; load the one that fits before starting:

- `adding-an-app`: app templates, routes, ext-auth, persistence, PostgreSQL, network policies
- `creating-a-sops-secret`: a new encrypted Secret, without seeing its values
- `writing-a-pull-request` / `reviewing-pull-requests`
- `cluster-health`, `gitops-config-survey`

## Conventions

- **Images** pinned by tag and digest: `tag: 1.2.3@sha256:<digest>`; never `latest`.
- **Schema comment** first in every YAML file: `# yaml-language-server: $schema=...`.
- **Hardened containers**: `allowPrivilegeEscalation: false`, `readOnlyRootFilesystem: true`,
  `capabilities: { drop: ["ALL"] }`, `runAsNonRoot: true`, UID/GID `568` unless the image
  needs otherwise.
- `reloader.stakater.com/auto: "true"` on controllers that use ConfigMaps or Secrets.
- `TZ: Europe/Paris` in every container that reads local time.
- `chartRef` to an `OCIRepository`, never inline `chart:`; app-template uses the shared one
  from `components/common/`.
- HTTPRoute through Envoy Gateway; never `Ingress`.
- Name objects after the app, never with their kind (`myapp`, not `myapp-configmap`).
- Never commit an unencrypted `*.sops.yaml`.
- Before a new app or configuration pattern, check how [onedr0p/home-ops](https://github.com/onedr0p/home-ops)
  does it: `git show onedr0p/main:<path>`.
- No `NetworkPolicy` without a capability to fence; see `adding-an-app` before writing or
  deleting one.
- `kubernetes/flux/cluster/ks.yaml` patches every HelmRelease (CRD upgrades, remediation,
  rollback, history). Grep it before adding an `install:`/`upgrade:` block or flagging one as
  missing; an app sets one only to differ from it.

## Comments

A comment names a non-obvious constraint that outlives the change: an upstream bug worked
around, a value that looks wrong but is deliberate. Never a restatement of the YAML below it,
migration narration (steps, "now that X", previous values: that is the commit message), or
session leakage (what was tried, what an agent concluded). Delete the comment and read the
YAML: if nothing is lost, it should not exist.

## YAML

yamlfmt (`.yamlfmt.yaml`) formats staged YAML in a lefthook pre-commit hook. Quote a string
only when YAML would misparse it: boolean or number lookalikes (`"true"`, `"9090"`), `""`,
values starting with `@` or `*`, PromQL/LogQL. yamlfmt cannot drop needless quotes, so write
new files without them.

## Validation

`just validate` runs the checks `.github/workflows/validate.yaml` runs on every pull request
to `main`; a direct push to `main` skips CI, so run it yourself before pushing. Run checks
through `just` recipes and the lefthook hooks, never by retyping their commands.

All of these come from `.mise.toml`; Python CLIs are `pypi:` tools, not a project venv.
Konflate also posts a status check with the rendered diff of Flux changes under `kubernetes/`.

Nothing checks `talos/`; validate it against the live cluster (see `talos/README.md`):

```sh
just talos diff                    # topf apply --dry-run, shows the live diff per node
just talos render                  # render to talos/rendered/ (gitignored)
talosctl validate -m metal -c talos/rendered/<node>.yaml
```

`talos/rendered/` holds the cluster's secrets in plain text: agents never render into it, read
it or write to it, by any tool. Ask the user to run the last two commands.

Talos recipes (`just talos apply-node`, `upgrade-node`) take a node name (`k8s-node-1`), not
an IP.

## Cluster access

- Plain `kubectl`, not `just kube`, with `-n <namespace>` at the end:
  `kubectl logs -l app=foo -n media`. A hook blocks `kubectl -n <ns> ...`.
- Read state with `kubectl get`, `kubectl logs` or the Prometheus HTTP API; never exec into a
  pod for it.
- Reach an app's API through its route (`https://<app>.${DOMAIN}`); port-forward only when it
  has no route or sits behind ext-auth.
- Flux reconciles on push through a GitHub webhook: never tell the user to wait for it.

## Git

[Conventional Commits](https://www.conventionalcommits.org/): `feat:` adds or removes an app
or feature, `fix:`, `docs:` (this file included), `refactor:` changes no behaviour, `chore:`
for maintenance such as bumps and formatting, never for adding or removing an app.

One concern per commit: if the subject needs "and", it is two commits. A `fix(ai):` to a
HelmRelease and an edit to this file are never the same commit. Stage named paths only
(`git add <path>`, never `-A` or `.`): other edits in the tree may be someone else's work.
Split before pushing; rewriting published history needs the repo owner's say-so.
