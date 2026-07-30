---
machine:
  kubelet:
    extraConfig:
      featureGates:
        ResourceHealthStatus: true
      serializeImagePulls: false
    nodeIP:
      validSubnets:
        - {{ .Data.nodeCIDR }}
    extraMounts:
      - destination: /var/mnt/local-hostpath
        type: bind
        source: /var/mnt/local-hostpath
        options:
          - bind
          - rshared
          - rw
