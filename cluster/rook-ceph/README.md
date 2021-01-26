# Installation
Install Helm Release first then the others as the CRDs are required.

# Uninstallation
Remove the pool before the operator otherwise the pool will hang forever.

It is possible to manually remove the finalizers so the pool can be deleted:

```bash
kubectl -n rook-ceph patch cephblockpool replicapool --type merge \
  -p '{"metadata":{"finalizers": []}}'
```
