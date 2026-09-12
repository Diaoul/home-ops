---
cluster:
  etcd:
    extraArgs:
      listen-metrics-urls: http://0.0.0.0:2381
      # Raised: slow WAL fsync on the SATA SSDs spikes past the 100ms default,
      # causing spurious leader elections.
      heartbeat-interval: "250"
      election-timeout: "2500"
    advertisedSubnets:
      - {{ .Data.nodeCIDR }}
---
# Allow scheduling on control-plane nodes
apiVersion: v1alpha1
kind: KubeNodeConfig
taints:
  node-role.kubernetes.io/control-plane:
    $patch: delete
---
apiVersion: v1alpha1
kind: KubeAdmissionControlConfig
name: PodSecurity
$patch: delete
---
apiVersion: v1alpha1
kind: KubeAuditPolicyConfig
$patch: delete
---
apiVersion: v1alpha1
kind: KubeAPIServerConfig
certExtraSANs:
  {{- range .Data.certSANs }}
  - "{{ . }}"
  {{- end }}
extraArgs:
  # https://kubernetes.io/docs/tasks/extend-kubernetes/configure-aggregation-layer/
  enable-aggregator-routing: "true"
  feature-gates: HPAScaleToZero=true,MutatingAdmissionPolicy=true,ResourceHealthStatus=true
  runtime-config: admissionregistration.k8s.io/v1beta1=true
---
apiVersion: v1alpha1
kind: KubeControllerManagerConfig
extraArgs:
  bind-address: 0.0.0.0
  feature-gates: HPAScaleToZero=true
---
apiVersion: v1alpha1
kind: KubeCoreDNSConfig
enabled: false
---
# Disable built-in CNI and kube-proxy to use Cilium
apiVersion: v1alpha1
kind: KubeFlannelCNIConfig
$patch: delete
---
apiVersion: v1alpha1
kind: KubeProxyConfig
enabled: false
---
apiVersion: v1alpha1
kind: KubeSchedulerConfig
extraArgs:
  bind-address: 0.0.0.0
config:
  profiles:
    - schedulerName: default-scheduler
      plugins:
        score:
          disabled:
            - name: ImageLocality
      pluginConfig:
        - name: PodTopologySpread
          args:
            defaultingType: List
            defaultConstraints:
              - maxSkew: 1
                topologyKey: kubernetes.io/hostname
                whenUnsatisfiable: ScheduleAnyway
