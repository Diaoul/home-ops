## :building_construction: Playbooks

### Bootstrap
Setup ssh on a machine (not needed for kubernetes: part of cloud-init)
```bash
ansible-playbook playbooks/bootstrap.yml
```

### OS Preparation
With Kubernetes requirements
```bash
ansible-playbook playbooks/cluster/os.yml
```

### K3S Installation
Using [xanmanning.k3s](https://galaxy.ansible.com/xanmanning/k3s) role
```bash
ansible-playbook playbooks/cluster/k3s.yml
```

### CNI
Using [Calico](https://www.projectcalico.org/). If using BGP, make sure to
configure your router accordingly.
```bash
ansible-playbook playbooks/cluster/calico.yml
```
*Note: This is later managed in-cluster.*

## :fire: Uninstall Playbooks
Because sometimes it's the only thing left to do...

Most of the playbooks have an `uninstall` variant that will attempt to
remove what has been installed, e.g.
```bash
ansible-playbook playbooks/cluster/calico-uninstall.yml
```

## :radioactive: Nuke Playbooks
:warning: **Unrecoverable data loss!**
```bash
ansible-playbook playbooks/cluster/rook-ceph-nuke.yml
```
