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

## 5. OpenEBS

```sh
kubectl get pods -n openebs-system --no-headers | grep -v Running
```

Flag: any pod not Running.

## 6. VolSync Backups

```sh
kubectl get replicationsource -A
```

Flag: any source where last sync is >24h ago or status shows error.

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

Flag: namespaces with unusually high error counts. Use judgment — kube-system and openebs-system have background noise; flag counts that look anomalous (e.g. >1000 errors/hour from an app namespace).

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
