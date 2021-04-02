<p align="left">
   <img src="https://i.imgur.com/4l9bHvG.png" alt="ansible logo" width="150" align="left" />
   <img src="https://i.imgur.com/EXNTJnA.png" alt="kubernetes home logo" width="150" align="left" />
</p>

### Operations for my home...
_...with Ansible and Kubernetes!_ :sailboat:
<br/><br/><br/><br/>

![lint](https://github.com/Diaoul/home-operations/workflows/lint/badge.svg)
![pre-commit](https://github.com/Diaoul/home-operations/workflows/pre-commit/badge.svg)

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
| Synology NAS            | 1     | 12TB RAID 5 + 2TB RAID 1 | Main storage                                 |
| Raspberry Pi 3          | 2     | 16GB SD                  | Unifi Controller / 3D Printer with OctoPrint |
| Raspberry Pi 4          | 1     | 8GB SD + 120GB SSD USB   | Kubernetes master                            |
| Intel NUC8i5BEH         | 2     | 120GB SSD + 500GB NVMe   | Kubernetes master + storage                  |
| Intel NUC8i3BEH         | 1     | 120GB SSD + 500GB NVMe   | Kubernetes worker + storage                  |

...and a bunch of retired Rasbpberry Pi 1 and 2!

## :handshake:&nbsp; Thanks
I learned a lot from the people that have shared their clusters over at
[awesome-home-kubernetes](https://github.com/k8s-at-home/awesome-home-kubernetes)
and from the [k8s@home discord channel](https://discord.gg/DNCynrJ).
