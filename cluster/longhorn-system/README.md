# Longhorn Configuration
To add a node in the storage pool, label it with:
```yaml
node.longhorn.io/create-default-disk: "true"
```
With kubectl:
```bash
kubectl label node k8s-node-x node.longhorn.io/create-default-disk="true"
```

## Manual operations (e.g. change permission)
1. Scale down the service in k8s:
   `kubectl scale --replicas=0 deploy/<serviceName>`
2. Go into the Longhorn UI, click on *Volume* tab and find the PV. It should be
   in a *Detached* state
3. On the *Operation* column, click the menu button and select *Attach*
4. Pick a node to attach the PV to, do not select the *Maintenance* checkbox
5. The device will be attached to `/dev/longhorn/<pvName>`
6. SSH into the node the block device is mounted on
7. Create a temporary mountpoint for the block device to mount to:
   `sudo mkdir /mnt/tmp`
8. Mount the block device to the temporary mount point:
   `sudo mount /dev/longhorn/<pvName> /mnt/tmp`
9. Chown the directories to use the UID/GID that the container is operating
   under, e.g.: `sudo chown -R 568:568 /mnt/tmp/`
10. Umount the mountpoint: `sudo umount /mnt/tmp`
11. In Longhorn UI, on the *Operation* column, click the menu button and select
    *Detach*
12. Scale back up the service in kubernetes:
    `kubectl scale --replicas=1 deploy/<serviceName>`
