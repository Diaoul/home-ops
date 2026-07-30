#!/usr/bin/env bash

# Migrate one app from the volsync `persistence` component to `kopiur-tmp`.
#
# The PVC's dataSourceRef is immutable, so migrating means deleting and
# recreating the PVC. To make that safe this script:
#   1. scales the app to 0 (quiesces SQLite -- WAL gets checkpointed)
#   2. takes an on-demand kopiur snapshot of the quiesced volume
#   3. deletes the PVC so kopiur's Restore repopulates it
#   4. asserts the Restore consumed that exact snapshot
#   5. scales the app back up and checks it is healthy
#
# The git half (rewrite ks.yaml, commit, push) lives in `prepare` so a batch
# of apps costs two YubiKey touches in total rather than two per app.
#
# Delete this script once the migration is finished (see the final fold-in in
# ~/.claude/plans/kopiur-migration-resume.md).

set -Eeuo pipefail

# shellcheck source=./lib/common.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"

REPO_DIR="$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)"
SCRATCH="${TMPDIR:-/tmp}/kopiur-migrate"
ASSUME_YES="${ASSUME_YES:-false}"

# NOTE: earlier versions fingerprinted the volume from a throwaway pod before
# and after the swap and required the two to match. That was dropped once the
# restore path was proven across 7 apps: it cost two extra pods and a full
# read of every file per app, and produced three bugs of its own (du is not
# comparable across a freshly formatted filesystem; xargs split paths
# containing spaces; `kubectl wait --for=Succeeded` waited out its timeout on
# an already-Failed pod).
#
# What is actually load-bearing is that the Restore consumed the snapshot we
# took moments earlier. restore.yaml sets onMissingSnapshot=Continue, so a
# missed snapshot yields an *empty* PVC rather than an error -- comparing the
# restored snapshot ID against ours is exactly what catches that, and content
# integrity is kopia's own job (the SnapshotPolicy runs verification.quick
# daily and verification.deep monthly).


function confirm() {
    [[ "${ASSUME_YES}" == "true" ]] && return 0
    read -rp "$1 [y/N] " reply
    [[ "${reply}" =~ ^[Yy]$ ]]
}

# Commits and pushes are gated on a YubiKey touch, and gpg gives up after ~30s
# with "signing failed: Timeout". Without this retry a missed touch aborts the
# run with the app scaled to 0, so keep asking rather than bailing out.
function git_retry() {
    local desc="$1"
    shift
    local attempt
    for attempt in 1 2 3 4 5; do
        if "$@"; then
            return 0
        fi
        log warn "${desc} failed -- TOUCH THE YUBIKEY; retrying" attempt="${attempt}/5"
        sleep 5
    done
    log error "${desc} failed after 5 attempts" hint="app is scaled to 0; see the resume note above"
}

# Rewrite one app's ks.yaml: drop the volsync persistence + snapshot-only
# kopiur components and the volsync dependsOn, add kopiur-tmp. Any other
# component (zeroscaler, ext-auth, ...) is preserved.
function rewrite_ks() {
    local ns="$1" app="$2"
    local ks="${REPO_DIR}/kubernetes/apps/${ns}/${app}/ks.yaml"

    [[ -f "${ks}" ]] || log error "No ks.yaml" path="${ks}"
    grep -q 'components/persistence' "${ks}" ||
        log error "Not on the persistence component (already migrated?)" app="${ns}/${app}"
    [[ -z "$(git -C "${REPO_DIR}" status --porcelain -- "${ks}")" ]] ||
        log error "ks.yaml has uncommitted changes -- commit or revert it first" path="${ks}"

    yq -i '
      .spec.components = ((.spec.components // []) | map(select(test("components/(persistence|kopiur)$") | not)))
      | .spec.dependsOn = ((.spec.dependsOn // []) | map(select(.name != "volsync")))
    ' "${ks}"
    yq -e '.spec.components | any_c(. == "../../../../components/kopiur-tmp")' "${ks}" >/dev/null 2>&1 ||
        yq -i '.spec.components += ["../../../../components/kopiur-tmp"]' "${ks}"
    log info "Rewrote ks.yaml" app="${ns}/${app}"
}

# Rewrite every listed app, validate once, then a SINGLE commit and push.
# This is what makes a batch unattended: two YubiKey touches for the whole
# batch instead of two per app.
#
# After this lands, every prepared-but-not-yet-swapped app sits Ready=False
# with "PersistentVolumeClaim ... is immutable". That is expected and benign:
# a failed apply is atomic, so nothing changes and nothing is pruned -- the
# volsync ReplicationSources and their backups stay live until each app is
# actually swapped.
function prepare() {
    [[ $# -gt 0 ]] || log error "usage: $0 prepare <ns/app> [<ns/app>...]"
    mkdir -p "${SCRATCH}"

    [[ -n "$(kubectl get pods -n volsync-system --no-headers 2>/dev/null)" ]] ||
        log error "volsync is gone -- rollback would be impossible"

    local pair ns app files=() names=()
    for pair in "$@"; do
        ns="${pair%%/*}"
        app="${pair##*/}"
        [[ "${ns}" != "${pair}" ]] || log error "Expected <ns>/<app>" got="${pair}"
        rewrite_ks "${ns}" "${app}"
        files+=("${REPO_DIR}/kubernetes/apps/${ns}/${app}/ks.yaml")
        names+=("${pair}")
    done

    log info "Validating manifests (once for the whole batch)"
    bash "${REPO_DIR}/scripts/kubeconform.sh" "${REPO_DIR}/kubernetes" >"${SCRATCH}/prepare-kubeconform.log" 2>&1 ||
        log error "kubeconform failed" log="${SCRATCH}/prepare-kubeconform.log"

    git_retry "commit" git -C "${REPO_DIR}" commit -q -m "feat(kopiur): migrate persistence->kopiur for $# app(s)

$(printf -- '- %s\n' "${names[@]}")

Drop the volsync persistence component and the snapshot-only kopiur
component in favour of kopiur-tmp, which owns both the PVC and the Restore.
Also drop the now-unneeded volsync dependsOn.

The PVC swap happens separately per app (see: kopiur-migrate.sh swap), so
until each app is swapped its Kustomization fails on the immutable PVC.
That apply is atomic, so volsync backups keep running in the meantime.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>" -- "${files[@]}"
    git_retry "push" git -C "${REPO_DIR}" push -q origin HEAD

    flux reconcile source git flux-system -n flux-system --timeout=2m >/dev/null
    local want got
    want="refs/heads/main@sha1:$(git -C "${REPO_DIR}" rev-parse HEAD)"
    got="$(kubectl get gitrepository flux-system -n flux-system -o jsonpath='{.status.artifact.revision}')"
    [[ "${got}" == "${want}" ]] || log error "Flux source did not pick up the push" want="${want}" got="${got}"

    log info "PREPARED -- now run swap for each" apps="${names[*]}" commit="$(git -C "${REPO_DIR}" rev-parse --short HEAD)"
}

# Cluster-side half: quiesce, snapshot, swap the PVC, verify, scale back up.
# Does no git at all, so it needs no YubiKey touch.
function swap() {
    local ns="$1" app="$2"
    local ks="${REPO_DIR}/kubernetes/apps/${ns}/${app}/ks.yaml"
    local snap="${app}-premigration-$(date -u +%Y%m%d%H%M%S)"

    mkdir -p "${SCRATCH}"

    # --- preflight -------------------------------------------------------
    # Deliberately NOT requiring a globally clean Flux: in a batch the sibling
    # apps are expected to be failing on their immutable PVCs. Check the real
    # dependencies instead.
    grep -q 'components/kopiur-tmp' "${ks}" || log error "Not prepared yet -- run prepare first" app="${ns}/${app}"
    [[ -z "$(git -C "${REPO_DIR}" status --porcelain -- "${ks}")" ]] ||
        log error "ks.yaml has uncommitted changes -- commit them first" path="${ks}"
    [[ -n "$(kubectl get pods -n volsync-system --no-headers 2>/dev/null)" ]] ||
        log error "volsync is gone -- rollback would be impossible"

    local dep
    for dep in rook-ceph/rook-ceph-cluster kopiur-system/kopiur-repository; do
        [[ "$(kubectl get kustomization "${dep##*/}" -n "${dep%%/*}" \
            -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null)" == "True" ]] ||
            log error "Dependency not ready" dependency="${dep}"
    done

    local want got
    want="refs/heads/main@sha1:$(git -C "${REPO_DIR}" rev-parse HEAD)"
    got="$(kubectl get gitrepository flux-system -n flux-system -o jsonpath='{.status.artifact.revision}')"
    [[ "${got}" == "${want}" ]] || log error "Flux source is stale; run prepare or reconcile first" want="${want}" got="${got}"

    # --- discover the workload ------------------------------------------
    local ctrl replicas
    ctrl="$(kubectl get deploy,sts -l "app.kubernetes.io/name=${app}" -o name --no-headers -n "${ns}" | head -1)"
    [[ -n "${ctrl}" ]] || log error "No deployment/statefulset found" app="${ns}/${app}"
    replicas="$(kubectl get "${ctrl}" -o jsonpath='{.spec.replicas}' -n "${ns}")"

    # Already at 0 almost always means an earlier run of this script died after
    # quiescing. Restoring "the original 0" would then leave the app down for
    # good -- which is exactly what happened to home-assistant. Refuse to guess.
    if [[ "${replicas}" == "0" ]]; then
        [[ -n "${REPLICAS:-}" ]] ||
            log error "Already scaled to 0 -- a previous run probably died here. Re-run with REPLICAS=<n> to say what to scale back to" app="${ns}/${app}"
        replicas="${REPLICAS}"
        log warn "Was already at 0; will scale back to REPLICAS" replicas="${replicas}"
    fi
    log info "Migrating" app="${ns}/${app}" controller="${ctrl}" replicas="${replicas}"

    # --- quiesce ---------------------------------------------------------
    kubectl scale "${ctrl}" --replicas 0 -n "${ns}" >/dev/null
    log info "Scaled to 0, waiting for pods to go away"
    until [[ "$(kubectl get pods -l "app.kubernetes.io/name=${app}" --no-headers -n "${ns}" 2>/dev/null | wc -l)" == "0" ]]; do sleep 3; done

    # --- snapshot the quiesced volume ------------------------------------
    # Retain so that deleting this CR later cannot destroy the safety net.
    kubectl apply -f - <<EOF >/dev/null
apiVersion: kopiur.home-operations.com/v1alpha1
kind: Snapshot
metadata:
  name: ${snap}
  namespace: ${ns}
spec:
  deletionPolicy: Retain
  onScheduleDelete: Retain
  policyRef:
    name: ${app}
EOF
    log info "Waiting for pre-migration snapshot" snapshot="${snap}"
    until [[ -n "$(kubectl get "snapshot.kopiur.home-operations.com/${snap}" -o jsonpath='{.status.phase}' -n "${ns}" 2>/dev/null | grep -E 'Succeeded|Failed')" ]]; do sleep 5; done
    local phase kopia
    phase="$(kubectl get "snapshot.kopiur.home-operations.com/${snap}" -o jsonpath='{.status.phase}' -n "${ns}")"
    kopia="$(kubectl get "snapshot.kopiur.home-operations.com/${snap}" -o jsonpath='{.status.snapshot.kopiaSnapshotID}' -n "${ns}")"
    if [[ "${phase}" != "Succeeded" ]]; then
        kubectl scale "${ctrl}" --replicas "${replicas}" -n "${ns}" >/dev/null
        log error "Snapshot failed; scaled back up, nothing destroyed" snapshot="${snap}" phase="${phase}"
    fi
    log info "Snapshot ready" snapshot="${snap}" kopia="${kopia}"

    # --- swap the PVC ----------------------------------------------------
    # Source freshness was already asserted in the preflight above; prepare()
    # is what pushes, so by here Flux is guaranteed to hold the new manifests.
    # Getting this wrong deadlocked autobrr: with a stale source Flux recreates
    # the PVC from the old manifests, volsync dataSourceRef and all, which is
    # then immutable and unpopulatable.
    #
    # Expected to fail: the PVC's dataSourceRef is immutable, so Flux cannot
    # apply the new spec until the old PVC is gone.
    flux reconcile kustomization "${app}" -n "${ns}" --timeout=2m >/dev/null 2>&1 || true

    if ! confirm "Delete PVC ${ns}/${app}? (snapshot ${kopia} holds the data)"; then
        kubectl scale "${ctrl}" --replicas "${replicas}" -n "${ns}" >/dev/null
        log error "Aborted by user; scaled back up, PVC untouched"
    fi
    kubectl delete "pvc/${app}" -n "${ns}" --timeout=2m >/dev/null
    log info "PVC deleted, reconciling so kopiur recreates and repopulates it"
    flux reconcile kustomization "${app}" -n "${ns}" --timeout=5m >/dev/null

    # Catch the stale-source failure directly rather than waiting out a Restore
    # that will never be created.
    local dsr
    dsr="$(kubectl get "pvc/${app}" -o jsonpath='{.spec.dataSourceRef.apiGroup}' -n "${ns}" 2>/dev/null || true)"
    [[ "${dsr}" == "kopiur.home-operations.com" ]] ||
        log error "PVC recreated with the wrong dataSourceRef -- delete it and reconcile again" got="${dsr:-none}"

    until [[ -n "$(kubectl get "restore.kopiur.home-operations.com/${app}" -o jsonpath='{.status.phase}' -n "${ns}" 2>/dev/null | grep -E 'Completed|Succeeded|Failed')" ]]; do sleep 5; done
    local rphase
    rphase="$(kubectl get "restore.kopiur.home-operations.com/${app}" -o jsonpath='{.status.phase}' -n "${ns}")"
    [[ "${rphase}" != "Failed" ]] || log error "Restore failed -- see rollback in the resume plan" app="${ns}/${app}"
    kubectl wait --for=jsonpath='{.status.phase}'=Bound "pvc/${app}" --timeout=10m -n "${ns}" >/dev/null
    log info "Restore done" phase="${rphase}"

    # --- prove we restored from OUR snapshot -----------------------------
    # The one assertion that matters. onMissingSnapshot=Continue means a
    # missed snapshot produces an empty PVC instead of an error, so a
    # Completed phase alone proves nothing -- the snapshot ID does.
    #
    # Deliberately NOT gated on confirm(): ASSUME_YES exists to skip the
    # PVC-delete prompt during a batch and must never wave through a restore
    # that took the wrong data. On mismatch, stop with the app still down.
    local restored
    restored="$(kubectl get "restore.kopiur.home-operations.com/${app}" -n "${ns}" \
        -o jsonpath='{.status.snapshot.kopiaSnapshotID}' 2>/dev/null)"
    [[ -n "${restored}" ]] ||
        restored="$(kubectl get "restore.kopiur.home-operations.com/${app}" -n "${ns}" \
            -o jsonpath='{.status.logTail}' 2>/dev/null | grep -oE '[0-9a-f]{32}' | tail -1)"

    if [[ "${restored}" == "${kopia}" ]]; then
        log info "Restored from our pre-migration snapshot" kopia="${kopia}"
    else
        log warn "App left scaled to 0 for inspection" snapshot="${snap}"
        log error "Restore used the WRONG snapshot" expected="${kopia}" got="${restored:-none}"
    fi

    # --- back up ---------------------------------------------------------
    kubectl scale "${ctrl}" --replicas "${replicas}" -n "${ns}" >/dev/null
    kubectl rollout status "${ctrl}" --timeout=5m -n "${ns}" >/dev/null
    log info "Rolled out" controller="${ctrl}"

    kubectl logs -l "app.kubernetes.io/name=${app}" --tail=200 -n "${ns}" 2>/dev/null |
        grep -iE 'corrupt|malformed|panic|fatal' && log warn "Suspicious lines in logs -- check them" || true

    log info "MIGRATED" app="${ns}/${app}" snapshot="${snap}" kopia="${kopia}"
    log info "Pre-migration snapshot kept as a safety net; purge it with: $0 cleanup ${ns} ${app}"
}

# Purge on-demand pre-migration snapshots. They are created with
# deletionPolicy=Retain, so the CR is flipped to Delete first -- otherwise the
# kopia snapshot is orphaned in the repository with no CR tracking it.
function cleanup() {
    local selector=(-A)
    [[ -n "${1:-}" ]] && selector=(-n "$1")

    local targets
    targets="$(kubectl get snapshots.kopiur.home-operations.com "${selector[@]}" -o json |
        jq -r --arg app "${2:-}" '
            [.items[]
             | select(.status.origin == "manual")
             | select($app == "" or (.metadata.name | startswith($app + "-premigration")))
             | "\(.metadata.namespace)/\(.metadata.name)"] | .[]')"

    [[ -n "${targets}" ]] || { log info "No manual snapshots to clean up"; return; }

    echo "${targets}"
    confirm "Delete these snapshot CRs *and* their kopia data?" || { log info "Left alone"; return; }

    while read -r target; do
        local ns="${target%%/*}" name="${target##*/}"
        kubectl patch "snapshot.kopiur.home-operations.com/${name}" -n "${ns}" \
            --type=merge -p '{"spec":{"deletionPolicy":"Delete"}}' >/dev/null
        kubectl delete "snapshot.kopiur.home-operations.com/${name}" -n "${ns}" --timeout=2m >/dev/null
        log info "Purged" snapshot="${target}"
    done <<<"${targets}"
}

# Which apps are still on volsync.
function status() {
    log info "Still on the persistence component:"
    grep -rl 'components/persistence' "${REPO_DIR}/kubernetes/apps" --include=ks.yaml |
        sed "s|${REPO_DIR}/kubernetes/apps/||;s|/ks.yaml||" | sort
    log info "Already on kopiur-tmp:"
    grep -rl 'components/kopiur-tmp' "${REPO_DIR}/kubernetes/apps" --include=ks.yaml |
        sed "s|${REPO_DIR}/kubernetes/apps/||;s|/ks.yaml||" | sort
}

function main() {
    check_cli kubectl flux yq jq git diff
    case "${1:-}" in
        # Git half: rewrite + one commit + one push for the whole batch.
        # Two YubiKey touches total, however many apps are listed.
        prepare)
            shift
            prepare "$@"
            ;;
        # Cluster half: no git, so no YubiKey touch. Run once per app.
        swap)
            [[ $# -eq 3 ]] || log error "usage: $0 swap <namespace> <app>"
            swap "$2" "$3"
            ;;
        # Single-app convenience: prepare one app, then swap it.
        migrate)
            [[ $# -eq 3 ]] || log error "usage: $0 migrate <namespace> <app>"
            prepare "$2/$3"
            swap "$2" "$3"
            ;;
        cleanup) cleanup "${2:-}" "${3:-}" ;;
        status) status ;;
        *) log error "usage: $0 {prepare <ns/app>...|swap <ns> <app>|migrate <ns> <app>|cleanup [<ns> <app>]|status}" ;;
    esac
}

main "$@"
