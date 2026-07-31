set quiet
set shell := ['bash', '-euo', 'pipefail', '-c']
set script-interpreter := ['bash', '-euo', 'pipefail']

# Module recipes already run with the working directory set to talos/, so paths
# below are relative to it.

[private]
default:
    just -l talos

# Day-2 apply/upgrade recipes rely on topf's built-in diff-and-confirm prompt;
# only the destructive reset recipes disable it in favour of just's own
# confirmation.

[doc('Apply Talos config to all nodes (shows a diff and asks first)')]
apply:
    topf apply

[arg('mode', pattern='auto|reboot|no-reboot|staged|try')]
[doc('Apply Talos config to a node (shows a diff and asks first)')]
apply-node node mode='auto':
    just talos node-ip {{ node }} > /dev/null
    topf apply --nodes-filter "^{{ node }}$" --mode "{{ mode }}"

[doc('Show pending config changes without applying them')]
diff:
    topf apply --dry-run

[doc('Download the Talos installer ISO for a node')]
[script]
download-image node:
    just talos node-ip {{ node }} > /dev/null
    id="$(topf schematic-ids --nodes-filter "^{{ node }}$")"
    version="$(yq -e '.talosVersion' topf.yaml)"
    mkdir -p images
    gum spin --title "Downloading Talos ${version} ..." -- \
    curl -sfL --remove-on-error --retry 5 --retry-delay 5 --retry-all-errors \
        -o "images/talos-${version}-secureboot-${id:0:8}.iso" \
        "https://factory.talos.dev/image/${id}/${version}/metal-amd64-secureboot.iso"
    just log info "Downloaded Talos" version "${version}" schematic "${id}"

[doc('Fetch the kubeconfig from the cluster')]
kubeconfig:
    topf kubeconfig > "{{ justfile_dir() }}/kubeconfig"

# Fails loudly when the name matches nothing, so a typo cannot silently target
# no node (topf's --nodes-filter exits 0 in that case).
[private]
node-ip node:
    yq -e '.nodes[] | select(.host == "{{ node }}") | .ip' topf.yaml

[doc('List all nodes and their current state')]
nodes:
    topf nodes

# Recipes below take a node NAME (e.g. k8s-node-1), matching topf's
# --nodes-filter. talosctl wants an address, so resolve it out of topf.yaml.
[doc('Reboot a node')]
reboot-node node:
    gum confirm "Reboot node {{ node }}?" --default="No" && \
        talosctl -n "$(just talos node-ip {{ node }})" reboot -m powercycle || exit 0

[doc('Render Talos machine configs to talos/rendered')]
render:
    topf render --output ./rendered

# --full=false wipes only STATE and EPHEMERAL, matching what these recipes did
# under talhelper. topf defaults to --full=true, which takes the whole disk
# including the local-hostpath user volume.
[confirm("This will destroy the cluster and wipe STATE + EPHEMERAL on ALL nodes — continue? [y/N]")]
[doc('Reset all nodes back to maintenance mode (DESTRUCTIVE)')]
reset:
    topf reset --full=false --confirm=false

[confirm("This will wipe STATE + EPHEMERAL on the node — continue? [y/N]")]
[doc('Reset a single node back to maintenance mode (DESTRUCTIVE)')]
reset-node node:
    just talos node-ip {{ node }} > /dev/null
    topf reset --nodes-filter "^{{ node }}$" --full=false --confirm=false

[doc('Shutdown a node')]
shutdown-node node:
    gum confirm "Shutdown node {{ node }}?" --default="No" && \
        talosctl -n "$(just talos node-ip {{ node }})" shutdown --force || exit 0

[doc('Generate the talosconfig client config')]
talosconfig:
    topf talosconfig > talosconfig

# topf intentionally does not manage Kubernetes upgrades
[doc('Upgrade Kubernetes version on the cluster')]
upgrade-k8s:
    talosctl --nodes "$(yq -e '[.nodes[] | select(.role == "control-plane")][0].ip' topf.yaml)" \
        upgrade-k8s --to "$(yq -e '.kubernetesVersion' topf.yaml)"

# Talos upgrades are normally driven in-cluster by tuppr; these are the manual
# fallback.
[doc('Upgrade Talos on all nodes, one at a time (asks first)')]
upgrade:
    topf upgrade

[doc('Upgrade Talos on a single node (asks first)')]
upgrade-node node:
    just talos node-ip {{ node }} > /dev/null
    topf upgrade --nodes-filter "^{{ node }}$"
