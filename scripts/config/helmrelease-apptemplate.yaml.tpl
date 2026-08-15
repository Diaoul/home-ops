---
# yaml-language-server: $schema=https://k8s-schemas.home-operations.com/helm.toolkit.fluxcd.io/helmrelease_v2.json
# Only the keys are read; every value here is a placeholder.
# A "*" key stands for any name the manifest uses at that level (controller, container,
# probe, volume), so one entry orders all of them.
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: app
  namespace: default
  labels: {}
  annotations: {}
spec:
  interval: 30m
  timeout: 5m
  suspend: false
  chartRef:
    kind: OCIRepository
    name: app-template
    namespace: flux-system
  dependsOn:
    - name: dependency
      namespace: namespace
  install:
    remediation:
      retries: 3
  upgrade:
    cleanupOnFail: true
    remediation:
      strategy: rollback
      retries: 3
  driftDetection:
    mode: enabled
    ignore: []
  maxHistory: 5
  valuesFrom:
    - kind: ConfigMap
      name: values
      valuesKey: values.yaml
  values:
    defaultPodOptions:
      terminationGracePeriodSeconds: 30
      securityContext:
        runAsNonRoot: true
        runAsUser: 568
        runAsGroup: 568
        fsGroup: 568
        fsGroupChangePolicy: OnRootMismatch
        seccompProfile:
          type: RuntimeDefault
    controllers:
      "*":
        enabled: true
        type: deployment
        annotations: {}
        labels: {}
        strategy: RollingUpdate
        replicas: 1
        rollingUpdate:
          unavailable: 0
        serviceAccount:
          identifier: default
        initContainers:
          "*":
            dependsOn: []
            image:
              repository: repo
              tag: tag
              pullPolicy: IfNotPresent
            command: []
            args: []
            env: {}
            envFrom: []
            securityContext:
              allowPrivilegeEscalation: false
              readOnlyRootFilesystem: true
              capabilities: {}
            resources:
              requests: {}
              limits: {}
        containers:
          "*":
            image:
              repository: repo
              tag: tag
              pullPolicy: IfNotPresent
            command: []
            args: []
            env: {}
            envFrom: []
            probes:
              "*":
                enabled: true
                custom: true
                spec:
                  httpGet:
                    path: /
                    port: 80
                    scheme: HTTP
                  tcpSocket:
                    port: 80
                  exec:
                    command: []
                  initialDelaySeconds: 0
                  periodSeconds: 10
                  timeoutSeconds: 1
                  failureThreshold: 3
                  successThreshold: 1
            securityContext:
              allowPrivilegeEscalation: false
              readOnlyRootFilesystem: true
              capabilities: {}
            resources:
              requests: {}
              limits: {}
        pod:
          annotations: {}
          labels: {}
          securityContext:
            runAsNonRoot: true
            runAsUser: 568
            runAsGroup: 568
            fsGroup: 568
            fsGroupChangePolicy: OnRootMismatch
            seccompProfile:
              type: RuntimeDefault
          hostNetwork: false
          dnsPolicy: ClusterFirst
          nodeSelector: {}
          tolerations: []
          affinity: {}
          topologySpreadConstraints:
            - maxSkew: 1
              topologyKey: kubernetes.io/hostname
              whenUnsatisfiable: DoNotSchedule
              labelSelector: {}
    service:
      "*":
        enabled: true
        primary: true
        controller: controller
        type: ClusterIP
        annotations: {}
        labels: {}
        ports:
          "*":
            enabled: true
            primary: true
            port: 80
            protocol: HTTP
            targetPort: 80
    route:
      "*":
        enabled: true
        annotations: {}
        labels: {}
        parentRefs:
          - group: gateway.networking.k8s.io
            kind: Gateway
            name: envoy-internal
            namespace: network
            sectionName: https
        hostnames: []
        rules:
          - matches: []
            backendRefs: []
    serviceAccount:
      "*":
        create: true
        name: name
        annotations: {}
        labels: {}
    rbac:
      roles: {}
      bindings:
        "*":
          type: ClusterRoleBinding
          roleRef:
            kind: ClusterRole
            name: name
          subjects: []
    configMaps:
      "*":
        enabled: true
        annotations: {}
        labels: {}
        data: {}
    secrets:
      "*":
        enabled: true
        type: Opaque
        annotations: {}
        labels: {}
        stringData: {}
    persistence:
      "*":
        enabled: true
        type: persistentVolumeClaim
        existingClaim: claim
        storageClass: ceph-block
        accessMode: ReadWriteOnce
        size: 1Gi
        retain: false
        name: name
        medium: Memory
        sizeLimit: 1Gi
        hostPath: /path
        hostPathType: Directory
        server: server
        path: /path
        globalMounts:
          - path: /path
            subPath: subpath
            readOnly: false
        advancedMounts: {}
    serviceMonitor:
      "*":
        enabled: true
        annotations: {}
        labels: {}
        serviceName: service
        endpoints:
          - port: http
            scheme: http
            path: /metrics
            interval: 1m
            scrapeTimeout: 10s
    networkpolicies:
      "*":
        enabled: true
        annotations: {}
        labels: {}
        controller: controller
        podSelector: {}
        policyTypes: []
        rules:
          ingress: []
          egress: []
    rawResources:
      "*":
        enabled: true
        apiVersion: group/v1
        kind: Kind
        annotations: {}
        labels: {}
        spec: {}
