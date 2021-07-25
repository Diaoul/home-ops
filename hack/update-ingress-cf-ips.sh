#!/bin/bash

root=$(git rev-parse --show-toplevel)
file="$root/cluster/apps/networking/ingress-nginx/helmrelease.yaml"
ips=$( (\
    curl -s https://www.cloudflare.com/ips-v4 | sort; \
    curl -s https://www.cloudflare.com/ips-v6 | sort \
    ) | cat | tr '\n' ',' | sed -e 's/,$//' )

yq -i eval ".spec.values.controller.config.proxy-real-ip-cidr = \"$ips\"" $file
