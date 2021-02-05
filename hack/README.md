## :toolbox: Utility scripts

### create-helmrelease-annotations.sh
Create annotations in helmrelease.yaml files to be used by
[renovate](../.github/renovate.json5)

```yaml
# renovate: registryUrl=https://k8s-at-home.com/charts/
```

### seal-secrets.sh
Convert any `*-secret.yaml` file to a `*-sealedsecret.yaml` file with the
kubeseal CLI

### update-ingress-cf-ips.sh
Update Cloudflare's ip addresses for proxy-real-ip-cidr in
[ingress-nginx-external]( ../cluster/kube-system/ingress-nginx-external/helmrelease.yaml)
