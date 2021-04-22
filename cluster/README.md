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

Add Flux SSH key within a directory containing `identity`, `identity.pub` and
`known_hosts` (see [flux docs](https://toolkit.fluxcd.io/components/source/gitrepositories/#ssh-authentication))
```bash
kubectl create secret generic flux-system \
    --namespace=flux-system \
    --from-file=identity=identity \
    --from-file=identity.pub=identity.pub \
    --from-file=known_hosts=known_hosts
```

Install Flux
```bash
kubectl apply --kustomize=./cluster/base/flux-system
```

Enable k3s upgrades (if not already done by ansible)
```bash
kubectl label node --all k3s-upgrade=true
```
