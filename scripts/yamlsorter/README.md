# yamlsorter

Reorders keys in this repo's Flux manifests so diffs stay readable. Key order carries
no meaning to Kubernetes, so it is free to standardise — and worth standardising,
because an unordered `spec` makes every review hunt for the field it cares about.

## Usage

```sh
python scripts/yamlsorter/yamlsorter.py kubernetes             # sort in place
python scripts/yamlsorter/yamlsorter.py kubernetes --check     # report only, exit 1 if unsorted
python scripts/yamlsorter/yamlsorter.py kubernetes --audit     # list keys no template covers
```

Walking a directory picks up `helmrelease.yaml`, `kustomization.yaml` and `ks.yaml`
(`--names` overrides). A file named explicitly is processed whatever it is called.
Anything the templates do not cover — Secrets, HTTPRoutes, OCIRepositories — is
skipped, not an error.

lefthook runs it on staged manifests before `yamlfmt`.

## Templates

`scripts/config/<type>.yaml.tpl` holds one skeleton manifest per document type. Only its
**keys** are read; the values are placeholders. Keys absent from a template keep their
relative order and sort after the templated ones, so a template never has to be
exhaustive — `--audit` lists what it is missing.

| Template | Applies to |
|---|---|
| `flux-kustomization.yaml.tpl` | `kustomize.toolkit.fluxcd.io` Kustomizations (`ks.yaml`) |
| `kustomization.yaml.tpl` | `kustomize.config.k8s.io` Kustomizations |
| `component.yaml.tpl` | Kustomize Components |
| `helmrelease-apptemplate.yaml.tpl` | HelmReleases whose `chartRef` is `app-template` |
| `helmrelease.yaml.tpl` | every other HelmRelease |

A HelmRelease resolves to `helmrelease-<chart>.yaml.tpl` (hyphens stripped) by `chartRef.name`,
falling back to `helmrelease.yaml.tpl`. Adding `helmrelease-cilium.yaml.tpl` is enough to give
Cilium its own ordering.

A `"*"` key in a template stands for whatever name the manifest uses at that level, so
one `containers."*"` entry orders every container in the repo.

The `.tpl` suffix is load-bearing. A template is a well-formed Kustomization or
HelmRelease, so under a plain `.yaml` name the repo-wide Flux scanners render it as a
real resource — Konflate read `dependsOn: [{name: dependency}]` out of the placeholder
and reported 95 dependency failures.

## Tests

```sh
python -m pytest scripts/yamlsorter
```
