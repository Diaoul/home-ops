---
cluster:
  allowSchedulingOnControlPlanes: true
  apiServer:
    admissionControl:
      $patch: delete
    auditPolicy:
      $patch: delete
    certSANs:
      {{- range .Data.certSANs }}
      - "{{ . }}"
      {{- end }}
    extraArgs:
      # https://kubernetes.io/docs/tasks/extend-kubernetes/configure-aggregation-layer/
      enable-aggregator-routing: true
      feature-gates: HPAScaleToZero=true,MutatingAdmissionPolicy=true,ResourceHealthStatus=true
      runtime-config: admissionregistration.k8s.io/v1beta1=true
  controllerManager:
    extraArgs:
      bind-address: 0.0.0.0
      feature-gates: HPAScaleToZero=true
  coreDNS:
    disabled: true
  # Disable built-in CNI to use Cilium
  network:
    cni:
      name: none
  etcd:
    extraArgs:
      listen-metrics-urls: http://0.0.0.0:2381
      # Raised: slow WAL fsync on the SATA SSDs spikes past the 100ms default,
      # causing spurious leader elections.
      heartbeat-interval: "250"
      election-timeout: "2500"
    advertisedSubnets:
      - {{ .Data.nodeCIDR }}
  proxy:
    disabled: true
  scheduler:
    extraArgs:
      bind-address: 0.0.0.0
    config:
      apiVersion: kubescheduler.config.k8s.io/v1
      kind: KubeSchedulerConfiguration
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
