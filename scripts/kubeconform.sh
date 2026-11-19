#!/usr/bin/env bash

set -euo pipefail

KUBERNETES_DIR=$1

[[ -z "${KUBERNETES_DIR}" ]] && echo "Kubernetes location not specified" && exit 1

kustomize_args=("--load-restrictor=LoadRestrictionsNone")
kustomize_config="kustomization.yaml"
cache_dir=$(mktemp -d)
trap 'rm -rf "${cache_dir}"' EXIT

# DNSEndpoint: the schema checks dnsName against DNS-1123, which an unsubstituted ${DOMAIN} fails.
# Kanidm*: kaniop ships no CRD files, so no schema location serves them, and every lookup is a
# request that fails the run when a host errors instead of answering 404.
kubeconform_args=(
    "-strict"
    "-ignore-missing-schemas"
    "-cache"
    "${cache_dir}"
    "-skip"
    "Gateway,HTTPRoute,Secret,DNSEndpoint,Kanidm,KanidmBackupRepository,KanidmBackupSchedule,KanidmGroup,KanidmOAuth2Client,KanidmPersonAccount"
    "-schema-location"
    "default"
    "-schema-location"
    "https://k8s-schemas.home-operations.com/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json"
    "-schema-location"
    "https://kubernetes-schemas.pages.dev/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json"
    "-schema-location"
    "https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json"
    "-verbose"
)

echo "=== Validating standalone manifests in ${KUBERNETES_DIR}/flux ==="
find "${KUBERNETES_DIR}/flux" -maxdepth 1 -type f -name '*.yaml' -print0 | while IFS= read -r -d $'\0' file;
do
    kubeconform "${kubeconform_args[@]}" "${file}"
    if [[ ${PIPESTATUS[0]} != 0 ]]; then
        exit 1
    fi
done

echo "=== Validating kustomizations in ${KUBERNETES_DIR}/flux ==="
find "${KUBERNETES_DIR}/flux" -type f -name $kustomize_config -print0 | while IFS= read -r -d $'\0' file;
do
    echo "=== Validating kustomizations in ${file/%$kustomize_config} ==="
    kustomize build "${file/%$kustomize_config}" "${kustomize_args[@]}" | kubeconform "${kubeconform_args[@]}"
    if [[ ${PIPESTATUS[0]} != 0 ]]; then
        exit 1
    fi
done

echo "=== Validating kustomizations in ${KUBERNETES_DIR}/apps ==="
find "${KUBERNETES_DIR}/apps" -type f -name $kustomize_config -print0 | while IFS= read -r -d $'\0' file;
do
    echo "=== Validating kustomizations in ${file/%$kustomize_config} ==="
    kustomize build "${file/%$kustomize_config}" "${kustomize_args[@]}" | kubeconform "${kubeconform_args[@]}"
    if [[ ${PIPESTATUS[0]} != 0 ]]; then
        exit 1
    fi
done
