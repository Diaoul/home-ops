---
apiVersion: v1alpha1
kind: KubeletConfig
config:
  crashLoopBackOff:
    maxContainerRestartPeriod: 60s
  featureGates:
    ResourceHealthStatus: true
  imageMaximumGCAge: 168h
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
