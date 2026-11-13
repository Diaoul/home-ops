#!/usr/bin/env bash
# Encrypt a new Secret read from stdin into kubernetes/**/*.sops.yaml; can never decrypt.

set -o errexit
set -o pipefail
set -o nounset

die() { echo "sops-encrypt: $*" >&2; exit 1; }

[ $# -eq 1 ] || die "usage: sops-encrypt.sh <kubernetes/.../*.sops.yaml> < plaintext.yaml"
path=$1

case "$path" in
  kubernetes/*.sops.yaml) ;;
  *) die "path must be under kubernetes/ and end in .sops.yaml" ;;
esac
case "$path" in
  *..*) die "path must not contain .." ;;
esac
[ -e "$path" ] && die "$path exists; rotate it by hand"
[ -d "$(dirname "$path")" ] || die "$(dirname "$path") does not exist"

plain=$(cat)
printf '%s\n' "$plain" | grep -qE '^kind:[[:space:]]*Secret[[:space:]]*$' || die "stdin is not a kind: Secret"

# Encryption needs only the public recipients in .sops.yaml.
unset SOPS_AGE_KEY_FILE SOPS_AGE_KEY SOPS_AGE_SSH_PRIVATE_KEY_FILE

tmp=$(mktemp "${path}.XXXXXX")
trap 'rm -f "$tmp"' EXIT
# A pipe, not a here-string: bash may spill a here-string to a temp file.
printf '%s\n' "$plain" | sops --encrypt --filename-override "$path" --input-type yaml --output-type yaml /dev/stdin >"$tmp"
unset plain
mv "$tmp" "$path"
trap - EXIT
echo "encrypted $path"
