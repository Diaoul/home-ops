## :construction: Installation
The [prepare.sh](prepare.sh) script creates the necessary files to boot Ubuntu
from the network using PXE.

It will download the ubuntu iso and create two directories for PXE:
* `tftp` that contains files to copy to your tftp server
* `www` with files to put on your webserver

Both are served by the same host and the `www` part is under `/tftp` of my
webserver. See the begining of the script to adjust that.

The DHCP server is configured to point to `pxelinux.0` on the TFTP server.

[user-data.yaml](user-data.yaml) only contains minimal information, the rest
is default and usually doesn't need modifying.

:warning: **/dev/sda** (default) or **/dev/nvme0n1** will be wiped automatically
depending on the choice made in GRUB!
