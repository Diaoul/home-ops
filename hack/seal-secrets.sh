#!/bin/bash
for file in $(fd -t f -I '\-secret\.yaml'); do
    echo "kubeseal < ${file} > ${file%-secret.yaml}-sealedsecret.yaml"
done
