---
name: creating-a-sops-secret
description: >
  Create a new SOPS-encrypted Secret in home-ops without ever seeing its values. Use when an
  app needs a new `secret.sops.yaml` or a CNPG `<app>.sops.yaml`.
---

# Creating a SOPS secret

Encrypting needs only the public keys: the age recipient in `.sops.yaml`, and the PGP key it
names by fingerprint, which `https://github.com/Diaoul.gpg` serves. Nothing here decrypts, so
a file cannot be read back to check it: get it right in the command that writes it.

`sops` itself is denied in `.claude/settings.json`; encrypt through `scripts/sops-encrypt.sh`,
which takes the target path, reads the plaintext Secret on stdin, and refuses to overwrite an
existing file. Each call asks the user first.

## Generated values

Generate each value inside the command that encrypts it, so it never appears in your output,
a message, or a file in plain text. Run from the repository root, with the path the file will
have, so `.sops.yaml` picks the right rule:

```sh
path=kubernetes/apps/<namespace>/<app>/app/secret.sops.yaml
pw=$(openssl rand -base64 32 | tr -d '\n=+/')
cat <<EOF | bash scripts/sops-encrypt.sh "$path"
# yaml-language-server: \$schema=https://k8s-schemas.home-operations.com/core/secret_v1.json
apiVersion: v1
kind: Secret
metadata:
  name: <app>
stringData:
  APP_SECRET_KEY: "$pw"
EOF
unset pw
```

Check the result by its metadata only: `grep -cE 'recipient: age1|fp: ' "$path"` prints 2.

## A value shared by two files

A CNPG database password lives in both `kubernetes/apps/database/cloudnative-pg/databases/<app>.sops.yaml`
and the app's own secret (see AGENTS.md, PostgreSQL Pattern). Write both files in the same
shell, from the same `$pw`; generated separately, they will not match, and nothing shows it
until the app fails to log in.

## Values only the user has

A third-party API key or a credential from another service's UI: encrypt `CHANGEME` as its
value and list the key in the pull request, so the user replaces it with their own tooling.
