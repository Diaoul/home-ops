set quiet
set shell := ['bash', '-euo', 'pipefail', '-c']
set script-interpreter := ['bash', '-euo', 'pipefail']

host := 'singularity.milkyway'
containers := '/volume1/containers'

[private]
default:
    just -l nas

[doc('Upgrade DSM packages, then every Container Manager project')]
upgrade: upgrade-packages upgrade-containers

[doc('Upgrade all DSM packages that have an update')]
upgrade-packages:
    ssh {{ host }} 'sudo -n /usr/syno/bin/synopkg upgradeall'

[doc('Pull and recreate Container Manager projects (default: all)')]
[script]
upgrade-containers *projects:
    ssh {{ host }} 'bash -s' -- {{ projects }} <<'EOF'
    set -euo pipefail
    docker=/usr/local/bin/docker
    cd {{ containers }}
    projects=("$@")
    [[ ${#projects[@]} -gt 0 ]] || projects=($(ls -d */ | grep -v '^@' | tr -d /))
    failed=()
    for p in "${projects[@]}"; do
        echo "== $p"
        cd "{{ containers }}/$p"
        if ! sudo -n "$docker" compose pull --quiet </dev/null || ! sudo -n "$docker" compose up -d --remove-orphans </dev/null; then
            failed+=("$p")
        fi
    done
    sudo -n "$docker" image prune -f
    if [[ ${#failed[@]} -gt 0 ]]; then
        echo "failed: ${failed[*]}" >&2
        exit 1
    fi
    EOF
