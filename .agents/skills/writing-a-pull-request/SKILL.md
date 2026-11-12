---
name: writing-a-pull-request
description: >
  Use when opening a pull request in home-ops or writing its description. Covers the five
  sections and the rules behind them: counting peer practice, when to stack pull requests,
  keeping a pull request's history, and which changes are one-way doors.
---

# Writing a pull request

There is no template: this file carries both the shape and the rules behind it. Five sections,
three of them optional, and each one has a rule for when it earns its place.

## The shape

```markdown
## 🎯 Summary

## 🔎 What to review

## 🔑 Key decisions

### <the decision, as a statement>

**Why:** <the constraint that forces it>
**Precedent:** <what others do, or "first here">

## ⚠️ Beware

## 🔗 Related
```

- **`🎯 Summary`** — one or two sentences. Technical terms are fine: this is the abstract, not
  marketing copy. What it adds or changes, the route or boundary it lives behind, and any piece
  you had to add to make it work. No version numbers and no image digests, they rot in prose.
- **`🔎 What to review`** — two to four bullets: where a mistake would matter, and what correct
  looks like. Not a file list, the diff has that. Drop the section only when the change is
  trivial.
- **`🔑 Key decisions`** — one `###` per decision, titled with the decision itself, so a reviewer
  can skim the headings and stop at the one they disagree with. `Why:` is the constraint in two
  or three sentences, not the story. `Precedent:` is the evidence — how many repositories do it,
  repo precedent, an upstream default, or "first here". Rejections and deferrals are decisions
  too, same shape. Drop the section when nothing in it is arguable.
- **`⚠️ Beware`** — anything to know before this lands: a manual step Flux cannot do, or
  behaviour that is irreversible or destructive. Drop the section when there is nothing; never
  write a line saying there is nothing to beware of.
- **`🔗 Related`** — only when applicable: `Closes #123`, depends on #456, or the stack order.

## Counting peer practice

A `**Precedent:**` figure is evidence, not decoration.

- The denominator is the repositories that **contain the app**, never the candidates that were
  merely scanned. Twenty popular repos scanned, ten of them installing the app, is 10/… —
  not 20/….
- Say which repositories were left out and why — no manifest, an unreadable secret, no
  declared value — so the denominator can be rebuilt from the description alone.
- A bare "most common" is a defect: nobody can check it.
- Attach the survey output as a collapsed `<details><summary>Peer survey</summary>` block in
  the body, rather than narrating the tooling.

## When to stack pull requests

Stack when a later pull request would be **invalid, unusable or misleading** without the
earlier one:

- a component change and the first consumer of it — the consumer cannot land first;
- a two-phase migration, such as moving to a new database cluster before removing the old one;
- a CRD bump before the manifests that need the new field.

`gh stack` administers it: `gh extension install github/gh-stack`, not installed by default.
`gh stack submit` opens one pull request per branch, each based on the branch below it, so a
reviewer sees only that layer's diff.

The counterpart matters more here: do not stack because the changes are merely related. The
resources in this repository are declarative and Flux orders them with `dependsOn`, so a
database cluster, its `Database` and the app consuming it merge as one pull request. One pull
request is the default; a stack is the exception it has to earn.

## History, not rewrites

A pull request keeps its commits: intermediate ones record the decisions, and contributor pull
requests are squash-merged by hand, so that history is discarded at the end if it is noise —
there is nothing to gain by rewriting it first. A follow-up commit answering review is
normal — it shows what was asked and what changed.

That is not `AGENTS.md`'s one-concern-per-commit rule read backwards: that one keeps two
concerns out of one commit, this one keeps commits from being erased to make a branch look
tidy. Legible history, not the most commits — a three-line remark that belongs in the same
edit does not earn a commit of its own.

Never close a pull request as superseded. When history genuinely must change — a wrong
sign-off — rewrite the branch in place and force-push; any force-push needs the repository
owner's say-so, as `AGENTS.md` already requires. If the environment refuses the force-push, say
so on the pull request and leave it open rather than starting a replacement.

A leaked secret is not one of those cases. Once it has been pushed, forks, caches and this pull
request's own view of the old commits keep it, so rewriting the branch fixes nothing: rotate the
credential, then push the new encrypted value as an ordinary commit.

## One-way doors

Four changes do not roll back by reverting the commit. They belong under `⚠️ Beware`, in the
change's own words, including what to do instead:

- **A PVC's `dataSourceRef` is immutable** — `AGENTS.md` already says so under Persistence;
  changing it means a new PVC and a copy of the data.
- **A PVC cannot move between storage classes** — the move is a copy into a new volume, or
  starting over.
- **A CRD upgrade is not really reversible** — HelmReleases here upgrade CRDs with
  `crds: CreateReplace` (`kubernetes/flux/cluster/ks.yaml`), so a downgrade does put the old
  schema back. What it cannot undo is the objects already stored under the new version
  (`status.storedVersions`), which the old schema may be unable to serve or may reject.
- **Secret rotation is one way** — once the old credential is revoked, nothing rolls back into a
  working state. The new value lives in the current file and in the cluster; a revert brings
  back the old encrypted value from history, and that credential is already revoked. Roll
  forward with another new value instead of reverting.
