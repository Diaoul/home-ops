---
name: writing-a-pull-request
description: >
  The repo-specific rules a pull request description needs that the template cannot hold:
  counting peer practice, when to stack pull requests, keeping a pull request's history, and
  which changes are one-way doors.
---

# Writing a pull request

`.github/PULL_REQUEST_TEMPLATE.md` carries the shape and the rules an author needs while
writing. Four rules do not fit in a comment and live here.

## Counting peer practice

A `**Usage:**` figure is evidence, not decoration.

- The denominator is the repositories that **contain the app**, never the candidates that were
  merely scanned. Twenty popular repos scanned, ten of them installing the app, is 10/… —
  not 20/….
- Say which repositories were left out and why — no manifest, an unreadable secret, no
  declared value — so the denominator can be rebuilt from the description alone.
- A bare "most common" is a defect: nobody can check it.
- Attach the survey output to the pull request rather than narrating the tooling in the body.

## When to stack pull requests

Stack when a later pull request would be **invalid, unusable or misleading** without the
earlier one:

- a component change and the first consumer of it — the consumer cannot land first;
- a two-phase migration, such as moving to a new database cluster before removing the old one;
- a CRD bump before the manifests that need the new field.

`gh stack` administers it: `gh extension install github/gh-stack`, not installed by default.

The counterpart matters more here: do not stack because the changes are merely related. The
resources in this repository are declarative and Flux orders them with `dependsOn`, so a
database cluster, its `Database` and the app consuming it merge as one pull request. One pull
request is the default; a stack is the exception it has to earn.

## History, not rewrites

A pull request keeps its commits: intermediate ones record the decisions, and a squash-merge
discards them at the end if they are noise, so there is nothing to gain by rewriting them
first. A follow-up commit answering review is normal — it shows what was asked and what
changed.

That is not `AGENTS.md`'s one-concern-per-commit rule read backwards: that one keeps two
concerns out of one commit, this one keeps commits from being erased to make a branch look
tidy. Legible history, not the most commits — a three-line remark that belongs in the same
edit does not earn a commit of its own.

Never close a pull request as superseded. When history genuinely must change — a leaked
secret, a wrong sign-off — rewrite the branch in place and force-push; if the push is
blocked, report the block instead of opening a replacement.

## One-way doors

Four changes do not roll back by reverting the commit. They belong under `⚠️ Beware`, in the
change's own words, including what to do instead:

- **A PVC's `dataSourceRef` is immutable** — cloning from a snapshot or another volume means a
  new PVC and a copy of the data.
- **A PVC cannot move between storage classes** — the move is a copy into a new volume, or
  starting over.
- **A CRD upgrade is not reversible** — HelmReleases here upgrade CRDs with `crds: CreateReplace`
  (`kubernetes/flux/cluster/ks.yaml`), and a downgrade does not restore the old schema.
- **Secret rotation is one way** — once the old credential is revoked nothing rolls back; it
  survives only in the git history of the encrypted file.
