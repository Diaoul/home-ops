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

Each decision is a `###` heading that states the decision itself, so a reviewer
can skim the headings and stop at the one they disagree with, followed by two
bold leads:

```markdown
### A dedicated database cluster instead of the shared one

**Why:** the constraint that forces it, in two or three sentences.
**Usage:** the evidence — a count, repo precedent, the upstream default.
```

**Why** is the constraint, not the story: what breaks or costs more if the
choice went the other way, and why that is unacceptable here. **Usage** is the
part a reader can check, in the forms listed below.

Prose needs room. A table cell holds one clause, so reasoning squeezed into one
becomes a fragment nobody can question — the argument goes in the paragraph
under the heading.

A rejection is a decision, written in the same shape: "**No `ext-auth`.**" earns
a heading like any other, because the reviewer would have asked. So does a
deferral — "**`zeroscaler`, deferred to a follow-up.**" — which is a legitimate
decision: say what blocks it and what lands it, so nobody reads a stacked
omission as an oversight.

## Saying how common a choice is

**Usage** says how common the choice is. A bare "most common" is a defect,
because a reader cannot verify it and neither can the reviewer.

- `7/7 surveyed` — a ratio, from a survey of the repositories that contain the app.
- `repo precedent: kubernetes/apps/media/romm` — this repository already does it.
- `upstream default (<link>)` — the upstream project chose it, linked.
- `no precedent — first here` — honest, and still a decision.
- `no majority — 4/10 vs 6/10` — a split, both sides counted.

The description carries the count, not the method: readers care about the
decision, not the tooling. The survey output — the repositories, the queries,
the raw hits — is attached to the pull request as a file, so anyone who wants to
check the number can open it.

The denominator is the repositories that actually **contain the app**, never the
candidates that were merely scanned. Counting the scan set produced a false
majority in #9182; the two numbers differ by every repository that has no
manifest for the app. Say which repositories were excluded and why — no
retrievable storage class, no manifest, unreadable — so the denominator can be
rebuilt from the attached output.

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
"Beware" in the change's own words, including what to do instead:

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

The point is to warn, not to reassure. A change with no irreversible behaviour
deletes the section instead of noting that it is reversible, because "this is
reversible" invites the reader to stop reading the warnings that do exist.

## Rules that live elsewhere

`AGENTS.md` owns the invariants and the procedures this file does not repeat:
image tag and digest, security context and uid/gid 568, no `Ingress`, SOPS never
in plaintext, YAML style, and commit conventions. Read it before writing the
description, and link to it rather than copying a rule into a second or third
place — a rule with three copies has three futures.

Validation is CI's job, not the description's. Do not paste command output into
the body: a green check is evidence, a paragraph claiming one is not.
