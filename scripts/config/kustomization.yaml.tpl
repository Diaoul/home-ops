---
# yaml-language-server: $schema=https://json.schemastore.org/kustomization
# Only the keys are read; every value here is a placeholder.
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: namespace
components: []
resources: []
configurations: []
patches:
  - target: {}
    path: patch.yaml
configMapGenerator:
  - name: name
    namespace: namespace
    files: []
    literals: []
    options:
      disableNameSuffixHash: true
      labels: {}
      annotations: {}
secretGenerator:
  - name: name
    namespace: namespace
    files: []
    literals: []
    options:
      disableNameSuffixHash: true
      labels: {}
      annotations: {}
generatorOptions:
  disableNameSuffixHash: true
  labels: {}
  annotations: {}
