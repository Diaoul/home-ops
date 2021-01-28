#!/bin/bash
for file in $(fd -t f -I '\-secret\.yaml'); do
    sealedfile="${file%-secret.yaml}-sealedsecret.yaml"
    if [ ! -f "${sealedfile}" ]; then
        echo "---" > "${sealedfile}"
        kubeseal < "${file}" |
            yq eval 'del(.metadata.creationTimestamp)' - |
            yq eval 'del(.spec.template.metadata.creationTimestamp)' - >> "${sealedfile}"
    fi
done
