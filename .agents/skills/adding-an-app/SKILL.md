---
name: adding-an-app
description: >
  Use when adding an app to home-ops or changing how one is wired: the ks.yaml, HelmRelease
  and kustomization templates, routes and ext-auth, persistence and storage classes, a
  PostgreSQL database, secrets, and when a network policy is justified.
---

# Adding an app

## Files

Every app follows this pattern. Study an existing one (e.g.
`kubernetes/apps/default/vaultwarden/`) and check
[onedr0p/home-ops](https://github.com/onedr0p/home-ops) (`git show onedr0p/main:<path>`)
before adding a new one.

### `ks.yaml` — Flux Kustomization

```yaml
# yaml-language-server: $schema=https://k8s-schemas.home-operations.com/kustomize.toolkit.fluxcd.io/kustomization_v1.json
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: <app>                              # no namespace: apps/<namespace>/kustomization.yaml sets it
spec:
  targetNamespace: <namespace>
  interval: 1h
  retryInterval: 1m
  timeout: 5m
  path: ./kubernetes/apps/<namespace>/<app>/app
  prune: true
  sourceRef:
    kind: GitRepository
    name: flux-system
    namespace: flux-system
  wait: false                              # true only if another Kustomization dependsOn this one being healthy
  # Include ONLY the components that this app actually needs:
  components:
    - ../../../../components/persistence   # if app needs PVC + kopiur backup
    - ../../../../components/ext-auth      # if app needs a Kanidm login
    - ../../../../components/zeroscaler    # if app mounts NFS (media/downloads)
  dependsOn:
    - name: rook-ceph-cluster              # if using ceph-block storage
      namespace: rook-ceph
    - name: kopiur-repository              # if using persistence component
      namespace: kopiur-system
    - name: cloudnative-pg-databases       # if using PostgreSQL
      namespace: database
  postBuild:
    substituteFrom:
      - name: cluster-secrets
        kind: Secret
    substitute:
      APP: <app>
      CAPACITY: 5Gi                        # if using persistence component
```

### `app/helmrelease.yaml` — HelmRelease (app-template)

```yaml
# yaml-language-server: $schema=https://raw.githubusercontent.com/bjw-s-labs/helm-charts/main/charts/other/app-template/schemas/helmrelease-helm-v2.schema.json
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: <app>
spec:
  interval: 1h
  chartRef:
    kind: OCIRepository
    name: app-template                     # per-namespace copy from components/common
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
    route:
      app:
        hostnames:
          - <app>.${DOMAIN}
        parentRefs:
          - name: envoy-internal           # or envoy-external
            namespace: network
```

### `app/kustomization.yaml`

```yaml
# yaml-language-server: $schema=https://json.schemastore.org/kustomization
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ./helmrelease.yaml
  - ./secret.sops.yaml   # only if secrets exist
```

## Networking

**Do NOT use `Ingress` resources.** This cluster uses Kubernetes Gateway API exclusively.

### Gateways

| Gateway | IP | Use for |
|---|---|---|
| `envoy-external` | `10.44.0.1` | Publicly accessible services (via Cloudflare Tunnel) |
| `envoy-internal` | `10.44.0.2` | LAN-only services |

Both gateways are in namespace `network`.

### Routes

For an app-template app, declare the route in the HelmRelease's `route:` values (see
the template above); the chart renders the HTTPRoute and points it at the app's Service.

Write a standalone `app/httproute.yaml` only when the backend is not an app-template
release (e.g. `flux-system/flux-instance`, `network/singularity`), and reference it in
`app/kustomization.yaml`:

```yaml
# yaml-language-server: $schema=https://k8s-schemas.home-operations.com/gateway.networking.k8s.io/httproute_v1.json
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: <app>
spec:
  parentRefs:
    - name: envoy-internal          # or envoy-external
      namespace: network
  hostnames:
    - <app>.${DOMAIN}
  rules:
    - backendRefs:
        - name: <service>
          port: <port>
```

### ext-auth (Kanidm via oauth2-proxy)

To put an app behind a Kanidm login, add the `ext-auth` component in `ks.yaml`. It attaches
a SecurityPolicy to every HTTPRoute labelled `app.kubernetes.io/instance: ${APP}` (app-template
sets it on each route it renders) that sends each request to oauth2-proxy, which bypasses only
`/ping`. Logins finish on `auth.${DOMAIN}` and return to the app, so nothing else changes,
unless the app lives in a namespace missing from
`kubernetes/apps/security/oauth2-proxy/app/referencegrant.yaml`.

To leave an app's API reachable without a login, and only when the app checks its own API
key there (test it: an unauthenticated request must get a 401 or 403), add a second route
labelled `ext-auth.home-ops/skip: "true"` matching only those paths; the policy skips routes
with that label. See `media/sonarr` for the pattern.

## Secrets

A secret goes in `app/secret.sops.yaml`, named after the app; write it with the
`creating-a-sops-secret` skill. `cluster-secrets` is injected into every Kustomization
through `postBuild.substituteFrom`, so these are available as `${VAR}`: `${DOMAIN}`,
`${CLOUDFLARE_TUNNEL_ID}`, `${EMAIL_ADDRESS_1}`.

## Persistence (kopiur + PVC)

For apps that need persistent storage with automatic backups, add the `persistence`
component in `ks.yaml` and set:

```yaml
substitute:
  APP: <app>          # Used as PVC name and kopiur resource names
  CAPACITY: 5Gi       # PVC size (default if omitted)
```

The component creates:
- A `PersistentVolumeClaim` named `<app>` using `ceph-block` StorageClass, populated
  from a `Restore`
- A `SnapshotPolicy` + `SnapshotSchedule` (snapshot every 3 hours to the NAS via kopiur/Kopia)
- A `Restore` (populates the PVC from the latest snapshot)

Note the PVC's `dataSourceRef` is immutable: changing it requires deleting and
recreating the PVC.

For NFS-mounted media (downloads/media namespace), use `miroir-local` StorageClass
and add the `zeroscaler` component. It is a native HPA (min 0, max 1) driven by the
blackbox `nfs_probe` via prometheus-adapter; set `CONTROLLER: StatefulSet` when the
workload is not a Deployment.

Storage classes: `ceph-block` (default, replicated RBD), `miroir-local` (node-local
LVM thin, no DRBD traffic), `miroir-replicated` (2-way DRBD, keep it off control
planes; their system disks are already the etcd fdatasync bottleneck).

## PostgreSQL

Databases are declared with the CNPG `Database`/`DatabaseRole` CRDs, not with a
`postgres-init` init container. All three resources must live in the cluster's
namespace, so they sit together in `kubernetes/apps/database/cloudnative-pg/databases/`
and the postgres superuser password never leaves the `database` namespace.

For an app needing a database:

1. Add `<app>.yaml` to `databases/` with a `DatabaseRole` (`login: true`,
   `passwordSecret: <app>-db`) and a `Database` (`owner: <app>`).
2. Add `<app>.sops.yaml` there too: a `kubernetes.io/basic-auth` Secret named
   `<app>-db`, labelled `cnpg.io/reload: "true"`, holding `username` and `password`.
3. Reference both from `databases/kustomization.yaml`.
4. Put the app's own connection string or password in its usual app secret — the same
   password, since there are no cross-namespace secrets, so a rotation touches both
   files.
5. `dependsOn: cloudnative-pg-databases` (namespace `database`) in the app's `ks.yaml`.

Reference: `kubernetes/apps/database/cloudnative-pg/databases/` plus any of its
consumers (`ai/litellm`, `downloads/autobrr`, `default/miniflux`, `media/romm`).

Do not write a `failed:` health expression for these kinds. A new `passwordSecret`
reaches the cluster's Role only on CNPG's next reconcile, so a fresh `DatabaseRole`
sits at `applied: false` with an RBAC error for a few seconds; treating that as a
failure makes Flux fail the Kustomization early and every dependent app alert.

Reclaim policies default to `retain` — leave them out.

## Network policies

Do not add a `NetworkPolicy` or `CiliumNetworkPolicy` by default. Access control in
this cluster is the gateway plus ext-auth; a policy that only restates that adds
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

Existing policies, all justified under that test — do not delete as drift:
- `actions-runner-system/.../runners/home-ops/networkpolicy.yaml` — the runner
  keeps cluster-admin and `os:admin` and executes fork PRs; fenced off the LAN
- `default/searxng/app/ciliumnetworkpolicy.yaml` — unauthenticated and fetches
  arbitrary URLs; restricts who may call it and fences it off the LAN
- `security/kanidm/app/ciliumnetworkpolicy.yaml` — the IdP, trusting
  X-Forwarded-For from any source; only envoy-external and kaniop may reach it
