# Rendering a HelmRelease with flate

When a chart version or a HelmRelease's values change, render the
HelmRelease with this repository's values, from a checkout of the pull
request's head, with `kubernetes` as the path and the namespace selected.

A pull request is read without touching the user's working tree: fetch it
into a scratch worktree and remove both afterwards.

```
git fetch origin pull/<n>/head:refs/tmp/pr-<n>
git worktree add --detach <scratch>/pr-<n> refs/tmp/pr-<n>
# ... review from <scratch>/pr-<n> ...
git worktree remove --force <scratch>/pr-<n> && git update-ref -d refs/tmp/pr-<n>
```

Diff against the merge-base, not `origin/main`. A Renovate branch is often
days behind `main`, and against `main` every update merged since shows up
as a revert in this pull request:

```
flate diff hr <name> --base "$(git merge-base origin/main HEAD)" --path kubernetes -n <namespace> --no-progress -o diff
```

To read the head alone:

```
flate build hr <name> --path kubernetes -n <namespace> --no-progress
```

flate reports every failure in the namespace, not only the requested
HelmRelease's, and exits nonzero for any of them. A failure is a finding
on the changed line only when it belongs to the HelmRelease under review
and the change caused it: a value the chart's schema rejects, a template
that errors on this repository's values. A failure of another
HelmRelease, or a source that could not be fetched, says nothing about the
change.

A render that succeeds is an offline approximation of what the cluster
applies: CRDs and Secrets are left out, patches Flux applies from a parent
Kustomization are not (the HelmRelease defaults in
`kubernetes/flux/cluster/ks.yaml` among them), and templates that branch on
Kubernetes capabilities see flate's bundled version, not the cluster's.
Within that, take the label values, resource names and ports the search
for dependents needs from the render rather than from a reading of the
template, and narrow it with `--show-only <template path>` when the whole
output is too long.
