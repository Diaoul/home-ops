# Longhorn Configuration
To add a node in the storage pool, label it with:
```yaml
node.longhorn.io/create-default-disk: "true"
```
With kubectl:
```bash
kubectl label node k8s-node-x node.longhorn.io/create-default-disk="true"
```
