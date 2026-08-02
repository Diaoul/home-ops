# Talos Patching

Machine configs are assembled by [topf](https://postfinance.github.io/topf/) from
`topf.yaml` plus the strategic merge patches in this directory.

<https://www.talos.dev/latest/talos-guides/configuration/patching/>

## Patch Directories

Patches merge in this order, alphabetically within each directory, with later
patches taking precedence:

- `all/`: applied to every node
- `control-plane/`: applied to control-plane nodes
- `worker/`: applied to worker nodes
- `node/${hostname}/`: applied to the node with the specified name

Filenames follow the numbering used by
[onedr0p/cluster-template](https://github.com/onedr0p/cluster-template), so the
`60-encryption` and `61-kernel-modules` slots are left free for those upstream
patches; local additions start at `62-`.

Files ending in `.yaml.tpl` are Go-templated per node; see the
[topf configuration model](https://postfinance.github.io/topf/main/configuration-model/)
for the available template variables. Cluster-wide values (cert SANs, CIDRs) live
under `data:` in `topf.yaml` and are reachable as `.Data.<key>`.

## What is and is not committed

| Path | Committed | Note |
|---|---|---|
| `topf.yaml`, `schematic.yaml`, `all/`, `control-plane/` | yes | no secrets |
| `secrets.sops.yaml` | yes | SOPS-encrypted Talos secrets bundle (PGP + age) |
| `talosconfig` | no | generated with `just talos talosconfig` |
| `rendered/` | no | plaintext machine configs, `just talos render` |
| `images/` | no | downloaded installer ISOs |

## Adding or renumbering a node

Node IPs are hardcoded in one place outside `talos/`: the GitHub Actions runner's
CiliumNetworkPolicy at
`kubernetes/apps/actions-runner-system/actions-runner-controller/runners/home-ops/networkpolicy.yaml`
excepts `10.0.3.24/29` (`10.0.3.24`–`10.0.3.31`) so the runner can reach the Talos
API for `talosctl image pull`. The range is tighter than the `10.0.3.0/24` SERVER
VLAN on purpose — the NAS shares that VLAN and is intentionally out of reach.

A node outside `.24`–`.31` makes the `Image Pull` workflow hang and time out
against that node rather than fail with a useful error. Widen the `except` entry
when you add one.

## Upgrades

Talos version upgrades are driven **in-cluster by tuppr** (`TalosUpgrade` in
`kubernetes/apps/system-upgrade/tuppr/upgrades/talosupgrade.yaml`), which gates
each node on Ceph and kopiur health. `talosVersion` in `topf.yaml` only selects
the installer image used by `topf apply`; Renovate bumps both in one PR.

`just talos upgrade` / `upgrade-node` exist as a manual fallback.
