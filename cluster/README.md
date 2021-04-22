## :construction: Installation

Create namespace
```bash
kubectl create namespace flux-system
```

Add SOPS private key
```bash
kubectl create secret generic sops-gpg \
    --namespace=flux-system \
    --from-file=sops.asc=/dev/stdin
```

Install Flux
```bash
kubectl apply --kustomize=./cluster/base/flux-system
```

Enable k3s upgrades (if not already done by ansible)
```bash
kubectl label node --all k3s-upgrade=true
```
