#!/bin/bash
for file in $(fd -t f -I '\-secret\.yaml'); do
    sealedfile="${file%-secret.yaml}-sealedsecret.yaml"
    if [ ! -f "${sealedfile}" ]; then
        echo "---" > "${sealedfile}"
        kubeseal < "${file}" >> "${sealedfile}"
    fi
done
