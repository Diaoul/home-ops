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

## Upgrades

Talos version upgrades are driven **in-cluster by tuppr** (`TalosUpgrade` in
`kubernetes/apps/system-upgrade/tuppr/upgrades/talosupgrade.yaml`), which gates
each node on Ceph and kopiur health. `talosVersion` in `topf.yaml` only selects
the installer image used by `topf apply`; Renovate bumps both in one PR.

`just talos upgrade` / `upgrade-node` exist as a manual fallback.
