---
name: cluster-health
description: >
  Full cluster health check for the home-ops Kubernetes cluster. Checks nodes, Flux, pods,
  storage, certs, database, networking, security, alerts, Gatus, Victoria Logs, events, and
  upgrade status. Use when user asks to check cluster health, run a health check, or diagnose
  cluster issues.
---

Run each check below in order. After all checks, print a summary table: area | status (✅/⚠️/❌) | one-line note. Only show ⚠️ or ❌ rows in the summary unless everything is green.

Run independent checks in parallel where possible.

## 1. Nodes

```sh
kubectl get nodes -o wide
```

Flag: any node not `Ready`, any pressure condition, version mismatch across nodes.

## 2. Flux

```sh
flux get all -A
```

Flag: any resource where `READY != True`. Ignore `SUSPENDED=True` resources.

## 3. Pods

```sh
kubectl get pods -A --no-headers | grep -vE '\s(Running|Completed|Succeeded)\s'
kubectl get daemonsets -A --no-headers | awk '$2 != $4 {print}'
```

Flag: CrashLoopBackOff, Error, OOMKilled, stuck Pending. Daemonsets where DESIRED != READY.

## 4. Rook-Ceph

```sh
kubectl get cephcluster -n rook-ceph -o jsonpath='{.items[0].status.ceph.health}'
kubectl get pvc -A --no-headers | grep -v Bound
```

Flag: anything other than `HEALTH_OK`. Any unbound PVCs.

### 4b. Stuck CSI unpublish (silent stale RBD mappings)

```sh
for p in $(kubectl get pods -n rook-ceph -l app=rook-ceph.rbd.csi.ceph.com-nodeplugin -o name); do
  n=$(kubectl get $p -n rook-ceph -o jsonpath='{.spec.nodeName}')
  l=$(kubectl logs $p -c csi-rbdplugin -n rook-ceph --since=15m 2>/dev/null | grep 'directory not empty')
  echo "$n ENOTEMPTY=$(echo -n "$l" | grep -c .) last=$(echo "$l" | tail -1 | awk '{print $2}')"
done
```

Flag: any node with a non-zero count. The window is 15m and the loop retries every ~2 min, so a live loop always shows ≥3; `last=` is there to confirm recency (log timestamps are **UTC** — compare against `date -u`, not local time). Don't widen the window: with a 1h lookback this check keeps reporting a node as broken for an hour after it's actually fixed. Nothing else in this skill catches it — the volume keeps working for its current pod, so pods, PVCs and Ceph health all stay green while the RBD image is silently pinned to that node forever.

**What it means:** `NodeUnpublishVolume` is failing with `remove /var/lib/kubelet/pods/<uid>/volumes/kubernetes.io~csi/<pv>/mount: directory not empty` and retrying every ~2 min. A leftover directory sits in the pod's `mount/` dir on local disk (app wrote at the volume root while unmounted). Unpublish never completes, so `NodeUnstageVolume` never runs, so the image stays krbd-mapped. The damage only surfaces later, when the pod reschedules to another node and hits `FailedMount ... rbd image ... is still being used`.

**Fix** — pull the pod UID and PV from the error line, confirm nothing is mounted there, then remove the leftover dir; kubelet finishes cleanup and GCs the pod dir within ~2 min:

```sh
kubectl exec <nodeplugin-pod> -c csi-rbdplugin -n rook-ceph -- grep -c '<pod-uid>' /proc/mounts   # MUST be 0
kubectl exec <nodeplugin-pod> -c csi-rbdplugin -n rook-ceph -- rmdir <mount-dir>/<leftover-dir>
```

If a pod is already stuck mounting elsewhere, also clear the stale mapping on the old node — see [[rwo-ceph-forcedelete-hazard]] for the umount/unmap sequence. Never `ceph osd blocklist add`.

## 5. miroir

```sh
kubectl get pods -n miroir-system --no-headers | grep -v Running
kubectl get miroirnodes
kubectl get miroirvolumes -A --no-headers | grep -v Ready
```

Flag: any pod not Running. Any `MiroirNode` missing its `default` pool, showing no
CAPACITY, or with a blank DRBD version — that node's `r-miroir` partition is missing or
its agent has not claimed it, and it silently stops being a placement candidate. Any
`MiroirVolume` not `Ready`, or reporting fewer replicas than its StorageClass asks for
(`1/1` for `miroir-local`, `2/2` for `miroir-replicated`).

## 6. Kopiur Backups

```sh
kubectl get snapshotschedule.kopiur.home-operations.com -A -o json \
  | jq -r '.items[]
      | "\(.metadata.namespace)/\(.metadata.name) cron=\(.spec.schedule.cron) last=\((.status.lastSchedule.at // "never")[0:19]) next=\((.status.nextSchedule.at // "-")[0:19]) fails=\(.status.consecutiveFailures) suspended=\(.spec.suspend // false)"'
kubectl get snapshots.kopiur.home-operations.com -A -o json \
  | jq -r '[.items[] | select(.status.phase != "Succeeded")
            | "\(.metadata.namespace)/\(.metadata.name) \(.status.phase)"] | .[]'
for k in snapshotpolicy snapshotschedule restore; do
  echo "$k: $(kubectl get $k.kopiur.home-operations.com -A --no-headers | wc -l)"
done
date -u +%Y-%m-%dT%H:%M:%SZ
```

Flag: any schedule that is `SUSPENDED`, has `consecutiveFailures > 0`, or whose `last=`
is older than the interval its own `cron=` implies (read the cron off the object — do not
assume a period). `next=` in the past by more than one interval means the scheduler has
stopped firing. Also flag any Snapshot stuck in a non-`Succeeded` phase across two runs —
a single `Running`/`Deleting` is just a run in flight.

The three counts should match each other (one policy, schedule and restore per stateful
app); the absolute number tracks how many apps use `components/persistence`, so compare
them to each other rather than to a fixed number.

Snapshots are retained on a GFS schedule, so a large total is expected — see
[[kopiur-retention-design]] before diagnosing accumulation.

**Transient churn is normal.** Each run creates a VolumeSnapshot, an ephemeral PVC and a
mover pod, then tears them down, which produces `VolumeFailedDelete` (PV deleted before
its VolumeAttachment detaches), `FailedScheduling` (mover waiting on the ephemeral PVC)
and `MissingDependency` (waiting for the VolumeSnapshot to become `readyToUse`) in
check 17. Expect roughly one of each per schedule per run. Only treat them as a fault if
PVs are stuck `Released`/`Failed` or a schedule's `consecutiveFailures` is climbing.

## 7. Certificates

```sh
kubectl get certificate -A -o json \
  | jq -r '.items[] | "\(.metadata.namespace)/\(.metadata.name) ready=\([.status.conditions[] | select(.type=="Ready") | .status] | join("")) notAfter=\(.status.notAfter) renewal=\(.status.renewalTime)"'
date -u +%Y-%m-%dT%H:%M:%SZ
```

Flag: `ready != True`, or a `renewal` time already in the past (cert-manager should have
renewed and hasn't).

Judge by `renewal`, not `notAfter`. cert-manager renews at ~2/3 of lifetime, so a healthy
90-day cert spends weeks inside any fixed "expiring soon" window while being perfectly
fine. A `CertManagerCertExpirySoon` alert on a cert that is `ready=True` with a future
`renewal` is an alert-threshold problem, not a certificate problem — say so rather than
flagging the cert.

## 8. CloudNative-PG

```sh
kubectl get cluster -n database
```

Flag: status not `Cluster in healthy state`, READY < INSTANCES.

## 9. Dragonfly

```sh
kubectl get dragonfly -A
kubectl get pods -A -l app.kubernetes.io/part-of=dragonfly -o json \
  | jq -r '.items[] | select(.status.phase != "Running" or ([.status.containerStatuses[]?.restartCount] | add > 0))
      | "\(.metadata.namespace)/\(.metadata.name) \(.status.phase) restarts=\([.status.containerStatuses[]?.restartCount] | add)"'
```

Flag: any `Dragonfly` not `Ready`, fewer running pods than its `REPLICAS`, or any restart
count above zero.

Only the operator lives in `database`; the instances are created per consuming app and
follow that app's namespace, so always query all namespaces rather than a fixed list. If
the label selector returns nothing, confirm with `kubectl get dragonfly -A` and find the
current pod labels from one of those instances before concluding anything is down.

## 10. Networking

```sh
kubectl exec -n kube-system ds/cilium -- cilium status --brief
kubectl exec -n kube-system ds/cilium -- cilium bgp peers
kubectl get pods -n network --no-headers | grep -v Running
```

Flag: Cilium not OK, BGP session not `established`, any network pod not Running.

## 11. HTTPRoutes / Gateways

```sh
kubectl get gateway -n network
kubectl get httproute -A -o json | jq '[.items[] | select(.status.parents[]?.conditions[]? | select(.type=="Accepted" and .status!="True"))] | length'
```

Flag: gateways not `PROGRAMMED=True`, any HTTPRoute not accepted (count > 0).

## 12. Security

```sh
kubectl get pods -n security --no-headers
```

Flag: Authelia or LLDAP not Running, any restarts > 0.

## 13. Observability Stack

```sh
kubectl get pods -n observability --no-headers | grep -v Running
```

Flag: any pod not Running.

## 14. Firing Alerts

```sh
curl -s https://alertmanager.diaoul.io/api/v2/alerts \
  | jq '[.[] | select(.status.silencedBy == [] and (.labels.alertname | test("InfoInhibitor|Watchdog") | not))] | .[] | {alert: .labels.alertname, severity: .labels.severity, namespace: .labels.namespace}'
```

Flag: any critical alerts. Warning alerts note but don't fail.

## 15. Gatus — Per-Service Status

```sh
curl -s https://status.diaoul.io/api/v1/endpoints/statuses \
  | jq '[.[] | select(.results[-1].success == false) | .name]'
```

Flag: any service in the list (non-empty = failing probes).

## 16. Victoria Logs — Error/Warning Scan

```sh
curl -s 'https://victoria-logs.diaoul.io/select/logsql/query?start=1h&query=%28level%3AERROR%20OR%20level%3AWARNING%29%20%7C%20stats%20by%20%28kubernetes.pod_namespace%29%20count%28%29%20as%20cnt'
```

The query must be URL-encoded into the query string as above: the sandbox rejects
`curl --data-urlencode` (it reads as a POST), and an empty `query` arg returns
``​`query` arg cannot be empty``.

Flag: namespaces with unusually high error counts. Judge relatively, not against a fixed
threshold — `kube-system` carries constant background noise, and `rook-ceph` spikes for
an hour after any Ceph or node-level change. Compare namespaces against each other and
against what the rest of this run already found: a spike in a namespace whose pods,
PVCs and Flux resources are all green is usually the tail of something that already
resolved. An app namespace that is normally silent appearing at all is the real signal.

## 17. Kubernetes Warning Events

```sh
kubectl get events -A --field-selector=type=Warning --sort-by='.lastTimestamp' | tail -20
```

Flag: OOMKilled, FailedScheduling, recurring BackOff.

## 18. Resource Pressure

```sh
kubectl top nodes
kubectl top pods -A --sort-by=memory | head -20
```

Flag: any node >85% memory, any node >90% CPU sustained.

## 19. System Upgrades

```sh
kubectl get talosupgrade,kubernetesupgrade -A
```

Flag: Phase not `Completed` — upgrade in progress or failed.
