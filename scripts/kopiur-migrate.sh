#!/usr/bin/env bash

# Migrate one app from the volsync `persistence` component to `kopiur-tmp`.
#
# The PVC's dataSourceRef is immutable, so migrating means deleting and
# recreating the PVC. To make that safe this script:
#   1. scales the app to 0 (quiesces SQLite -- WAL gets checkpointed)
#   2. fingerprints the volume from a throwaway pod
#   3. takes an on-demand kopiur snapshot of the quiesced volume
#   4. rewrites ks.yaml, commits, pushes
#   5. deletes the PVC so kopiur's Restore repopulates it
#   6. fingerprints the *restored* volume from a throwaway pod, before the
#      app runs again, and requires it to match step 2 byte for byte
#   7. scales the app back up and checks it is healthy
#
# Both fingerprints are taken with no app running, which is why they can be
# compared exactly. Comparing a pre-shutdown fingerprint against a running
# app is not meaningful: the clean shutdown itself rewrites SQLite files.
#
# Delete this script once the migration is finished (see the final fold-in in
# ~/.claude/plans/kopiur-migration-resume.md).

set -Eeuo pipefail

# shellcheck source=./lib/common.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"

REPO_DIR="$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)"
SCRATCH="${TMPDIR:-/tmp}/kopiur-migrate"
ASSUME_YES="${ASSUME_YES:-false}"

# Emits a file count then a sha256 per file, with relative paths so that two
# fingerprints compare directly. The -wal/-shm/-lock/-pid patterns are quoted
# so the container's shell cannot glob-expand them before find runs.
#
# `du` output is prefixed with '#' and excluded from the comparison on purpose:
# it counts the apparent size of directories too, and a restored volume is a
# freshly formatted filesystem whose directory blocks are allocated
# differently. cross-seed restored with all 680 file hashes identical but a
# 12288-byte (3 x 4096) du difference. Content hashes are the real assertion.
FINGERPRINT_CMD='cd /data \
  && printf "files=%s\n" "$(find . -type f | wc -l | tr -d " ")" \
  && printf "# apparent_bytes=%s\n" "$(du -sb . | cut -f1)" \
  && find . -type f ! \( -name "*-wal" -o -name "*-shm" -o -name "*.lock" -o -name "*.pid" \) \
     | sort | xargs -r sha256sum'

# Read-only fingerprint of a PVC, taken from a throwaway pod so that no
# application is running while we read. Runs as root because app data is
# routinely mode 0600 owned by the app's uid.
function fingerprint_pvc() {
    local ns="$1" pvc="$2" out="$3"
    local pod="fingerprint-${pvc}-$$"
    local overrides

    # Built with jq so that quoting in FINGERPRINT_CMD survives into the JSON.
    overrides="$(jq -n --arg pvc "${pvc}" --arg cmd "${FINGERPRINT_CMD}" '{
      spec: {
        securityContext: {runAsUser: 0, runAsGroup: 0},
        restartPolicy: "Never",
        containers: [{
          name: "fingerprint",
          image: "docker.io/library/busybox:stable",
          command: ["sh", "-c", $cmd],
          volumeMounts: [{name: "data", mountPath: "/data", readOnly: true}]
        }],
        volumes: [{name: "data", persistentVolumeClaim: {claimName: $pvc}}]
      }
    }')"

    kubectl run "${pod}" \
        --image=docker.io/library/busybox:stable \
        --restart=Never \
        --quiet \
        --overrides="${overrides}" \
        -n "${ns}" >/dev/null

    kubectl wait --for=jsonpath='{.status.phase}'=Succeeded "pod/${pod}" --timeout=5m -n "${ns}" >/dev/null
    kubectl logs "pod/${pod}" -n "${ns}" >"${out}"
    kubectl delete "pod/${pod}" -n "${ns}" --wait=false >/dev/null
    log info "Fingerprinted volume" pvc="${ns}/${pvc}" \
        "$(grep -m1 '^files=' "${out}")" \
        "hashed=$(grep -c '^[0-9a-f]\{64\}  ' "${out}")"
}

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

function migrate() {
    local ns="$1" app="$2"
    local ks="${REPO_DIR}/kubernetes/apps/${ns}/${app}/ks.yaml"
    local snap="${app}-premigration-$(date -u +%Y%m%d%H%M%S)"

    mkdir -p "${SCRATCH}"
    [[ -f "${ks}" ]] || log error "No ks.yaml" path="${ks}"

    # --- preflight -------------------------------------------------------
    grep -q 'components/persistence' "${ks}" || log error "Not on the persistence component (already migrated?)" app="${ns}/${app}"
    [[ -n "$(kubectl get pods -n volsync-system --no-headers 2>/dev/null)" ]] || log error "volsync is gone -- rollback would be impossible"

    local unready
    unready="$(kubectl get kustomizations -A -o json |
        jq -r '[.items[]|select(.status.conditions[]?|select(.type=="Ready" and .status!="True"))|"\(.metadata.namespace)/\(.metadata.name)"]|join(",")')"
    [[ -z "${unready}" ]] || log error "Flux is not clean; fix before migrating" unready="${unready}"

    # A dirty ks.yaml usually means an earlier run died between the rewrite and
    # the push. Re-running from the top would take a second snapshot, so commit
    # or revert that file by hand first.
    [[ -z "$(git -C "${REPO_DIR}" status --porcelain -- "${ks}")" ]] ||
        log error "ks.yaml has uncommitted changes -- commit or revert it, then re-run" path="${ks}"

    # --- discover the workload ------------------------------------------
    local ctrl replicas
    ctrl="$(kubectl get deploy,sts -l "app.kubernetes.io/name=${app}" -o name --no-headers -n "${ns}" | head -1)"
    [[ -n "${ctrl}" ]] || log error "No deployment/statefulset found" app="${ns}/${app}"
    replicas="$(kubectl get "${ctrl}" -o jsonpath='{.spec.replicas}' -n "${ns}")"
    log info "Migrating" app="${ns}/${app}" controller="${ctrl}" replicas="${replicas}"

    # --- quiesce ---------------------------------------------------------
    kubectl scale "${ctrl}" --replicas 0 -n "${ns}" >/dev/null
    log info "Scaled to 0, waiting for pods to go away"
    until [[ "$(kubectl get pods -l "app.kubernetes.io/name=${app}" --no-headers -n "${ns}" 2>/dev/null | wc -l)" == "0" ]]; do sleep 3; done

    fingerprint_pvc "${ns}" "${app}" "${SCRATCH}/${app}-pre.txt"

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

    # --- rewrite ks.yaml -------------------------------------------------
    yq -i '
      .spec.components = ((.spec.components // []) | map(select(test("components/(persistence|kopiur)$") | not)))
      | .spec.dependsOn = ((.spec.dependsOn // []) | map(select(.name != "volsync")))
    ' "${ks}"
    yq -e '.spec.components | any_c(. == "../../../../components/kopiur-tmp")' "${ks}" >/dev/null 2>&1 ||
        yq -i '.spec.components += ["../../../../components/kopiur-tmp"]' "${ks}"

    log info "Validating manifests"
    bash "${REPO_DIR}/scripts/kubeconform.sh" "${REPO_DIR}/kubernetes" >"${SCRATCH}/${app}-kubeconform.log" 2>&1 ||
        log error "kubeconform failed" log="${SCRATCH}/${app}-kubeconform.log"

    git_retry "commit" git -C "${REPO_DIR}" commit -q -m "feat(${app}): migrate persistence->kopiur

Drop the volsync persistence component and the snapshot-only kopiur
component in favour of kopiur-tmp, which owns both the PVC and the Restore.
Also drop the now-unneeded volsync dependsOn.

Pre-migration quiesced snapshot: ${kopia}

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>" -- "${ks}"
    git_retry "push" git -C "${REPO_DIR}" push -q origin HEAD
    log info "Pushed" commit="$(git -C "${REPO_DIR}" rev-parse --short HEAD)"

    # --- swap the PVC ----------------------------------------------------
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

    until [[ -n "$(kubectl get "restore.kopiur.home-operations.com/${app}" -o jsonpath='{.status.phase}' -n "${ns}" 2>/dev/null | grep -E 'Completed|Succeeded|Failed')" ]]; do sleep 5; done
    local rphase
    rphase="$(kubectl get "restore.kopiur.home-operations.com/${app}" -o jsonpath='{.status.phase}' -n "${ns}")"
    [[ "${rphase}" != "Failed" ]] || log error "Restore failed -- see rollback in the resume plan" app="${ns}/${app}"
    kubectl wait --for=jsonpath='{.status.phase}'=Bound "pvc/${app}" --timeout=10m -n "${ns}" >/dev/null
    log info "Restore done" phase="${rphase}"

    # --- prove the data came back ----------------------------------------
    # restore.yaml sets onMissingSnapshot=Continue, so a missed snapshot
    # yields an *empty* PVC rather than an error. Never trust phases alone.
    fingerprint_pvc "${ns}" "${app}" "${SCRATCH}/${app}-post.txt"
    if diff <(grep -v '^#' "${SCRATCH}/${app}-pre.txt") \
            <(grep -v '^#' "${SCRATCH}/${app}-post.txt") >"${SCRATCH}/${app}-diff.txt"; then
        log info "Volume is byte-identical to the pre-migration fingerprint"
    else
        log warn "FINGERPRINT MISMATCH -- inspect before trusting this app" diff="${SCRATCH}/${app}-diff.txt"
        cat "${SCRATCH}/${app}-diff.txt"
        confirm "Scale ${app} back up anyway?" || log error "Left scaled to 0 for inspection"
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
        migrate) [[ $# -eq 3 ]] || log error "usage: $0 migrate <namespace> <app>"; migrate "$2" "$3" ;;
        cleanup) cleanup "${2:-}" "${3:-}" ;;
        status)  status ;;
        *)       log error "usage: $0 {migrate <ns> <app>|cleanup [<ns> <app>]|status}" ;;
    esac
}

main "$@"
