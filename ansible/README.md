## :building_construction: Playbooks

### OS Preparation
With Kubernetes requirements
```bash
ansible-playbook ansible/playbooks/cluster/os.yml
```

### K3S Installation
Using [xanmanning.k3s](https://galaxy.ansible.com/xanmanning/k3s) role
to install version pinned in [k3s_release_version](https://github.com/Diaoul/home-operations/blob/main/ansible/inventory/group_vars/all/k3s.yml#L5).
```bash
ansible-playbook ansible/playbooks/cluster/k3s.yml
```

### CNI
[Calico](https://www.projectcalico.org/) or [Cilium](https://cilium.io/)
available. If using BGP, make sure to configure your router accordingly.
```bash
ansible-playbook ansible/playbooks/cluster/calico.yml
```

### Storage
[Longhorn](https://longhorn.io/) or [Rook (ceph)](https://rook.io/)
available. This role will prepare the disks to be used with the CSI.
Be careful!
```bash
ansible-playbook ansible/playbooks/cluster/longhorn.yml
```

## :fire: Uninstall Playbooks
Because sometimes it's the only thing left to do...

Most of the playbooks have an `uninstall` variant that will attempt to
remove what has been installed, e.g.
```bash
ansible-playbook ansible/playbooks/cluster/calico-uninstall.yml
```

## :radioactive: Nuke Playbooks
:warning: **Unrecoverable data loss!**
```bash
ansible-playbook ansible/playbooks/cluster/rook-ceph-nuke.yml
```
