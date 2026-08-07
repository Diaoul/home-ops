set quiet
set shell := ['bash', '-euo', 'pipefail', '-c']
set script-interpreter := ['bash', '-euo', 'pipefail']

# Module recipes run with the working directory set to talos/; paths are relative.

[private]
default:
    just -l talos

# Day-2 apply/upgrade recipes rely on topf's built-in diff-and-confirm
# prompt; only the destructive reset recipes disable it in favour of just's
# own confirmation.

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
    id="$(topf schematic-ids --nodes-filter "^{{ node }}$" --submit-to-factory)"
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

# topf's --nodes-filter exits 0 when it matches nothing; this fails loudly instead.
[private]
node-ip node:
    yq -e '.nodes[] | select(.host == "{{ node }}") | .ip' topf.yaml

[doc('List all nodes and their current state')]
nodes:
    topf nodes

# Recipes take a node NAME; talosctl wants an address, so resolve it.
[doc('Reboot a node')]
reboot-node node:
    gum confirm "Reboot node {{ node }}?" --default="No" && \
        talosctl -n "$(just talos node-ip {{ node }})" reboot -m powercycle || exit 0

[doc('Render Talos machine configs to talos/rendered')]
render:
    topf render --output ./rendered

# --full=false wipes only STATE and EPHEMERAL; topf defaults to the whole disk.
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

# Manual fallback; tuppr normally drives upgrades. powercycle because the
# schematic sets kexec_load_disabled=1, so topf's default kexec cannot work.
#
# --submit-to-factory registers the schematic with the Image Factory. topf
# computes the ID locally by default, so a schematic.yaml change yields an ID
# the factory has never built and the node fails the upgrade with
# "failed to resolve reference ... not found". Submission is idempotent and the
# ID is a deterministic hash, so this only ever creates what the config already
# describes. `just talos schematic-ids` stays read-only for inspection.
[doc('Upgrade Talos on all nodes, one at a time (asks first)')]
upgrade:
    topf upgrade --reboot-mode=powercycle --submit-to-factory

[doc('Upgrade Talos on a single node (asks first)')]
upgrade-node node:
    just talos node-ip {{ node }} > /dev/null
    topf upgrade --nodes-filter "^{{ node }}$" --reboot-mode=powercycle --submit-to-factory
