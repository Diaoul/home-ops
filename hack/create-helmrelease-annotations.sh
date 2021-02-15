#!/bin/bash
shopt -s globstar

# shellcheck disable=SC2155
REPO_ROOT=$(git rev-parse --show-toplevel)
CLUSTER_ROOT="${REPO_ROOT}/cluster"
HELM_REPOSITORIES="${CLUSTER_ROOT}/flux-system/helm-chart-repositories"

# Ensure yq exist
command -v yq >/dev/null 2>&1 || {
    echo >&2 "yq is not installed. Aborting."
    exit 1
}

for helm_release in "${CLUSTER_ROOT}"/**/helmrelease.yaml; do
    # ignore wrong apiVersion and non HelmReleases
    grep -q "apiVersion: helm.toolkit.fluxcd.io/v2beta1" "${helm_release}"
    api_version_status=$?
    grep -q "kind: HelmRelease" "${helm_release}"
    kind_status=$?

    [[ ${api_version_status} -eq 1 || ${kind_status} -eq 1 ]] && continue

    for helm_repository in "${HELM_REPOSITORIES}"/*.yaml; do
        chart_name=$(awk '/metadata/{flag=1} flag && /name:/{print $NF;flag=""}' ${helm_repository})
        chart_url=$(awk '/spec/{flag=1} flag && /url:/{print $NF;flag=""}' ${helm_repository})

        grep -q "name: ${chart_name}" "${helm_release}"
        chart_status=$?

        if [[ "${chart_status}" -eq 0 ]]; then
            echo "Annotating $(basename "$(dirname "${helm_release}")") with ${chart_name} for renovatebot..."
            # delete "renovate: registryUrl=" line
            sed -i "/renovate: registryUrl=/d" "${helm_release}"
            # insert "renovate: registryUrl=" line
            sed -i "/.*chart: .*/i \ \ \ \ \ \ # renovate: registryUrl=${chart_url}" "${helm_release}"
            break
        fi
    done
done
