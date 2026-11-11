# Pull requests

The description is what the review reads first, and the only record of why a
change looks the way it does a year later. `.github/PULL_REQUEST_TEMPLATE.md`
carries the shape; this file carries the rules that do not fit in a comment.

Every section of the template can be deleted when it has nothing to say. Three
real sections beat five padded ones, and a template that cannot be trimmed gets
deleted wholesale by the next person in a hurry.

## What counts as a key decision

A choice a reviewer could reasonably disagree with: if it had gone the other
way, would the review have a comment? If not, it is not a decision, it is the
platform.

- Not a key decision: "we used `bjw-s/app-template`", "we added a Deployment",
  "the image tag is pinned with its digest" — `AGENTS.md` already fixes those.
- A key decision: a dedicated database cluster instead of the shared one,
  node-local storage instead of replicated, no ext-auth in front of an app that
  has its own accounts.
- A rejection is a decision, written negatively: "**No `ext-auth`.**" The
  reviewer would have asked, so the answer goes in the same list. There is no
  separate "left out on purpose" section.

Each decision is a bold one-line statement followed by the reasoning in prose,
and ends with how common the choice is. No table: reasoning squeezed into a
cell becomes a fragment nobody can check.

## Saying how common a choice is

A key decision ends in one of these. A bare "most common" is a defect, because
a reader cannot verify it and neither can the reviewer.

- `7/7 surveyed` — a ratio, from a survey that the same paragraph names.
- `repo precedent: kubernetes/apps/media/romm` — this repository already does it.
- `upstream default (<link>)` — the upstream project chose it, linked.
- `no precedent — first here` — honest, and still a decision.
- `no majority — 4/10 vs 6/10` — a split, both sides counted.

A count is reproducible or it is decoration. The paragraph names the method, so
a reader can rerun it: the script or query used, the set of repositories
searched, and the date it ran.

The denominator is the repositories that actually **contain the app**, never the
candidates that were merely scanned. Counting the scan set produced a false
majority in #9182; the two numbers differ by every repository that has no
manifest for the app. Say which repositories were excluded and why — no
retrievable storage class, no manifest, unreadable — so the denominator can be
rebuilt from the description alone.

## When to stack pull requests

Stack when a later pull request's manifest would be invalid, unusable or
misleading without the earlier one:

- a component change and the first consumer of it — the consumer cannot land first;
- a two-phase migration, such as an app moved to a new database cluster before
  the old one is removed;
- a CRD bump before the manifests that need the new field.

`gh stack` administers this: `gh extension install github/gh-stack`, not
installed by default. It rebases each branch onto the one below it and opens
them with the right base, so the reviewer reads them in order.

The counterpart matters more here: do not stack because the changes are merely
related. The resources in this repository are declarative and Flux orders them
with `dependsOn`, so a database cluster, its `Database` and the app consuming it
merge as one pull request. Stacking adds a merge order someone has to honour,
and buys nothing when no step is imperative. One pull request is the default;
a stack is the exception it has to earn.

## Irreversibility

Four changes here do not roll back by reverting the commit. They belong under
"Before merging" in the change's own words, including what to do instead:

- **A PVC's `dataSourceRef` is immutable.** It is set when the volume is
  created, so cloning from a snapshot or another volume means a new PVC and a
  copy of the data.
- **A PVC cannot move between storage classes.** Reclaim policies and
  `storageClassName` are effectively fixed; the move is a copy into a new
  volume, or starting over.
- **A CRD upgrade is not reversible.** HelmReleases here upgrade CRDs with
  `crds: CreateReplace` (`kubernetes/flux/cluster/ks.yaml`): the previous
  version's schema is replaced, and a downgrade does not restore it.
- **Secret rotation is one way.** Once the old credential is revoked, nothing
  rolls back to it; every consumer restarts on the new value, and the old one
  survives only in the git history of the encrypted file.

## Rules that live elsewhere

`AGENTS.md` owns the invariants and the procedures this file does not repeat:
image tag and digest, security context and uid/gid 568, no `Ingress`, SOPS never
in plaintext, YAML style, and commit conventions. Read it before writing the
description, and link to it rather than copying a rule into a second or third
place — a rule with three copies has three futures.

Validation is CI's job, not the description's. Do not paste command output into
the body: a green check is evidence, a paragraph claiming one is not.
