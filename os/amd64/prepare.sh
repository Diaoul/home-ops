#!/bin/bash
set -euo pipefail

url=https://releases.ubuntu.com/20.04/ubuntu-20.04.1-live-server-amd64.iso
iso=$(basename $url)
echo "Preparing for $iso"

# download the iso
mkdir -p www
if [ ! -f www/$iso ]; then
    echo "Download ISO..."
    curl -sfLO --output-dir www/ \
        $url
fi

# copy kernel and initramfs from iso
mkdir -p tftp
if [ ! -f tftp/initrd ] || [ ! -f tftp/vmlinuz ]; then
    echo "Copy kernel and initramfs..."
    mkdir mnt
    sudo mount -o ro www/$iso mnt/
    [ -f tftp/vmlinuz ] || cp -p mnt/casper/vmlinuz tftp/
    [ -f tftp/initrd ] || cp -p mnt/casper/initrd tftp/
    sudo umount mnt/
    rmdir mnt
fi

# download grub image
if [ ! -f tftp/pxelinux.0 ]; then
    echo "Download GRUB image..."
    curl -sfLo tftp/pxelinux.0 \
        http://archive.ubuntu.com/ubuntu/dists/focal/main/uefi/grub2-amd64/current/grubnetx64.efi.signed
fi

# copy grub configuration
echo "Copy GRUB configuration..."
mkdir -p tftp/grub
cp -f grub.cfg tftp/grub/

# copy cloud-init files
echo "Copy cloud-init files..."
cp -f meta-data.yaml www/meta-data
cp -f user-data.yaml www/user-data

echo "Done!"
