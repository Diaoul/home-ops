# Installation
## OS preparation
```bash
ansible-playbook ansible/playbooks/os.yml
```

## K3S
```bash
ansible-playbook ansible/playbooks/k3s.yml
```

## CNI
```bash
ansible-playbook ansible/playbooks/calico.yml
```

## Flux
```bash
export GITHUB_TOKEN=token
flux bootstrap github \
  --owner=Diaoul \
  --repository=home-operations \
  --branch=main \
  --path=./cluster \
  --personal \
  --cluster-domain=cluster.milkyway
```

Flux will likely scream due to missing CRDs so apply them manually, usually
by installing the HelmRelease manually, e.g.
```bash
kubectl apply -f cluster/kube-system/sealed-secrets/helmrelease.yaml
```

Flux will pick up the rest, eventually.

## Sealed Secrets
Seal the secrets with `hack/seal-secrets.sh`
