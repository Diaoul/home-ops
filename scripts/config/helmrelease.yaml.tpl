---
# yaml-language-server: $schema=https://k8s-schemas.home-operations.com/helm.toolkit.fluxcd.io/helmrelease_v2.json
# Only the keys are read; every value here is a placeholder.
# Fallback for HelmReleases whose chart has no template of its own.
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
    name: chart
    namespace: flux-system
  dependsOn:
    - name: dependency
      namespace: namespace
  install:
    createNamespace: false
    crds: Create
    replace: false
    remediation:
      retries: 3
      remediateLastFailure: false
      ignoreTestFailures: false
    timeout: 5m
  upgrade:
    crds: Skip
    force: false
    cleanupOnFail: true
    remediation:
      strategy: rollback
      retries: 3
      remediateLastFailure: false
      ignoreTestFailures: false
    timeout: 5m
  rollback:
    recreate: false
    force: false
    cleanupOnFail: true
    timeout: 5m
  uninstall:
    deletionPropagation: background
    disableHooks: false
    keepHistory: false
    timeout: 5m
  test:
    enable: false
    timeout: 5m
    ignoreFailures: false
  driftDetection:
    mode: enabled
    ignore: []
  maxHistory: 5
  persistentClient: true
  valuesFrom:
    - kind: ConfigMap
      name: values
      valuesKey: values.yaml
  values: {}
