---
apiVersion: v1alpha1
kind: KubeletConfig
config:
  featureGates:
    ResourceHealthStatus: true
  maxParallelImagePulls: 3
  serializeImagePulls: false
  shutdownGracePeriod: 90s
  shutdownGracePeriodCriticalPods: 60s
---
apiVersion: v1alpha1
kind: KubeNodeConfig
nodeIP:
  validSubnets:
    - {{ .Data.nodeCIDR }}
