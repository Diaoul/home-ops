## :toolbox: Utility scripts

### seal-secrets.sh
Convert any `*-secret.yaml` file to a `*-sealedsecret.yaml` file with the
kubeseal CLI

### update-ingress-cf-ips.sh
Update Cloudflare's ip addresses for `proxy-real-ip-cidr` in
[ingress-nginx]( ../cluster/kube-system/ingress-nginx/helmrelease.yaml)
