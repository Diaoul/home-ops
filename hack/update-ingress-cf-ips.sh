#!/bin/bash

ips=$( (\
    curl -s https://www.cloudflare.com/ips-v4 | sort; \
    curl -s https://www.cloudflare.com/ips-v6 | sort \
    ) | cat | tr '\n' ' ')

yq e ".spec.values.controller.config.proxy-real-ip-cidr = \"$ips\"" \
    cluster/kube-system/ingress-nginx-external/helmrelease.yaml
