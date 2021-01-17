# Images
Use Ubuntu 20.04 LTS as base image with [autoinstall][1] to create the the
minimum common image for my k3s nodes.

The rest of the configuration is done by the `os` and `k3s` ansible roles.

See various ways to achieve this for different architectures:
* [arm64](arm64)
* [amd64](amd64)

[1]: https://ubuntu.com/server/docs/install/autoinstall
