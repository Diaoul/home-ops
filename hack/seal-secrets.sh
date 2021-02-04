#!/bin/bash
root=$(git rev-parse --show-toplevel)
for file in $(fd -t f -I '\-secret\.yaml' "$root"); do
    sealedfile="${file%-secret.yaml}-sealedsecret.yaml"
    if [ ! -f "${sealedfile}" ]; then
        echo "Creating $sealedfile..."
        echo "---" > "${sealedfile}"
        kubeseal < "${file}" |
            yq eval 'del(.metadata.creationTimestamp)' - |
            yq eval 'del(.spec.template.metadata.creationTimestamp)' - >> "${sealedfile}"
    fi
done
