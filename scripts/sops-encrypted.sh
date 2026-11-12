#!/usr/bin/env bash

# Fails when a Kubernetes Secret carries plaintext: every document needs sops
# metadata (mac), and every non-empty data/stringData value must be an ENC[...]
# payload. Only kubernetes/ and bootstrap/ are read: the creation rule covering
# them is the one with encrypted_regex: "^(data|stringData)$", and their files
# are all Secrets. This needs no age key, so it can run in CI.
set -euo pipefail

rc=0
while IFS= read -r -d '' file; do
    # yq prints nothing when it cannot read the file; treat that as a failure of
    # its own rather than as evidence about the contents.
    if ! encrypted=$(yq ea '[.sops.mac | select(.)] | length' "${file}") ||
        ! total=$(yq ea '[.] | length' "${file}"); then
        echo "::error file=${file}::not readable as YAML by yq"
        rc=1
        continue
    fi

    if [[ ${encrypted} != "${total}" ]]; then
        echo "::error file=${file}::not encrypted: a document has no sops metadata"
        rc=1
        continue
    fi

    if ! plaintext=$(yq ea '[(.data, .stringData) | select(.) | .[] | select(. != "" and (test("^ENC\\[") | not))] | length' "${file}"); then
        echo "::error file=${file}::not readable as YAML by yq"
        rc=1
        continue
    fi

    if [[ ${plaintext} != 0 ]]; then
        echo "::error file=${file}::plaintext value under data or stringData"
        rc=1
    fi
done < <(git ls-files -z 'kubernetes/*.sops.yaml' 'bootstrap/*.sops.yaml')
exit "${rc}"
