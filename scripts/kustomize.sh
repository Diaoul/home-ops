#!/usr/bin/env bash
set -o errexit
set -o pipefail

files=$(git diff --staged --name-only | grep "^kubernetes/")
lcp=$(echo "$files" | sed -e 'N;s/^\(.*\).*\n\1.*$/\1\n\1/;D')
parent=$(echo "$lcp" | sed 's/\(.*\)\/.*/\1/')

if [ -f "$parent/kustomization.yaml" ]; then
  echo "Running kustomize build $parent..."
  kustomize build "$parent" >/dev/null
else
  echo "No kustomization.yaml in $parent"
fi
