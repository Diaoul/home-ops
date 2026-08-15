# AGENTS.md — AI Agent Guide for home-ops

This is a Kubernetes homelab GitOps monorepo managed with Flux v2 on Talos Linux.
Read this file before making any changes.

---

## Project Overview

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

Versions are deliberately absent: Renovate and tuppr move them, and a number written
here goes stale silently. Read the live values instead — `kubectl version`,
`talosctl version`, or the pinned tag in the relevant `helmrelease.yaml`.

---

## Repository Layout

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

### Namespaces

`cert-manager`, `database`, `default`, `downloads`, `flux-system`, `home-automation`,
`kube-system`, `media`, `miroir-system`, `network`, `observability`, `rook-ceph`,
`security`, `system-upgrade`

---

## Universal App Pattern

Every app follows this exact two-file pattern. Study an existing app (e.g.,
`kubernetes/apps/default/vaultwarden/`) before adding a new one.

### `ks.yaml` — Flux Kustomization

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
  # Include ONLY the components that this app actually needs:
  components:
    - ../../../../components/persistence # if app needs PVC + kopiur backup
    - ../../../../components/ext-auth # if app needs Authelia auth
    - ../../../../components/nfs-scaler # if app needs NFS (media/downloads)
  dependsOn:
    - name: rook-ceph-cluster # if using ceph-block storage
      namespace: rook-ceph
    - name: kopiur-repository # if using persistence component
      namespace: kopiur-system
    - name: cloudnative-pg # if using PostgreSQL
      namespace: database
  postBuild:
    substituteFrom:
      - kind: Secret
        name: cluster-secrets
    substitute:
      APP: <app>
      CAPACITY: 5Gi # if using persistence component
```

### `app/helmrelease.yaml` — HelmRelease (app-template)

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
              tag: <version>@sha256:<digest> # ALWAYS pin both tag AND digest
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
    ingress: {} # NOT used — use HTTPRoute instead (see Networking below)
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

**Do NOT use `Ingress` resources.** This cluster uses Kubernetes Gateway API exclusively.

### Gateways

| Gateway          | IP          | Use for                                              |
| ---------------- | ----------- | ---------------------------------------------------- |
| `envoy-external` | `10.44.0.1` | Publicly accessible services (via Cloudflare Tunnel) |
| `envoy-internal` | `10.44.0.2` | LAN-only services                                    |

Both gateways are in namespace `network`.

### HTTPRoute example

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

Add `httproute.yaml` to `app/` and reference it in `app/kustomization.yaml`.

### Authelia (external auth)

To protect an app with Authelia, add the `ext-auth` component in `ks.yaml`. No other
changes are needed — the component patches Envoy Gateway with the SecurityPolicy.

---

## Secrets Management (SOPS)

**CRITICAL: Never commit unencrypted secrets.** All secret files must be named
`*.sops.yaml` and encrypted before committing.

Encrypt a new secret:

```sh
sops --encrypt --in-place kubernetes/apps/<namespace>/<app>/app/secret.sops.yaml
```

Secret template before encryption:

```yaml
# yaml-language-server: $schema=https://k8s-schemas.home-operations.com/core/secret_v1.json
apiVersion: v1
kind: Secret
metadata:
  name: <app>
stringData:
  SECRET_KEY: "value"
```

### Global variables (injected into all Kustomizations via `cluster-secrets`)

These are available via `postBuild.substituteFrom` and can be used as `${VAR}`:

- `${DOMAIN}` — homelab domain
- `${CLOUDFLARE_TUNNEL_ID}`
- `${EMAIL_ADDRESS_1}`

---

## Persistence (kopiur + PVC)

For apps that need persistent storage with automatic backups, add the `persistence`
component in `ks.yaml` and set:

```yaml
substitute:
  APP: <app> # Used as PVC name and kopiur resource names
  CAPACITY: 5Gi # PVC size (default if omitted)
```

The component creates:

- A `PersistentVolumeClaim` named `<app>` using `ceph-block` StorageClass, populated
  from a `Restore`
- A `SnapshotPolicy` + `SnapshotSchedule` (daily snapshot to NFS via kopiur/Kopia)
- A `Restore` (populates the PVC from the latest snapshot)

Note the PVC's `dataSourceRef` is immutable: changing it requires deleting and
recreating the PVC.

For NFS-mounted media (downloads/media namespace), use `miroir-local` StorageClass
and add the `nfs-scaler` component.

Storage classes: `ceph-block` (default, replicated RBD), `miroir-local` (node-local
LVM thin, no DRBD traffic), `miroir-replicated` (2-way DRBD, keep it off control
planes; their system disks are already the etcd fdatasync bottleneck).

---

## PostgreSQL Pattern

For apps needing a PostgreSQL database:

1. Add a `postgres-init` init container using the `ghcr.io/home-operations/postgres-init` image.
2. Create `init-db-secret.sops.yaml` with database credentials.
3. Add `dependsOn: cloudnative-pg` in `ks.yaml`.

Reference: `kubernetes/apps/default/vaultwarden/app/` or `kubernetes/apps/default/mealie/app/`.

---

## Key Conventions — Always Follow These

1. **Image pinning**: Always use both tag AND digest: `tag: 1.2.3@sha256:<digest>`
2. **Schema comments**: Every YAML file must start with `# yaml-language-server: $schema=...`
3. **Security context**: All containers need `allowPrivilegeEscalation: false`,
   `readOnlyRootFilesystem: true`, `capabilities: { drop: ["ALL"] }`, `runAsNonRoot: true`
4. **Reloader annotation**: Add `reloader.stakater.com/auto: "true"` on controllers
   that use ConfigMaps or Secrets
5. **OCI charts**: Use `chartRef` (OCIRepository) not inline `chart:` in HelmReleases
6. **No Ingress**: Use HTTPRoute + Envoy Gateway (Gateway API)
7. **Timezone**: Always set `TZ: Europe/Paris` in container env
8. **UID/GID**: Default is `568` for all app containers unless image requires otherwise

---

## Comments

Comments explain a decision the YAML cannot. Nothing else.

Write one only for a **non-obvious constraint that outlives the change**: an upstream
bug being worked around, a value that looks wrong but is deliberate, a port that must
avoid another service. Name the constraint, not the story.

Never write:

- **Restatements.** `# Backing store for miroir's LVM thin pool` above
  `kind: RawVolumeConfig / name: miroir` says nothing the next two lines don't.
- **Migration narration.** Steps, orderings, "now that X", "replacing Y", what a
  previous value used to be. Procedures belong in the commit message, which is where
  someone looks when asking _why did this change_. A comment describing a one-off
  procedure ages into a lie.
- **Session or reasoning leakage.** Notes to self, what was tried, what an agent
  concluded. Git history holds this.

Rule of thumb: delete the comment and read the YAML. If nothing is lost, it should not
have been written.

## YAML Formatting

All YAML is formatted with **yamlfmt** (config in `.yamlfmt.yaml`). The formatter runs
automatically via lefthook on staged files before every commit.

### Quote style

Do **not** add unnecessary double quotes around plain string values. Only quote when
YAML would misparse the value without them:

| Value type        | Example                      | Quoted?                                |
| ----------------- | ---------------------------- | -------------------------------------- |
| Plain string      | `sync`, `enabled`, `get`     | No                                     |
| Boolean lookalike | `"true"`, `"false"`, `"off"` | Yes — unquoted becomes a boolean       |
| Integer lookalike | `"0"`, `"1"`, `"9090"`       | Yes — unquoted becomes a number        |
| Empty string      | `""`                         | Yes — unquoted becomes null            |
| `@`-prefixed      | `"@daily"`, `"@hourly"`      | Yes — `@` is a reserved YAML indicator |
| `*`-prefixed      | `"*.example.com"`            | Yes — `*` is a reserved YAML indicator |
| PromQL / LogQL    | `'absent(up{job="foo"})'`    | Yes — contains special characters      |

Note: yamlfmt cannot remove unnecessary quotes automatically. Existing files may have
legacy quoted strings that are safe but not worth bulk-editing. Write new files
without unnecessary quotes from the start.

---

## Validation

Before committing, validate your YAML:

```sh
# Validate Kubernetes manifests against schemas
bash scripts/kubeconform.sh kubernetes

# Regenerate the SOPS MAC on files that report a mismatch
bash scripts/sops-mismatch.sh

# Lint YAML
yamllint .

# Full Flux validation (requires flux-local installed)
flux-local test --path kubernetes/
```

For changes under `talos/`, validate against the live cluster instead — see
`talos/README.md`:

```sh
just talos diff                    # topf apply --dry-run, shows the live diff per node
just talos render                  # render to talos/rendered/ (gitignored)
talosctl validate -m metal -c talos/rendered/<node>.yaml
```

**Run these yourself — they are not enforced anywhere.** The only automation is
lefthook pre-commit, which runs `yamlfmt` on staged YAML, `just --fmt` on staged
justfiles, and blocks any staged `*.sops.yaml` that is not encrypted. There are no
manifest-validation workflows in `.github/workflows/` (only
`image-pull`, `label-sync`, `renovate`, `tag`), so a PR gets no `kubeconform`,
`yamllint`, or `flux-local` signal. Konflate posts a status check, but it reviews Flux
changes under `kubernetes/` and says nothing about `talos/`.

---

## Just Commands

```sh
just talos diff                 # Show pending Talos config changes (dry-run)
just talos apply                # Apply Talos config to all nodes (diffs and asks first)
just talos apply-node <name>    # Apply Talos config to a node
just talos upgrade-node <name>  # Upgrade Talos on a node (normally tuppr's job)
just bootstrap <step>           # Bootstrap steps (talos/k8s/namespaces/resources/apps)
```

Talos recipes take a node **name** (`k8s-node-1`), not an IP — they map to topf's
`--nodes-filter`. See `talos/README.md`.

---

## kubectl Conventions

- Use plain `kubectl` directly — do not use `just kube` wrapper
- Put `-n <namespace>` at the **end** of kubectl commands, not immediately after `kubectl`
  - Correct: `kubectl logs -l app=foo -n media`
  - Wrong: `kubectl -n media logs -l app=foo`
- Do not exec into pods to retrieve cluster info — use `kubectl get`, `kubectl logs`, or the Prometheus HTTP API
- A PreToolUse hook enforces the `-n` placement rule and will block `kubectl -n <ns> ...` commands

---

## Git Conventions

Use [Conventional Commits](https://www.conventionalcommits.org/):

- `feat:` for adding or removing apps/features
- `fix:` for bug fixes
- `docs:` for documentation, including this file
- `refactor:` for changes that alter no behaviour
- `chore:` for maintenance (dependency bumps, formatting) — **not** for adding/removing apps

### One concern per commit

A commit carries a single semantic change. If the subject line needs "and", or the
body explains two unrelated things, it is two commits. A `fix(ai):` to a HelmRelease
and an edit to this file are never the same commit, however close together they
happened.

Stage deliberately: `git add <specific paths>`, never `git add -A` or `git add .`.
Only the files belonging to the change being committed, even when other edits are
sitting in the tree — they may be someone else's work in progress.

Split before committing rather than after. Once pushed, fixing it means rewriting
published history, which needs the repo owner's say-so.

Before implementing a new app or configuration pattern, check the
[onedr0p/home-ops](https://github.com/onedr0p/home-ops) repo as a reference.

---

## Flux Reconciliation

Flux is configured with a GitHub webhook — reconciliation triggers immediately on push. Do not tell the user to "wait X minutes for Flux to reconcile."

---

## What NOT to Do

- Do not use `Ingress` resources — use `HTTPRoute`
- Do not commit `*.sops.yaml` files without encrypting them first
- Do not use `chart:` inline in HelmReleases — use `chartRef` pointing to an `OCIRepository`
- Do not pin images by tag only — always include the SHA256 digest
- Do not add `runAsRoot: true` or skip security context — harden all containers
- Do not create a new `OCIRepository` for app-template — use the shared one in `components/common/`
- Do not skip `# yaml-language-server: $schema=...` headers on YAML files
- Do not use `latest` tags for any container image
- Do not add a `NetworkPolicy` or `CiliumNetworkPolicy` by default. Access control in
  this cluster is the gateway plus Authelia; a policy that only restates that adds
  drift risk and maintenance for no security gain.

  Add one only when a workload holds a **network capability the rest of the cluster
  should not be able to borrow**, and state which one in a comment on the policy:
  - it fetches arbitrary URLs on request, so it doubles as an open proxy (SSRF,
    egress laundering)
  - it holds credentials or privileges that make it worth pivoting through

  "Defence in depth" on its own is not a justification — name the capability or
  don't write the policy.

  Prefer `egressDeny` layered on open egress (`enableDefaultDeny.egress: false`)
  over allow-listing: it fails open on the path you forgot rather than breaking the
  app, and it keeps the diff readable. Every CIDR is site-specific — see
  `network_mtu_topology` / the VLAN map before copying one from upstream.

  Existing policies, both justified under that test — do not delete as drift:
  - `actions-runner-system/.../runners/home-ops/networkpolicy.yaml` — the runner
    keeps cluster-admin and `os:admin` and executes fork PRs; fenced off the LAN
  - `default/searxng/app/ciliumnetworkpolicy.yaml` — unauthenticated and fetches
    arbitrary URLs; restricts who may call it and fences it off the LAN

- Do not suffix Secret names with `-secret` — use the app name directly (e.g. `name: myapp` not `name: myapp-secret`)
