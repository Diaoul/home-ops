set quiet
set shell := ['bash', '-euo', 'pipefail', '-c']
set script-interpreter := ['bash', '-euo', 'pipefail']

talos_dir := justfile_dir() + '/talos'

[private]
default:
    just -l talos

# Day-2 apply/upgrade recipes rely on topf's built-in diff-and-confirm prompt;
# only the destructive reset recipes disable it in favour of just's own
# confirmation.

[doc('Apply Talos config to all nodes (shows a diff and asks first)')]
[working-directory('../talos')]
apply:
    topf apply

[doc('Apply Talos config to a node (shows a diff and asks first)')]
[working-directory('../talos')]
apply-node node mode='auto':
    topf apply --nodes-filter "^{{ node }}$" --mode "{{ mode }}"

[doc('Show pending config changes without applying them')]
[working-directory('../talos')]
diff:
    topf apply --dry-run

[doc('Download the Talos installer ISO for a node')]
[script]
[working-directory('../talos')]
download-image node:
    id="$(topf schematic-ids --nodes-filter "^{{ node }}$")"
    version="$(yq -e '.talosVersion' topf.yaml)"
    mkdir -p "{{ talos_dir }}/images"
    gum spin --title "Downloading Talos ${version} ..." -- \
    curl -sfL --remove-on-error --retry 5 --retry-delay 5 --retry-all-errors \
        -o "{{ talos_dir }}/images/talos-${version}-secureboot-${id:0:8}.iso" \
        "https://factory.talos.dev/image/${id}/${version}/metal-amd64-secureboot.iso"
    just log info "Downloaded Talos" version "${version}" schematic "${id}"

[doc('Fetch the kubeconfig from the cluster')]
[working-directory('../talos')]
kubeconfig:
    topf kubeconfig > "{{ justfile_dir() }}/kubeconfig"

[doc('List all nodes and their current state')]
[working-directory('../talos')]
nodes:
    topf nodes

[doc('Reboot a node')]
reboot-node node:
    gum confirm "Reboot node {{ node }}?" --default="No" && \
        talosctl -n "{{ node }}" reboot -m powercycle || exit 0

[doc('Render Talos machine configs to talos/rendered')]
[working-directory('../talos')]
render:
    topf render --output ./rendered

[confirm("This will destroy the cluster and reset ALL nodes to maintenance mode — continue? [y/N]")]
[doc('Reset all nodes back to maintenance mode (DESTRUCTIVE)')]
[working-directory('../talos')]
reset:
    topf reset --confirm=false

[confirm("This will reset the node to maintenance mode — continue? [y/N]")]
[doc('Reset a single node back to maintenance mode (DESTRUCTIVE)')]
[working-directory('../talos')]
reset-node node:
    topf reset --nodes-filter "^{{ node }}$" --confirm=false

[doc('Shutdown a node')]
shutdown-node node:
    gum confirm "Shutdown node {{ node }}?" --default="No" && \
        talosctl -n "{{ node }}" shutdown --force || exit 0

[doc('Generate the talosconfig client config')]
[working-directory('../talos')]
talosconfig:
    topf talosconfig > "{{ talos_dir }}/talosconfig"

# topf intentionally does not manage Kubernetes upgrades
[doc('Upgrade Kubernetes version on the cluster')]
[working-directory('../talos')]
upgrade-k8s:
    talosctl --nodes "$(yq -e '[.nodes[] | select(.role == "control-plane")][0].ip' topf.yaml)" \
        upgrade-k8s --to "$(yq -e '.kubernetesVersion' topf.yaml)"

# Talos upgrades are normally driven in-cluster by tuppr; these are the manual
# fallback.
[doc('Upgrade Talos on all nodes, one at a time (asks first)')]
[working-directory('../talos')]
upgrade:
    topf upgrade

[doc('Upgrade Talos on a single node (asks first)')]
[working-directory('../talos')]
upgrade-node node:
    topf upgrade --nodes-filter "^{{ node }}$"
