# System Upgrade Controller

[Automated upgrades][docs] of k3s within the cluster. See
[the repository][repo] for more details.

* [system-upgrade-controller.yaml](system-upgrade-controller.yaml) is the
  manifest which makes this work. Copied from [the repository][repo]
* [k3s-plan.yaml](k3s-plan.yaml) contains the upgrade plans for the server and
  the agent with their associated release channel. Based on the example plans
  from [the repository][repo]

[docs]: https://rancher.com/docs/k3s/latest/en/upgrades/automated/
[repo]: https://github.com/rancher/system-upgrade-controller/
