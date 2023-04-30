<p align="left">
   <img src="https://i.imgur.com/4l9bHvG.png" alt="ansible logo" width="150" align="left" />
   <img src="https://i.imgur.com/EXNTJnA.png" alt="kubernetes home logo" width="150" align="left" />
</p>

### Operations for my home...
_...with Ansible and Kubernetes!_ :sailboat:
<br/><br/><br/><br/>
![lint](https://img.shields.io/github/actions/workflow/status/Diaoul/home-ops/lint.yml?style=for-the-badge)
![pre-commit](https://img.shields.io/github/actions/workflow/status/Diaoul/home-ops/pre-commit.yml?style=for-the-badge)

## :closed_book: Overview
This repository contains everything I use to setup and run the devices in my home. For more
details, see the README of the following directories
* [os](os/) automated installation with PXE or USB for AMD64 and ARM64
* [ansible](ansible/) roles for additional configuration and application installation
* [cluster](cluster/) to manage my Kubernetes cluster with [Flux](https://fluxcd.io/)
   and maintained with the the help of
   [:robot: Renovate](https://github.com/renovatebot/renovate)
* [hack](hack/) is a collection of scripts to ease the maintenance of all this!

## :gear: Hardware
I try to run everything bare metal to get the most out of each device

| Device                  | Count | Storage                  | Purpose                                      |
|-------------------------|-------|--------------------------|----------------------------------------------|
| Protectli FW4B clone    | 1     | 120GB                    | Opnsense router                              |
| Synology NAS            | 1     | 12TB RAID 5 + 2TB RAID 1 | Main storage                                 |
| Raspberry Pi 3          | 2     | 16GB SD                  | Unifi Controller / 3D Printer with OctoPrint |
| Intel NUC8i5BEH         | 3     | 120GB SSD + 500GB NVMe   | Kubernetes masters + storage                 |
| Intel NUC8i3BEH         | 2     | 120GB SSD                | Kubernetes workers                           |

### Router
In addition to the regular things like a firewall, my router runs other useful
stuff.

#### BGP
The Calico CNI is configured with BGP to advertise load balancer IPs directly
over BGP. Coupled with ECMP, this allows to spread workload in my cluster.

1. Routing > BPG | General
    1. `enable` = `true`
    2. `BGP AS Number` = `64512`
    3. `Network` = `10.0.3.0/24` (Subnet of Kubernetes nodes)
    4. Save
2. Routing > BGP | Neighbors
    - Add a neighbor for each Kubernetes node
      1. `Enabled` = `true`
      2. `Peer-IP` = `10.0.3.x` (Kubernetes node IP)
      3. `Remote AS` = `64512`
      4. `Update-Source Interface` = `SERVER` (VLAN of Kubernetes nodes)
      5. Save
      6. Continue adding neighbors until all your nodes are present
3. Routing > General
    1. `Enable` = `true`
    2. Save
4. System > Settings > Tunables
    1. Add `net.route.multipath` and set the value to `1`
    2. Save
5. Reboot
6. Verify
    1. Routing > Diagnostics > BGP | Summary

### SMTP Relay
To be able to send emails from my local devices easily without authentication,
I run the Postfix plugin with the following configuration:

1. System > Services > Postfix > General
    1. `Enable` = `true`
    2. `Trusted Networks` += `10.0.0.0/8`
    3. `TLS Wrapper Mode` = `true`
    4. `SMTP Client Security` = `encrypt`
    5. `Smart Host` = `[smtp.purelymail.com]:465`
    6. `Enable SMTP Authentication` = `true`
    7. `Authentication Username` = `admin@<email-domain>`
    8. `Authentication Password` = `<app-password>`
    9. `Permit SASL Authenticated` = `false`
    10. Save
2. System > Services > Postfix > Domains
    - Add new domain
      1. `Domainname` = `<email-domain>`
      2. `Destination` = `[smtp.purelymail.com]:465`
      3. Save
    - Apply
3. System > Services > Postfix > Senders
    - Add new sender
      1. `Enabled` = `true`
      2. `Sender Address` = `admin@<email-domain>`
      3. Save
    - Apply
4. Verify
    ```sh
    swaks --server opnsense.milkyway --port 25 --to <email-address> --from <email-address>
    ```

## :handshake:&nbsp; Thanks
I learned a lot from the people that have shared their clusters over at
[awesome-home-kubernetes](https://github.com/k8s-at-home/awesome-home-kubernetes)
and from the [k8s@home discord channel](https://discord.gg/DNCynrJ).

Want to get started? I recommend that you take a look at the
[template-cluster-k3s](https://github.com/k8s-at-home/template-cluster-k3s/) repository!
