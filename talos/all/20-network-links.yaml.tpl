{{- /*
Node networking as Talos 1.13+ typed network documents. The MAC-matched
link is enslaved to a single-link active-backup bond so every consumer
(Cilium devices, VLANs, the VIP, metrics) sees a stable interface name,
bond0, regardless of kernel NIC naming; a second NIC can join the bond
later without renaming anything. The bond name is also referenced by
`devices` in the cilium HelmRelease.

bond0 stays on DHCP; only the tagged VLANs carry static addresses, and their
last octet always matches bond0's, so it is derived here.
*/ -}}
{{- $octet := last (splitList "." (printf "%s" .Node.IP)) }}
---
apiVersion: v1alpha1
kind: LinkAliasConfig
name: bond0-m0
selector:
  match: glob("{{ .Node.Data.macAddr }}", mac(link.hardware_addr)) && glob("e1000e", link.driver)
---
apiVersion: v1alpha1
kind: BondConfig
name: bond0
links:
  - bond0-m0
bondMode: active-backup
mtu: 9000
---
apiVersion: v1alpha1
kind: DHCPv4Config
name: bond0
{{- if eq .Node.Role "control-plane" }}
---
apiVersion: v1alpha1
kind: Layer2VIPConfig
name: 10.0.3.3
link: bond0
{{- end }}
---
apiVersion: v1alpha1
kind: VLANConfig
name: bond0.30 # IOT
vlanID: 30
parent: bond0
mtu: 1500
addresses:
  - address: 10.0.30.{{ $octet }}/24
---
apiVersion: v1alpha1
kind: VLANConfig
name: bond0.90 # VPN
vlanID: 90
parent: bond0
mtu: 1500
addresses:
  - address: 10.0.90.{{ $octet }}/24
