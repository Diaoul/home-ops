## :construction: Installation

### All in one
This will result in a commit on the repository to update the manifests

```bash
export GITHUB_TOKEN=token
flux bootstrap github \
  --owner=Diaoul \
  --repository=home-operations \
  --branch=main \
  --path=./cluster \
  --personal \
  --network-policy=false \
  --cluster-domain=cluster.milkyway
```

### Manually
Install Flux components
```bash
flux install \
  --cluster-domain=cluster.milkyway \
  --network-policy=false
```

Create git source
```bash
flux create source git flux-system \
  --url=ssh://git@github.com/Diaoul/home-operations \
  --ssh-key-algorithm=ed25519 \
  --branch=main \
  --interval=1m
```

Flux will fail due to missing CRDs, running this several times will ensure
everything gets created:
```bash
kustomize build cluster/ | kubectl apply -f -
```

Flux will handle future updates!
