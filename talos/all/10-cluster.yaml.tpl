---
cluster:
  network:
    podSubnets: ["{{ .Data.podCIDR }}"]
    serviceSubnets: ["{{ .Data.svcCIDR }}"]
machine:
  certSANs:
    {{- range .Data.certSANs }}
    - "{{ . }}"
    {{- end }}
