---
# yaml-language-server: $schema=https://json.schemastore.org/kustomization
# Only the keys are read; every value here is a placeholder.
apiVersion: kustomize.config.k8s.io/v1alpha1
kind: Component
namespace: namespace
resources: []
patches:
  - target: {}
    path: patch.yaml
configMapGenerator:
  - name: name
    files: []
    literals: []
generatorOptions:
  disableNameSuffixHash: true
  labels: {}
  annotations: {}
