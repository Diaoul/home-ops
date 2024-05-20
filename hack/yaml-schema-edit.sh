#!/usr/bin/env bash

selection='select(.kind == "HelmRelease" and .spec.chart.spec.chart != "app-template")'
comment='yaml-language-server: $schema=https://kubernetes-schemas.pages.dev/helm.toolkit.fluxcd.io/helmrelease_v2.json'

for file in $(fd .yaml -E '*.sops.*' -E '*.j2'); do
  if yq eval -e "$selection" "$file" >/dev/null 2>&1; then
    echo "Matching $file"
    # remove the document comment if there was one
    yq eval -i "$selection head_comment=\"\"" "$file"
    yq eval -i "($selection | .apiVersion | key) head_comment=\"$comment\"" "$file"
    # add bach the document separator which was removed by yq
    # see https://github.com/mikefarah/yq/issues/1836
    if [ "$(head -n 1 "$file")" != "---" ]; then
      sed -i '1i---' "$file"
    fi
  else
    continue
  fi
done
