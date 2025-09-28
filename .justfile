#!/usr/bin/env -S just --justfile

set quiet := true
set shell := ['bash', '-euo', 'pipefail', '-c']

mod bootstrap
mod kubernetes
mod talos

[private]
default:
    just -l

[private]
log lvl msg *args:
    gum log -t rfc3339 -s -l "{{ lvl }}" "{{ msg }}" {{ args }}

[private]
template file *args:
    minijinja-cli "{{ file }}" {{ args }} | op inject

merge type="":
    #!/usr/bin/env bash
    set -euo pipefail

    if [[ -n "{{ type }}" ]]; then
        if [[ ! "{{ type }}" =~ ^(digest|patch|minor|major)$ ]]; then
            echo "Error: type must be one of: digest, patch, minor, major"
            exit 1
        fi
        types=("{{ type }}")
    else
        types=("digest" "patch" "minor" "major")
    fi

    for type in "${types[@]}"; do
        label="type/${type}"

        prs=$(gh pr list \
            --label "${label}" \
            --state open \
            --json number,labels \
            --jq '.[] | select(.labels | map(.name) | contains(["status/hold"]) | not) | .number')

        if [[ -z "${prs}" ]]; then
            continue
        fi

        for pr in ${prs}; do
            gh pr merge "${pr}" --rebase
        done
    done
