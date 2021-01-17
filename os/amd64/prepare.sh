#!/bin/bash
set -euo pipefail

# create output directories
mkdir -p tftp
mkdir -p www

# download the iso
url=https://releases.ubuntu.com/20.04/ubuntu-20.04.1-live-server-amd64.iso
iso=$(basename $url)
 curl -sfLO --output-dir www/ \
    $url

# copy kernel and initramfs from iso
mkdir mnt
sudo mount -o ro www/$iso mnt/
cp -p mnt/casper/{vmlinuz,initrd} tftp/
sudo umount mnt/
rmdir mnt

# download grub image
 curl -sfLo tftp/pxelinux.0 \
    http://archive.ubuntu.com/ubuntu/dists/focal/main/uefi/grub2-amd64/current/grubnetx64.efi.signed

# copy grub configuration
mkdir -p tftp/grub
cp grub.cfg tftp/grub/

# copy cloud-init files
cp meta-data.yaml www/meta-data
cp user-data.yaml www/user-data

