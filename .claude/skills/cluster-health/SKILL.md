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
kubectl get snapshotschedule.kopiur.home-operations.com -A
kubectl get snapshots.kopiur.home-operations.com -A -o json \
  | jq -r '[.items[] | select(.status.phase != "Succeeded")
            | "\(.metadata.namespace)/\(.metadata.name) \(.status.phase)"] | .[]'
```

Flag: any schedule whose `LAST-SNAPSHOT` is >24h ago or that is `SUSPENDED`, and any
Snapshot not `Succeeded`. Schedules run `H 3 * * *` Europe/Paris, so a healthy app shows
a last snapshot under 24h old. There should be 22 policies / 22 schedules / 22 restores.

## 7. Certificates

```sh
kubectl get certificate -A
```

Flag: `READY != True`, or expiry within 7 days.

## 8. CloudNative-PG

```sh
kubectl get cluster -n database
```

Flag: status not `Cluster in healthy state`, READY < INSTANCES.

## 9. Dragonfly

```sh
kubectl get pods -n database -l app.kubernetes.io/name=dragonfly --no-headers
```

Flag: not Running, any restarts.

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
curl -s 'https://victoria-logs.diaoul.io/select/logsql/query' \
  --data-urlencode 'query=(level:ERROR OR level:WARNING) | stats by (kubernetes.pod_namespace) count() as cnt' \
  --data-urlencode 'start=1h'
```

Flag: namespaces with unusually high error counts. Use judgment — kube-system has background noise; flag counts that look anomalous (e.g. >1000 errors/hour from an app namespace).

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
