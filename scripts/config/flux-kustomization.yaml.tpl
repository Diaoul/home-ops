---
# yaml-language-server: $schema=https://k8s-schemas.home-operations.com/kustomize.toolkit.fluxcd.io/kustomization_v1.json
# Only the keys are read; every value here is a placeholder.
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: app
  namespace: flux-system
  labels: {}
  annotations: {}
spec:
  sourceRef:
    kind: GitRepository
    name: home-ops
    namespace: flux-system
  path: ./kubernetes/apps
  interval: 10m
  timeout: 5m
  retryInterval: 1m
  suspend: false
  dependsOn:
    - name: dependency
      namespace: namespace
  targetNamespace: default
  commonMetadata:
    labels: {}
    annotations: {}
  components: []
  patches:
    - target:
        group: group
        version: version
        kind: Kind
        name: name
        namespace: namespace
        labelSelector: selector
        annotationSelector: selector
      patch: ""
  decryption:
    provider: sops
    secretRef:
      name: sops-age
  postBuild:
    substituteFrom:
      - kind: Secret
        name: cluster-secrets
    substitute: {}
  prune: true
  deletionPolicy: WaitForTermination
  wait: true
  force: false
  healthChecks:
    - apiVersion: v1
      kind: Kind
      name: name
      namespace: namespace
  healthCheckExprs:
    - apiVersion: group/v1
      kind: Kind
      current: expr
      inProgress: expr
      failed: expr
