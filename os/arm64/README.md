## :construction: Installation

### Boot from USB (optional)
To boot from USB:
1. Install Rapberry Pi OS Lite on the SD card
2. Run `apt update` and `apt upgrade` to ensure the latest bootloader is
   installed
3. Run `raspi-config` and change the boot order to choose USB first
4. Plug the USB drive previously flashed with an image (like an SD card)

### Cloud-init
On Ununtu images, cloud-init will run on the first boot. Before that,
copy [user-data.yaml](user-data.yaml) to `/boot/firmware/user-data`.

It is possible to force another run of cloud-init with
```bash
sudo cloud-init clean --logs --reboot
```

[user-data.yaml](user-data.yaml) only contains minimal information, the rest
is default and usually doesn't need modifying.
