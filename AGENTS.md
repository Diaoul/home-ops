# AGENTS.md — agent guide for home-ops

Kubernetes homelab GitOps monorepo: Flux v2 on Talos Linux. Read this before changing anything.

---

## Stack

| Layer       | Technology                                                |
| ----------- | --------------------------------------------------------- |
| OS          | Talos Linux (immutable, API-driven)                       |
| Kubernetes  | upgraded in-place by tuppr                                |
| GitOps      | Flux v2 (flux-operator + flux-instance)                   |
| CNI         | Cilium (BGP, native routing, kube-proxy replacement)      |
| Ingress     | Envoy Gateway (Kubernetes Gateway API)                    |
| Storage     | Rook-Ceph (block) + miroir (node-local / DRBD-replicated) |
| Backup      | kopiur (Kopia) → NFS (singularity.milkyway)               |
| Database    | CloudNative-PG (PostgreSQL 18, HA)                        |
| Secrets     | SOPS + Age + PGP                                          |
| Helm charts | bjw-s/app-template (OCI) for nearly all apps              |
| Updates     | Renovate (hourly GitHub Actions)                          |
| Auth        | Authelia + LLDAP                                          |

Versions are deliberately absent: Renovate and tuppr move them, and a number written here
goes stale silently. Read live values instead — `kubectl version`, `talosctl version`, or the
pinned tag in the relevant `helmrelease.yaml`.

---

## Layout

```
kubernetes/
├── flux/cluster/ks.yaml        # Flux entrypoint → kubernetes/apps/
├── components/                 # Reusable Kustomize components
│   ├── common/                 # Namespace, OCI repos, SOPS secret, Flux alerts
│   ├── ext-auth/               # Authelia external auth (Envoy SecurityPolicy)
│   ├── nfs-scaler/             # KEDA autoscaler for NFS-dependent pods
│   ├── persistence/            # PVC + kopiur snapshot/restore templates
│   └── replacements/           # Shared variable substitution
└── apps/<namespace>/<app>/
    ├── ks.yaml                 # Flux Kustomization
    └── app/
        ├── kustomization.yaml
        ├── helmrelease.yaml
        └── secret.sops.yaml    # (optional) SOPS-encrypted secret
```

Namespaces: `cert-manager`, `database`, `default`, `downloads`, `flux-system`,
`home-automation`, `kube-system`, `media`, `miroir-system`, `network`, `observability`,
`rook-ceph`, `security`, `system-upgrade`

---

## App pattern

Every app is the same two files. Copy a working one — `kubernetes/apps/default/vaultwarden/` —
rather than writing from scratch.

### `ks.yaml`

```yaml
# yaml-language-server: $schema=https://k8s-schemas.home-operations.com/kustomize.toolkit.fluxcd.io/kustomization_v1.json
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: <app>
  namespace: flux-system
spec:
  targetNamespace: <namespace>
  commonMetadata:
    labels:
      app.kubernetes.io/name: <app>
  interval: 10m
  path: ./kubernetes/apps/<namespace>/<app>/app
  prune: true
  sourceRef:
    kind: GitRepository
    name: home-ops
  wait: true
  # Only the components this app actually needs:
  components:
    - ../../../../components/persistence # PVC + kopiur backup
    - ../../../../components/ext-auth # Authelia auth
    - ../../../../components/nfs-scaler # NFS (media/downloads)
  dependsOn:
    - name: rook-ceph-cluster # ceph-block storage
      namespace: rook-ceph
    - name: kopiur-repository # persistence component
      namespace: kopiur-system
    - name: cloudnative-pg # PostgreSQL
      namespace: database
  postBuild:
    substituteFrom:
      - kind: Secret
        name: cluster-secrets
    substitute:
      APP: <app>
      CAPACITY: 5Gi # persistence component
```

### `app/helmrelease.yaml`

```yaml
# yaml-language-server: $schema=https://k8s-schemas.home-operations.com/helm.toolkit.fluxcd.io/helmrelease_v2.json
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: <app>
spec:
  interval: 30m
  chartRef:
    kind: OCIRepository
    name: app-template
    namespace: flux-system
  install:
    remediation:
      retries: 3
  upgrade:
    cleanupOnFail: true
    remediation:
      strategy: rollback
      retries: 3
  values:
    controllers:
      <app>:
        annotations:
          reloader.stakater.com/auto: "true"
        containers:
          app:
            image:
              repository: <registry>/<image>
              tag: <version>@sha256:<digest>
            env:
              TZ: Europe/Paris
            securityContext:
              allowPrivilegeEscalation: false
              readOnlyRootFilesystem: true
              capabilities: { drop: ["ALL"] }
            resources:
              requests:
                cpu: 10m
              limits:
                memory: 512Mi
        pod:
          securityContext:
            runAsNonRoot: true
            runAsUser: 568
            runAsGroup: 568
            fsGroup: 568
            fsGroupChangePolicy: OnRootMismatch
    service:
      app:
        controller: <app>
        ports:
          http:
            port: <port>
```

### `app/kustomization.yaml`

```yaml
# yaml-language-server: $schema=https://json.schemastore.org/kustomization
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - helmrelease.yaml
  - secret.sops.yaml # only if secrets exist
```

---

## Networking

Gateway API only. `Ingress` resources are never used here.

| Gateway          | IP          | Use for                                              |
| ---------------- | ----------- | ---------------------------------------------------- |
| `envoy-external` | `10.44.0.1` | Publicly accessible services (via Cloudflare Tunnel) |
| `envoy-internal` | `10.44.0.2` | LAN-only services                                    |

Both live in namespace `network`. Add `httproute.yaml` to `app/` and list it in
`app/kustomization.yaml`:

```yaml
# yaml-language-server: $schema=https://k8s-schemas.home-operations.com/gateway.networking.k8s.io/httproute_v1.json
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: <app>
spec:
  parentRefs:
    - name: envoy-internal # or envoy-external
      namespace: network
      sectionName: https
  hostnames:
    - <app>.${DOMAIN}
  rules:
    - backendRefs:
        - name: <app>
          port: <port>
```

To put an app behind Authelia, add the `ext-auth` component in `ks.yaml`. Nothing else — the
component patches Envoy Gateway with the SecurityPolicy.

---

## Secrets

Secret files are named `*.sops.yaml` and encrypted before committing. A lefthook pre-commit
hook blocks any staged `*.sops.yaml` lacking a `sops:` block, but do not rely on it.

```sh
sops --encrypt --in-place kubernetes/apps/<namespace>/<app>/app/secret.sops.yaml
```

Plaintext template, before encrypting:

```yaml
# yaml-language-server: $schema=https://k8s-schemas.home-operations.com/core/secret_v1.json
apiVersion: v1
kind: Secret
metadata:
  name: <app>
stringData:
  SECRET_KEY: "value"
```

Injected into every Kustomization via `cluster-secrets`, usable as `${VAR}`: `${DOMAIN}`,
`${CLOUDFLARE_TUNNEL_ID}`, `${EMAIL_ADDRESS_1}`.

---

## Storage

| StorageClass        | Use for                                                                                            |
| ------------------- | -------------------------------------------------------------------------------------------------- |
| `ceph-block`        | default, replicated RBD                                                                            |
| `miroir-local`      | node-local LVM thin, no DRBD traffic                                                               |
| `miroir-replicated` | 2-way DRBD; keep off control planes — their system disks are already the etcd fdatasync bottleneck |

For persistent storage with backups, add the `persistence` component and set `APP` (PVC and
kopiur resource names) and `CAPACITY` in `substitute`. It creates a PVC on `ceph-block`
populated from a `Restore`, plus a `SnapshotPolicy` and `SnapshotSchedule` (daily to NFS via
kopiur).

The PVC's `dataSourceRef` is immutable — changing it means deleting and recreating the PVC.

For NFS-mounted media (`downloads`/`media`), use `miroir-local` and add the `nfs-scaler`
component.

---

## PostgreSQL

Add a `postgres-init` init container (`ghcr.io/home-operations/postgres-init`), an
`init-db-secret.sops.yaml`, and `dependsOn: cloudnative-pg`. See
`kubernetes/apps/default/vaultwarden/app/` or `kubernetes/apps/default/mealie/app/`.

---

## Rules

- **Images**: pin tag AND digest — `tag: 1.2.3@sha256:<digest>`. Never `latest`.
- **Schema header**: every YAML starts with `# yaml-language-server: $schema=...`.
- **Security context**: every container sets `allowPrivilegeEscalation: false`,
  `readOnlyRootFilesystem: true`, `capabilities: { drop: ["ALL"] }`, `runAsNonRoot: true`.
  Never `runAsRoot: true`, never skip it.
- **UID/GID**: `568` unless the image demands otherwise.
- **Timezone**: `TZ: Europe/Paris` in container env.
- **Reloader**: `reloader.stakater.com/auto: "true"` on controllers using ConfigMaps or Secrets.
- **Charts**: `chartRef` → `OCIRepository`, never inline `chart:`. Use the shared app-template
  `OCIRepository` in `components/common/` — do not create another.
- **Routing**: `HTTPRoute`, never `Ingress`.
- **Secret names**: the app name, no `-secret` suffix (`name: myapp`).

Before inventing a new app or config pattern, check [onedr0p/home-ops](https://github.com/onedr0p/home-ops) —
it is a configured git remote, so `git show onedr0p/main:<path>` works.

---

## Network policies

Do not add a `NetworkPolicy` or `CiliumNetworkPolicy` by default. Access control here is the
gateway plus Authelia; a policy that only restates that adds drift risk and maintenance for no
security gain.

Add one only when a workload holds a **network capability the rest of the cluster should not be
able to borrow**, and name that capability in a comment on the policy:

- it fetches arbitrary URLs on request, so it doubles as an open proxy (SSRF, egress laundering)
- it holds credentials or privileges that make it worth pivoting through

"Defence in depth" alone is not a justification — name the capability or don't write the policy.

Prefer `egressDeny` layered on open egress (`enableDefaultDeny.egress: false`) over
allow-listing: it fails open on the path you forgot rather than breaking the app, and keeps the
diff readable. Every CIDR is site-specific — check the VLAN map before copying one from upstream.

Both existing policies pass that test. Do not delete them as drift:

- `actions-runner-system/.../runners/home-ops/networkpolicy.yaml` — the runner keeps
  cluster-admin and `os:admin` and executes fork PRs; fenced off the LAN
- `default/searxng/app/ciliumnetworkpolicy.yaml` — unauthenticated and fetches arbitrary URLs;
  restricts who may call it and fences it off the LAN

---

## Comments

A comment explains a decision the YAML cannot. Nothing else.

Write one only for a **non-obvious constraint that outlives the change**: an upstream bug being
worked around, a value that looks wrong but is deliberate, a port that must avoid another
service. Name the constraint, not the story.

Never write:

- **Restatements.** `# Backing store for miroir's LVM thin pool` above
  `kind: RawVolumeConfig / name: miroir` says nothing the next two lines don't.
- **Migration narration.** Steps, orderings, "now that X", "replacing Y", what a previous value
  used to be. Procedures belong in the commit message — that is where someone looks when asking
  _why did this change_. A comment describing a one-off procedure ages into a lie.
- **Session or reasoning leakage.** Notes to self, what was tried, what an agent concluded. Git
  history holds this.

Delete the comment and read the YAML. If nothing is lost, it should not have been written.

---

## YAML formatting

Formatted with **oxfmt** (`.oxfmtrc.json`), run by lefthook on staged files. It skips
`*.sops.yaml` natively.

Do not add unnecessary double quotes. Quote only when YAML would otherwise misparse the value:

| Value type        | Example                      | Quoted?                                |
| ----------------- | ---------------------------- | -------------------------------------- |
| Plain string      | `sync`, `enabled`, `get`     | No                                     |
| Boolean lookalike | `"true"`, `"false"`, `"off"` | Yes — unquoted becomes a boolean       |
| Integer lookalike | `"0"`, `"1"`, `"9090"`       | Yes — unquoted becomes a number        |
| Empty string      | `""`                         | Yes — unquoted becomes null            |
| `@`-prefixed      | `"@daily"`, `"@hourly"`      | Yes — `@` is a reserved YAML indicator |
| `*`-prefixed      | `"*.example.com"`            | Yes — `*` is a reserved YAML indicator |
| PromQL / LogQL    | `'absent(up{job="foo"})'`    | Yes — contains special characters      |

oxfmt cannot strip unnecessary quotes — it only normalises `'single'` to `"double"` where safe.
Legacy quoted strings are harmless; just don't add new ones.

---

## Validation

```sh
bash scripts/kubeconform.sh kubernetes   # manifests against schemas
bash scripts/sops-mismatch.sh            # regenerate SOPS MAC where it mismatches
flux-local test --path kubernetes/       # requires flux-local
```

For `talos/`, validate against the live cluster instead (see `talos/README.md`):

```sh
just talos diff                    # topf apply --dry-run, live diff per node
just talos render                  # render to talos/rendered/ (gitignored)
talosctl validate -m metal -c talos/rendered/<node>.yaml
```

**Run these yourself.** The only automation is lefthook pre-commit: `oxfmt` on staged
YAML/JSON/markdown, `just --fmt` on justfiles, `zizmor` on workflows, and the unencrypted-sops
block. `.github/workflows/` holds only `image-pull`, `label-sync`, `renovate` and `tag`, so a PR
gets no `kubeconform` or `flux-local` signal. Konflate posts a status check, but it reviews Flux
changes under `kubernetes/` and says nothing about `talos/`.

---

## Commands

```sh
just talos diff                 # pending Talos config changes (dry-run)
just talos apply                # apply to all nodes (diffs and asks first)
just talos apply-node <name>    # apply to one node
just talos upgrade-node <name>  # upgrade Talos on a node (normally tuppr's job)
just bootstrap <step>           # talos/k8s/namespaces/resources/apps
```

Talos recipes take a node **name** (`k8s-node-1`), not an IP — they map to topf's
`--nodes-filter`. See `talos/README.md`.

kubectl:

- Use `kubectl` directly — not the `just kube` wrapper.
- Put `-n <namespace>` at the **end**: `kubectl logs -l app=foo -n media`, not
  `kubectl -n media logs -l app=foo`. A PreToolUse hook blocks the wrong form.
- Do not exec into pods to read cluster state — use `kubectl get`, `kubectl logs`, or the
  Prometheus HTTP API.

---

## Git

[Conventional Commits](https://www.conventionalcommits.org/):

- `feat:` adding or removing apps/features
- `fix:` bug fixes
- `docs:` documentation, including this file
- `refactor:` no behaviour change
- `chore:` maintenance (dependency bumps, formatting) — **not** adding/removing apps

**One concern per commit.** If the subject needs "and", it is two commits. A `fix(ai):` to a
HelmRelease and an edit to this file are never the same commit, however close together they
happened.

Stage deliberately: `git add <specific paths>`, never `git add -A` or `git add .`. Only files
belonging to the change being committed, even when other edits sit in the tree — they may be
someone else's work in progress.

Split before committing. Once pushed, fixing it means rewriting published history, which needs
the repo owner's say-so.

Flux reconciles immediately on push via a GitHub webhook. Never tell the user to wait N minutes.
