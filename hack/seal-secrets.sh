#!/bin/bash
for file in $(fd -t f -I '\-secret\.yaml'); do
    kubeseal < ${file} > ${file%-secret.yaml}-sealedsecret.yaml
done
