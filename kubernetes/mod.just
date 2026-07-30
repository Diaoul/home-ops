set quiet
set shell := ['bash', '-euo', 'pipefail', '-c']

kubernetes_dir := justfile_dir() + '/kubernetes'

[private]
default:
    just -l kube

[doc('Apply local Flux Kustomization')]
apply-ks dir ks="*":
    just kube render-local-ks "{{ dir }}" "{{ ks }}" \
        | kubectl apply --server-side --force-conflicts --field-manager=kustomize-controller -f /dev/stdin

[doc('Browse a PVC')]
browse-pvc namespace claim:
    kubectl browse-pvc -n {{ namespace }} -i mirror.gcr.io/alpine:latest {{ claim }}

[doc('Delete local Flux Kustomization')]
delete-ks dir ks="*":
    just kube render-local-ks "{{ dir }}" "{{ ks }}" | kubectl delete -f /dev/stdin

[doc('Open a shell on a node')]
node-shell node:
    kubectl debug node/{{ node }} -n default -it --image="mirror.gcr.io/alpine:latest" --profile sysadmin
    kubectl delete pod -n default -l app.kubernetes.io/managed-by=kubectl-debug

[doc('Prune pods in Failed, Pending, or Succeeded state')]
prune-pods:
    for phase in Failed Pending Succeeded; do \
        kubectl delete pods -A --field-selector status.phase="$phase" --ignore-not-found=true; \
    done

[doc('Take an on-demand kopiur snapshot of every app')]
snapshot:
    stamp="manual-$(date -u +%Y%m%d%H%M%S)"; \
    kubectl get snapshotpolicy.kopiur.home-operations.com --no-headers -A | while read -r ns name _; do \
        printf 'apiVersion: kopiur.home-operations.com/v1alpha1\nkind: Snapshot\nmetadata:\n  name: %s-%s\n  namespace: %s\nspec:\n  deletionPolicy: Delete\n  policyRef:\n    name: %s\n' \
            "$name" "$stamp" "$ns" "$name" | kubectl apply -f -; \
    done; \
    echo "Watch with: kubectl get snapshots.kopiur.home-operations.com -A | grep $stamp"

[doc('Delete on-demand kopiur snapshots (origin=manual)')]
snapshot-prune:
    kubectl get snapshots.kopiur.home-operations.com -A -o json \
        | jq -r '.items[]|select(.status.origin == "manual")|"\(.metadata.namespace) \(.metadata.name)"' \
        | while read -r ns name; do \
            kubectl -n "$ns" patch snapshot.kopiur.home-operations.com "$name" --type merge -p '{"spec":{"deletionPolicy":"Delete"}}'; \
            kubectl -n "$ns" delete snapshot.kopiur.home-operations.com "$name"; \
        done

[doc('Sync ExternalSecrets')]
sync-es:
    kubectl get es --no-headers -A | while read -r ns name _; do \
        kubectl -n "$ns" annotate --field-manager flux-client-side-apply --overwrite es "$name" force-sync="$(date +%s)"; \
    done

[doc('Sync GitRepositories')]
sync-git:
    kubectl get gitrepo --no-headers -A | while read -r ns name _; do \
        kubectl -n "$ns" annotate --field-manager flux-client-side-apply --overwrite gitrepo "$name" reconcile.fluxcd.io/requestedAt="$(date +%s)"; \
    done

[doc('Sync HelmReleases')]
sync-hr:
    kubectl get hr --no-headers -A | while read -r ns name _; do \
        kubectl -n "$ns" annotate --field-manager flux-client-side-apply --overwrite hr "$name" reconcile.fluxcd.io/requestedAt="$(date +%s)" reconcile.fluxcd.io/forceAt="$(date +%s)"; \
    done

[doc('Sync Kustomizations')]
sync-ks:
    kubectl get ks --no-headers -A | while read -r ns name _; do \
        kubectl -n "$ns" annotate --field-manager flux-client-side-apply --overwrite ks "$name" reconcile.fluxcd.io/requestedAt="$(date +%s)"; \
    done

[doc('Sync OCIRepositories')]
sync-oci:
    kubectl get ocirepo --no-headers -A | while read -r ns name _; do \
        kubectl -n "$ns" annotate --field-manager flux-client-side-apply --overwrite ocirepo "$name" reconcile.fluxcd.io/requestedAt="$(date +%s)"; \
    done

[doc('View a secret')]
view-secret namespace secret:
    kubectl view-secret -n {{ namespace }} {{ secret }}

[private]
render-local-ks dir ks="*":
    flux-local build ks --all-namespaces --path "{{ kubernetes_dir }}/apps/{{ dir }}" {{ if ks != "*" { ks } else { "" } }}
