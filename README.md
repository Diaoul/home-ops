<p align="left">
   <img src="https://i.imgur.com/4l9bHvG.png" alt="ansible logo" width="150" align="left" />
   <img src="https://i.imgur.com/EXNTJnA.png" alt="kubernetes home logo" width="150" align="left" />
</p>

### Operations for my home...
_...with Ansible and Kubernetes!_ ⛵
<br/><br/><br/><br/>
![lint](https://img.shields.io/github/actions/workflow/status/Diaoul/home-ops/lint.yml?label=lint&style=for-the-badge)
![pre-commit](https://img.shields.io/github/actions/workflow/status/Diaoul/home-ops/pre-commit.yml?label=pre-commit&style=for-the-badge)

## 📕 Overview
This repository contains everything I use to setup and run the devices in my home. It is based off [cluster-template](https://github.com/onedr0p/cluster-template).

## ⚙️  Hardware
I run everything bare metal.

| Device                  | Count | Storage                  | Purpose                                      |
|-------------------------|-------|--------------------------|----------------------------------------------|
| Protectli FW4B clone    | 1     | 120GB                    | Opnsense router                              |
| Synology NAS            | 1     | 12TB RAID 5 + 2TB RAID 1 | Main storage                                 |
| Raspberry Pi 3          | 2     | 16GB SD                  | Unifi Controller / 3D Printer with OctoPrint |
| Intel NUC8i5BEH         | 3     | 120GB SSD + 500GB NVMe   | Kubernetes control planes + storage                 |
| Intel NUC8i3BEH         | 2     | 120GB SSD                | Kubernetes workers                           |

### Intel NUC

#### BIOS
Intel NUC bios can now be found on [Asus support](https://www.asus.com/supportonly/nuc8i5beh/helpdesk_bios/).

Configuration on top of Defaults (F9):

1. Devices > Onboard Devices > Onboard Device Configuration
  1. Uncheck `WLAN`
  2. Uncheck `Bluetooth`
2. Cooling > CPU Fan Header
   1. Uncheck `Fan off capability`
3. Power > Secondary Power Settings
   1. Set `After Power Failure` to `Last State`
4. Boot > Boot Configuration > Boot Display Config
   1. Check `Display F12 for Network Boot`

In addition, to install Talos Linex with secure boot, we need to allow enrolling other keys.
Enrolling new keys is done by booting the ISO and selecting the appropriate option.

1. Boot > Secure Boot > Secure Boot Config
   1. Check `Clear Secure Boot Data`

There is a [boot menu](https://www.intel.com/content/www/us/en/support/articles/000090607/intel-nuc.html) that can be helpful in case of boot failures:

> Press and hold down the power button for three seconds, then release it before the 4 second shutdown override. The Power Button Menu displays. (Options on the menu can vary, depending on the Intel NUC model.) Press F7 to start the BIOS update.

#### Hardware
The fans on the Intel NUC are known to wear off. In case of overheating this is likely the issue. Amazon and Youtube are your best friends.


The CMOS battery can die and need replacing. Symptoms are the NUC not powering on at all.

### Router
In addition to the regular things like a firewall, my router runs other useful
stuff.

#### HAProxy
I have Talos configured with a Virtual IP to provide HA over the control nodes' API server but I also use HAProxy as loadbalancer.

First, create a Virtual IP to listen on:

1. Interfaces > Virtual IPs > Settings > Add
   1. `Mode` = `IP Alias`
   2. `Interface` = `SERVER` (my VLAN for k8s nodes)
   3. `Network / Address` = `10.0.3.2/32`
   4. `Description` = `k8s-apiserver`

Then, create the HAProxy configuration:

1. Services > HAProxy | Real Servers (for each **master node**)
    1. `Enabled` = `true`
    2. `Name or Prefix` = `k8s-node-x-apiserver`
    3. `FQDN or IP` = `k8s-node-x`
    4. `Port` = `6443`
    5. `Verify SSL Certificate` = `false`
2. Services > HAProxy | Rules & Checks > Health Monitors
    1. `Name` = `k8s-apiserver`
    2. `SSL preferences` = `Force SSL for health checks`
    3. `Port to check` = `6443`
    4. `HTTP method` = `GET`
    5. `Request URI` = `/healthz`
    6. `HTTP version` = `HTTP/1.1`
3. Services > HAProxy | Virtual Services > Backend Pools
    1. `Enabled` = `true`
    2. `Name` = `k8s-apiserver`
    3. `Mode` = `TCP (Layer 4)`
    4. `Servers` = `k8s-node-x-apiserver` (Add one for each real server you created)
    5. `Enable Health Checking` = `true`
    6. `Health Monitor` = `k8s-apiserver`
4. Services > HAProxy | Virtual Services > Public Services
    1. `Enabled` = `true`
    2. `Name` = `k8s-apiserver`
    3. `Listen Addresses` = `10.0.3.2:6443` (the Virtual IP created above, alternatively, the router IP)
    4. `Type` = `TCP`
    5. `Default Backend Pool` = `k8s-apiserver`
5. Services > HAProxy | Settings > Service
    1. `Enable HAProxy` = `true`

Note that Health Monitors require `anonymous-auth` to be enabled on Talos, otherwise we need to rely on TCP health checks instead.

#### BGP
Cilium is configured with BGP to advertise load balancer IPs directly over BGP. Coupled with ECMP, this allows to spread workload in my cluster.

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
## 🤝 Thanks
I learned a lot from the people that have shared their clusters over at
[kubesearch](https://kubesearch.dev/) and from the [Home Operations discord channel](https://discord.gg/DNCynrJ).

Want to get started? I recommend that you take a look at the
[cluster-template](https://github.com/onedr0p/cluster-template) repository!
