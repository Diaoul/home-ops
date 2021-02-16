#!/bin/bash

files=$(git diff --staged --name-only | grep "^cluster/")
lcp=$(echo "$files" | sed -e 'N;s/^\(.*\).*\n\1.*$/\1\n\1/;D')
parent=$(echo "$lcp" | sed 's/\(.*\)\/.*/\1/')

echo "Running kustomize build $parent..."
kustomize build $parent > /dev/null
