# kube-prometheus-stack

## NAS Deployments

### node-exporter

```yaml
services:
  node-exporter:
    image: quay.io/prometheus/node-exporter:latest
    command:
      - "--path.rootfs=/host/root"
      - "--path.procfs=/host/proc"
      - "--path.sysfs=/host/sys"
      - "--path.udev.data=/host/root/run/udev/data"
      - "--no-collector.mdadm"
      - "--collector.filesystem.mount-points-exclude=^/(dev|proc|sys|host|etc|volume1)($$|/)"
    network_mode: host
    pid: host
    restart: always
    volumes:
      - /:/host/root:ro
      - /proc:/host/proc:ro
      - /sys:/host/sys:ro
```

### smartctl-exporter

```yaml
services:
  smartctl-exporter:
    image: quay.io/prometheuscommunity/smartctl-exporter:latest
    ports:
      - "9633:9633"
    privileged: true
    restart: always
    user: root
```

### minio

```yaml
services:
  minio:
    image: quay.io/minio/minio:latest
    command: server /data --console-address ":9010"
    environment:
      MINIO_ROOT_USER: "{{ minio_root_user }}"
      MINIO_ROOT_PASSWORD: "{{ minio_root_password }}"
      MINIO_PROMETHEUS_AUTH_TYPE: public
    ports:
      - "9000:9000"
      - "9010:9010"
    restart: always
    volumes:
      - /volume2/minio:/data
```
