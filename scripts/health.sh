#!/usr/bin/env bash
# Point-in-time cluster health. One line per finding: STATUS AREA DETAIL.
# Exits 1 when anything is FAIL.

set -o errexit
set -o pipefail
set -o nounset

DOMAIN="${DOMAIN:-diaoul.io}"
PROM="https://prometheus.${DOMAIN}"
AM="https://alertmanager.${DOMAIN}"
GATUS="https://status.${DOMAIN}"
VLOGS="https://victoria-logs.${DOMAIN}"
REPO="${REPO:-Diaoul/home-ops}"

fail=0
report() {
    local status=$1 area=$2
    shift 2
    [[ $status == FAIL ]] && fail=1
    # Details carry untrusted text (PR titles, alert labels, Flux messages); drop terminal escapes.
    printf '%-4s %-10s %s\n' "$status" "$area" "$(tr -d '\000-\010\013-\037\177' <<<"$*")"
}
# Usage: each STATUS AREA < <(cmd) — a pipe would run it in a subshell and lose $fail.
each() {
    local line
    while IFS= read -r line; do
        [[ -n $line ]] && report "$1" "$2" "$line"
    done
    return 0
}

# Callers report the failure: fetch runs inside $(...), where report could not set $fail.
fetch() {
    curl -fsS -G --max-time 15 "$@" 2>/dev/null
}
unreachable() {
    report FAIL "$1" "unreachable: $2"
}

check_alerts() {
    local alerts sev status
    alerts=$(fetch "${AM}/api/v2/alerts" --data-urlencode silenced=false --data-urlencode inhibited=false) || { unreachable alerting "${AM}/api/v2/alerts"; return 0; }
    if ! jq -e 'any(.[]; .labels.alertname == "Watchdog")' <<<"$alerts" >/dev/null; then
        report FAIL alerting "Watchdog not firing: Prometheus to Alertmanager pipeline is broken"
    fi
    for sev in critical warning; do
        status=WARN
        [[ $sev == critical ]] && status=FAIL
        each "$status" alert < <(jq -r --arg sev "$sev" '
            [.[] | select(.labels.severity == $sev and (.labels.alertname | test("^(Watchdog|InfoInhibitor)$") | not))]
            | group_by(.labels.alertname)[]
            | "\(.[0].labels.alertname) x\(length): \([.[].labels | .namespace // .instance // .node // .job // "-"] | unique | join(", "))"
        ' <<<"$alerts")
    done
}

check_prometheus() {
    local rules alerts
    rules=$(fetch "${PROM}/api/v1/rules") || { unreachable prometheus "${PROM}/api/v1/rules"; return 0; }
    alerts=$(fetch "${PROM}/api/v1/alerts") || { unreachable prometheus "${PROM}/api/v1/alerts"; return 0; }
    each WARN rules < <(jq -r '
        .data.groups[] | .name as $g | .rules[] | select(.health == "err")
        | "\($g)/\(.name): \(.lastError)"' <<<"$rules")
    each INFO alert < <(jq -r '
        [.data.alerts[] | select(.state == "pending")] | group_by(.labels.alertname)[]
        | "\(.[0].labels.alertname) x\(length) pending"' <<<"$alerts")
}

check_gatus() {
    local statuses
    statuses=$(fetch "${GATUS}/api/v1/endpoints/statuses") || { unreachable gatus "${GATUS}/api/v1/endpoints/statuses"; return 0; }
    each FAIL gatus < <(jq -r '
        .[] | select(.results[-1].success == false) | "\(.group // "-")/\(.name)"' <<<"$statuses")
}

check_flux() {
    local out
    out=$(flux get all -A --status-selector ready=false --no-header 2>/dev/null) || { report FAIL flux "flux get failed"; return 0; }
    each WARN flux <<<"$out"
}

check_pods() {
    local pods
    pods=$(kubectl get pods -A -o json 2>/dev/null) || { report FAIL pods "kubectl get pods failed"; return 0; }
    each WARN pods < <(jq -r '
        .items[]
        | select(.status.phase != "Succeeded")
        | select(any(.status.conditions[]?; .type == "Ready" and .status != "True"))
        | "\(.metadata.namespace)/\(.metadata.name) \(.status.phase) \([.status.containerStatuses[]?.state | keys[0]] | unique | join(","))"
    ' <<<"$pods")
}

# A stuck NodeUnpublishVolume keeps the RBD image mapped while every other signal stays green.
check_csi() {
    local hits url="${VLOGS}/select/logsql/query"
    hits=$(fetch "$url" --data-urlencode \
        'query=_time:15m kubernetes.container_name:csi-rbdplugin "directory not empty" | stats by (kubernetes.pod_node_name) count() as n') || {
        unreachable csi "$url"
        return 0
    }
    each FAIL csi < <(jq -r '"\(."kubernetes.pod_node_name"): \(.n) failed unpublish retries in 15m"' <<<"$hits")
}

check_miroir() {
    local nodes
    nodes=$(kubectl get miroirnodes -o json 2>/dev/null) || { report FAIL miroir "kubectl get miroirnodes failed"; return 0; }
    each FAIL miroir < <(jq -r '
        .items[] | select(
            (.status.drbdVersion // "") == ""
            or ([.status.pools[]? | select(.name == "default" and (.capacityBytes // 0) > 0)] | length) == 0
        ) | "\(.metadata.name): default pool or DRBD missing, not a placement candidate"
    ' <<<"$nodes")
}

check_cilium() {
    local configs nodes result url="${PROM}/api/v1/query"
    configs=$(kubectl get ciliumbgpnodeconfig -o json 2>/dev/null) || { report FAIL bgp "kubectl get ciliumbgpnodeconfig failed"; return 0; }
    nodes=$(kubectl get nodes -o name 2>/dev/null | wc -l)
    each FAIL bgp < <(jq -r --argjson nodes "$nodes" '
        (if (.items | length) < $nodes then "\(.items | length)/\($nodes) nodes have a BGP node config" else empty end),
        (.items[] | .metadata.name as $n
            | (.status.bgpInstances // [])[] | (.peers // [])[]
            | select(.peeringState != "established")
            | "\($n) -> \(.name) (\(.peerAddress)): \(.peeringState // "unknown")"),
        (.items[] | select(([.status.bgpInstances[]?.peers[]?] | length) == 0) | "\(.metadata.name): no BGP peers")
    ' <<<"$configs")
    result=$(fetch "$url" --data-urlencode 'query=cilium_unreachable_nodes > 0 or cilium_controllers_failing > 0') || {
        unreachable cilium "$url"
        return 0
    }
    each WARN cilium < <(jq -r '.data.result[] | "\(.metric.node // .metric.pod): \(.metric.__name__) = \(.value[1])"' <<<"$result")
}

check_gateway() {
    local gateways routes
    gateways=$(kubectl get gateway -A -o json 2>/dev/null) || { report FAIL gateway "kubectl get gateway failed"; return 0; }
    routes=$(kubectl get httproute -A -o json 2>/dev/null) || { report FAIL gateway "kubectl get httproute failed"; return 0; }
    each FAIL gateway < <(jq -r '
        .items[] | .metadata.name as $n | .status.conditions[]?
        | select(.type == "Programmed" and .status != "True")
        | "\($n) not programmed: \(.message)"
    ' <<<"$gateways")
    each WARN route < <(jq -r '
        .items[] | "\(.metadata.namespace)/\(.metadata.name)" as $n
        | if ((.status.parents // []) | length) == 0 then "\($n) not attached to any Gateway"
          else .status.parents[].conditions[]?
            | select((.type == "Accepted" or .type == "ResolvedRefs") and .status != "True")
            | "\($n) \(.type)=False: \(.reason)"
          end
    ' <<<"$routes")
}

check_renovate() {
    local last_ok prs dashboard cutoff
    last_ok=$(gh run list -R "$REPO" --workflow renovate.yaml --status success --limit 1 \
        --json createdAt --jq '.[0].createdAt // empty') || { report WARN renovate "gh run list failed"; return 0; }
    if [[ -z $last_ok ]]; then
        report WARN renovate "no successful run found"
    elif (($(date +%s) - $(date -d "$last_ok" +%s) > 12 * 3600)); then
        report WARN renovate "last successful run ${last_ok}"
    fi
    cutoff=$(date -u -d '-7 days' +%FT%TZ)
    prs=$(gh pr list -R "$REPO" --author app/kornandon --state open --limit 200 --json number,title,createdAt \
        --jq ".[] | select(.createdAt < \"${cutoff}\") | \"#\(.number) open since \(.createdAt[0:10]): \(.title)\"") \
        || { report WARN renovate "gh pr list failed"; return 0; }
    each WARN renovate <<<"$prs"
    dashboard=$(gh issue list -R "$REPO" --author app/kornandon --search 'Renovate Dashboard in:title' \
        --json body --jq '.[0].body // ""') || { report WARN renovate "gh issue list failed"; return 0; }
    each WARN renovate < <(awk '/^## /{s=$0} s ~ /^## (Errored|Repository problems)/ && /^ *- /' <<<"$dashboard" \
        | sed -E 's/<!--[^>]*-->//g; s/^ *- (\[ \] )?//')
}

check_alerts
check_prometheus
check_gatus
# flux exits 0 when the API is down, so gate every kubectl/flux check on one probe.
if kubectl version --request-timeout=5s >/dev/null 2>&1; then
    check_flux
    check_pods
    check_miroir
    check_cilium
    check_gateway
else
    report FAIL kubernetes "API server unreachable, skipped flux/pods/miroir/bgp/cilium/gateway"
fi
check_csi
check_renovate

((fail == 0)) && report OK summary "no failures"
exit "$fail"
