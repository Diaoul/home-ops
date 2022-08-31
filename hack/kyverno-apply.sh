#!/bin/bash
# this script applies kyverno policies on a live cluster

workdir=$(mktemp -d)
echo "Created workdir $workdir"
for clusterpolicy in $(kubectl get clusterpolicies -A -o name)
do
    policy_workdir=$workdir/${clusterpolicy##*/}
    mkdir $policy_workdir
    kubectl get $clusterpolicy -o yaml > $policy_workdir/clusterpolicy.yaml
    kyverno apply $policy_workdir/clusterpolicy.yaml --cluster --output $policy_workdir/mutated
    kubectl apply -f $policy_workdir/mutated
done
