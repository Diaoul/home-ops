# Installation
The [prepare.sh](prepare.sh) script creates the seed image for VM installation.

You will need to have `cloud-localds` installed, usually through the
`cloud-image-utils` package.

Use an [Ubuntu Cloud Image](https://cloud-images.ubuntu.com/) with the
seed.iso mounted to have the installation done automatically.

[user-data.yaml](user-data.yaml) only contains minimal information, the rest
is default and usually doesn't need modifying.
