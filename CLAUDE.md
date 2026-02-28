# AGENTS.md — AI Agent Guide for home-ops

This is a Kubernetes homelab GitOps monorepo managed with Flux v2 on Talos Linux.
Read this file before making any changes.

---

## Project Overview

| Layer | Technology |
|---|---|
| OS | Talos Linux v1.12.4 (immutable, API-driven) |
| Kubernetes | v1.35.1 |
| GitOps | Flux v2 (flux-operator + flux-instance) |
| CNI | Cilium (BGP, native routing, kube-proxy replacement) |
| Ingress | Envoy Gateway (Kubernetes Gateway API) |
| Storage | Rook-Ceph (block) + OpenEBS (local hostpath) |
| Backup | VolSync + Kopia → MinIO S3 |
| Database | CloudNative-PG (PostgreSQL 18, HA) |
| Secrets | SOPS + Age + PGP |
| Helm charts | bjw-s/app-template (OCI) for nearly all apps |
| Updates | Renovate (hourly GitHub Actions) |
| Auth | Authelia + LLDAP |

---

## Repository Layout

```
kubernetes/
├── flux/cluster/ks.yaml        # Flux entrypoint → kubernetes/apps/
├── components/                 # Reusable Kustomize components
│   ├── common/                 # Namespace, OCI repos, SOPS secret, Flux alerts
│   ├── ext-auth/               # Authelia external auth (Envoy SecurityPolicy)
│   ├── nfs-scaler/             # KEDA autoscaler for NFS-dependent pods
│   ├── persistence/            # PVC + VolSync backup/restore templates
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
`kube-system`, `media`, `network`, `observability`, `openebs-system`, `rook-ceph`,
`security`, `system-upgrade`, `volsync-system`

---

## Universal App Pattern

Every app follows this exact two-file pattern. Study an existing app (e.g.,
`kubernetes/apps/default/vaultwarden/`) before adding a new one.

### `ks.yaml` — Flux Kustomization

```yaml
# yaml-language-server: $schema=https://kubernetes-schemas.pages.dev/kustomize.toolkit.fluxcd.io/kustomization_v1.json
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
    - ../../../../components/persistence   # if app needs PVC + VolSync backup
    - ../../../../components/ext-auth      # if app needs Authelia auth
    - ../../../../components/nfs-scaler   # if app needs NFS (media/downloads)
  dependsOn:
    - name: rook-ceph-cluster              # if using ceph-block storage
      namespace: rook-ceph
    - name: cloudnative-pg                 # if using PostgreSQL
      namespace: database
    - name: volsync                        # if using persistence component
      namespace: volsync-system
  postBuild:
    substituteFrom:
      - kind: Secret
        name: cluster-secrets
    substitute:
      APP: <app>
      CAPACITY: 5Gi                        # if using persistence component
```

### `app/helmrelease.yaml` — HelmRelease (app-template)

```yaml
# yaml-language-server: $schema=https://kubernetes-schemas.pages.dev/helm.toolkit.fluxcd.io/helmrelease_v2.json
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
              tag: <version>@sha256:<digest>   # ALWAYS pin both tag AND digest
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
    ingress: {}        # NOT used — use HTTPRoute instead (see Networking below)
```

### `app/kustomization.yaml`

```yaml
# yaml-language-server: $schema=https://json.schemastore.org/kustomization
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - helmrelease.yaml
  - secret.sops.yaml   # only if secrets exist
```

---

## Networking

**Do NOT use `Ingress` resources.** This cluster uses Kubernetes Gateway API exclusively.

### Gateways

| Gateway | IP | Use for |
|---|---|---|
| `envoy-external` | `10.44.0.1` | Publicly accessible services (via Cloudflare Tunnel) |
| `envoy-internal` | `10.44.0.2` | LAN-only services |

Both gateways are in namespace `network`.

### HTTPRoute example

```yaml
# yaml-language-server: $schema=https://kubernetes-schemas.pages.dev/gateway.networking.k8s.io/httproute_v1.json
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: <app>
spec:
  parentRefs:
    - name: envoy-internal          # or envoy-external
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
# yaml-language-server: $schema=https://kubernetes-schemas.pages.dev/v1/secret.json
apiVersion: v1
kind: Secret
metadata:
  name: <app>-secret
stringData:
  SECRET_KEY: "value"
```

### Global variables (injected into all Kustomizations via `cluster-secrets`)

These are available via `postBuild.substituteFrom` and can be used as `${VAR}`:
- `${DOMAIN}` — homelab domain
- `${CLOUDFLARE_TUNNEL_ID}`
- `${EMAIL_ADDRESS_1}`
- `${VOLSYNC_RESTIC_PASSWORD}`, `${VOLSYNC_MINIO_ACCESS_KEY}`, `${VOLSYNC_MINIO_SECRET_KEY}`

---

## Persistence (VolSync + PVC)

For apps that need persistent storage with automatic backups, add the `persistence`
component in `ks.yaml` and set:

```yaml
substitute:
  APP: <app>          # Used as PVC name and VolSync resource names
  CAPACITY: 5Gi       # PVC size (default if omitted)
```

The component creates:
- A `PersistentVolumeClaim` named `<app>` using `ceph-block` StorageClass
- A `ReplicationSource` (hourly backup to MinIO via Kopia)
- A `ReplicationDestination` (for restore)

For NFS-mounted media (downloads/media namespace), use `local-hostpath` StorageClass
and add the `nfs-scaler` component.

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

## Validation

Before committing, validate your YAML:

```sh
# Validate Kubernetes manifests against schemas
bash scripts/kubeconform.sh

# Check for SOPS files that should be encrypted but aren't
bash scripts/sops-mismatch.sh

# Lint YAML
yamllint .

# Full Flux validation (requires flux-local installed)
flux-local test --path kubernetes/
```

CI runs `kubeconform`, `yamllint`, `flux-local test`, and `flux-local diff` on all PRs.

---

## Just Commands

```sh
just talos apply-node <ip>      # Apply Talos config to a node
just talos upgrade-node <ip>    # Upgrade Talos on a node
just kube <kubectl args>        # Run kubectl with the cluster kubeconfig
just bootstrap <step>           # Bootstrap steps (talos/k8s/namespaces/resources/apps)
```

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
