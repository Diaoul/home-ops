_[How to write this description](https://github.com/Diaoul/home-ops/blob/main/.github/pull-requests.md)_

## 🎯 Summary

<!-- One paragraph: what this changes and why it exists. Keep it — it is the abstract the rest of the body expands on. -->

## 🔑 Key decisions

<!--
Only choices a reviewer could reasonably disagree with. Delete this whole section when there are none; never pad it.
A bold one-line statement, then the reasoning in a paragraph that ends with how common the choice is — one of
`n/N surveyed`, `repo precedent: <path>`, `upstream default (<link>)`, `no precedent — first here`, `no majority — n/N vs m/N`.
Name the survey that produced a count. A rejection is a decision too, phrased negatively, as below.

**No `ext-auth`.**
Immich has its own accounts and its own mobile clients, so a Kanidm login in front of it breaks them. 0/10 surveyed apps put it behind ext-auth.
-->

## 📦 What changes

<!-- Group by area — an app, a component, a namespace — not a file dump. Delete when the summary already says it in full, such as a one-line version bump. -->

## ⚠️ Before merging

<!-- Manual steps Flux cannot do (a value only the owner can supply, a directory on the NAS, a DNS record), and what this change makes hard to undo: a PVC's dataSourceRef is immutable, a storage-class move is one way, a CRD upgrade is not reversible. Delete when empty. -->

## 🔗 Related

<!-- `Closes #123`, `depends on #456`, or the stack order when this is one pull request of several. Delete otherwise. -->
