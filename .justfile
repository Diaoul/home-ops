#!/usr/bin/env -S just --justfile

set quiet
set shell := ['bash', '-euo', 'pipefail', '-c']

mod bootstrap
mod kubernetes
mod nas
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

[doc('Point-in-time cluster health; exits 1 on any FAIL')]
health:
    bash "{{ justfile_dir() }}/scripts/health.sh"

hold pr:
    gh pr edit "{{ pr }}" --add-label hold

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

    merged=0 hold=0 failing=0 pending=0 errors=0
    for type in "${types[@]}"; do
        while IFS=$'\t' read -r pr state; do
            case "${state}" in
                hold) hold=$((hold + 1)) ;;
                failing) failing=$((failing + 1)) ;;
                pending) pending=$((pending + 1)) ;;
                green)
                    if gh pr merge "${pr}" --rebase; then
                        merged=$((merged + 1))
                    else
                        errors=$((errors + 1))
                    fi
                    ;;
            esac
        done < <(gh pr list \
            --author app/kornandon \
            --label "type/${type}" \
            --state open \
            --json number,labels,statusCheckRollup \
            --jq '.[] | [.number, (
                if ([.labels[].name] | index("hold")) then "hold"
                else [.statusCheckRollup[] | (.conclusion // .state // "")] as $r
                    | [.statusCheckRollup[] | (.status // "COMPLETED")] as $s
                    | if any($r[]; IN("FAILURE", "ERROR", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED", "STARTUP_FAILURE")) then "failing"
                      elif any($s[]; . != "COMPLETED") or any($r[]; IN("PENDING", "EXPECTED", "")) then "pending"
                      else "green" end
                end)] | @tsv')
    done

    echo "Merged ${merged}. Not merged: ${hold} on hold, ${failing} failing CI, ${pending} CI still running, ${errors} merge errors."
