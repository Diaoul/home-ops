#!/bin/bash

file="cluster/kube-system/ingress-nginx-external/helmrelease.yaml"
ips=$( (\
    curl -s https://www.cloudflare.com/ips-v4 | sort; \
    curl -s https://www.cloudflare.com/ips-v6 | sort \
    ) | cat | tr '\n' ',' | sed -e 's/,$//' )

# TODO re-add --- document start removed by yq
# see https://github.com/mikefarah/yq/issues/351
yq -i eval ".spec.values.controller.config.proxy-real-ip-cidr = \"$ips\"" $file
