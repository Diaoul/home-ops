---
machine:
  certSANs:
    {{- range .Data.certSANs }}
    - "{{ . }}"
    {{- end }}
---
apiVersion: v1alpha1
kind: KubeNetworkConfig
podSubnets: ["{{ .Data.podCIDR }}"]
serviceSubnets: ["{{ .Data.svcCIDR }}"]
