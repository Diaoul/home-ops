---
apiVersion: v1alpha1
kind: KubeletConfig
config:
  crashLoopBackOff:
    maxContainerRestartPeriod: 60s
  featureGates:
    ResourceHealthStatus: true
  # Well below evictionHard imagefs (85% used), so GC runs before DiskPressure
  imageGCHighThresholdPercent: 70
  imageGCLowThresholdPercent: 65
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
