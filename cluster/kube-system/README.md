# kube-system

## sealed-secrets
[Sealed Secrets](https://github.com/bitnami-labs/sealed-secrets) converts
regular secrets to encrypted ones that can be included in source control.

Default arguments can be set through environment variables, for example:
```bash
export SEALED_SECRETS_CONTROLLER_NAME=sealed-secrets
export SEALED_SECRETS_FORMAT=yaml
```
