#!/bin/bash
set -euo pipefail

url='https://releases.ubuntu.com/20.04/ubuntu-20.04.2-live-server-amd64.iso'
grub_url='http://archive.ubuntu.com/ubuntu/dists/focal/main/uefi/grub2-amd64/current/grubnetx64.efi.signed'
# shellcheck disable=SC2016
server='${pxe_default_server}'
tftp_root='/tftp'
iso=$(basename $url)

echo "Preparing for $iso"

# download the iso
if [ ! -f "$iso" ]; then
    echo "Download ISO..."
    curl -sfLo "$iso" "$url"
fi

# copy cloud-init files
mkdir -p www
echo "Copy iso and cloud-init files..."
cp -f "$iso" "www/$iso"
mkdir -p www/sda
touch www/sda/meta-data
cp -f user-data-sda.yaml www/sda/user-data
mkdir -p www/nvme0n1
touch www/nvme0n1/meta-data
cp -f user-data-nvme0n1.yaml www/nvme0n1/user-data

# copy kernel and initramfs from iso
mkdir -p tftp
if [ ! -f tftp/initrd ] || [ ! -f tftp/vmlinuz ]; then
    echo "Copy kernel and initramfs..."
    mkdir mnt
    sudo mount -o ro "www/$iso" mnt/
    [ -f tftp/vmlinuz ] || cp -p mnt/casper/vmlinuz tftp/
    [ -f tftp/initrd ] || cp -p mnt/casper/initrd tftp/
    sudo umount mnt/
    rmdir mnt
fi

# download grub image
if [ ! -f tftp/pxelinux.0 ]; then
    echo "Download GRUB image..."
    curl -sfLo tftp/pxelinux.0 "$grub_url"
fi

# copy grub configuration
echo "Copy GRUB configuration..."
mkdir -p tftp/grub
sed -e "s|{{server}}|$server|g" \
    -e "s|{{root}}|$tftp_root|g" \
    -e "s|{{iso}}|$iso|g" \
    grub.cfg > tftp/grub/grub.cfg

echo "Done!"
