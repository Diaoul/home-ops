---
machine:
  kubelet:
    extraConfig:
      featureGates:
        ResourceHealthStatus: true
      maxParallelImagePulls: 3
      serializeImagePulls: false
      shutdownGracePeriod: 90s
      shutdownGracePeriodCriticalPods: 60s
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
