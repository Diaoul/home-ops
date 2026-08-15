"""Manifest bodies shared by the test modules."""

KS = """\
---
# yaml-language-server: $schema=https://example.invalid/kustomization.json
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: app
spec:
  targetNamespace: default
  prune: true
  path: ./kubernetes/apps/default/app
  wait: true
  sourceRef:
    name: home-ops
    kind: GitRepository
  interval: 10m
"""

SECRET = """\
---
apiVersion: v1
kind: Secret
metadata:
  name: app
stringData:
  KEY: value
"""
