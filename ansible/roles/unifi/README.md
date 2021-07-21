## Configuration blocks

### Login
Allow users and set public keys for authentication.

```json
"system": {
    "login": {
        "user": {
            "admin": {
                "authentication": {
                    "public-keys": {
                        "earth@milkyway.laniakea": {
                            "key": "AAAAC3NzaC1lZDI1NTE5AAAAIPveFNeWn+aFO3WyMfA+bX9D6iVurO5VfbqbzjO0G0J3",
                            "type": "ssh-ed25519"
                        },
                        "mars@milkyway.laniakea": {
                            "key": "AAAAC3NzaC1lZDI1NTE5AAAAIPCtJ+9LDLWTbwuTHAqC+06OsBT6Lol9avxS4rxy7+yh",
                            "type": "ssh-ed25519"
                        },
                        "openpgp:0x66FDC5CE": {
                            "key": "AAAAC3NzaC1lZDI1NTE5AAAAIE6mQ4yBpDESYhJrIv/G2daw5I2X0cwh0Hj9K1YxCp7n",
                            "type": "ssh-ed25519"
                        }
                    }
                }
            }
        }
    }
}
```

### Dynamic DNS
Use Unifi's ability to update a dynamic DNS, e.g. CloudFlare:

```json
"service": {
    "dns": {
        "dynamic": {
            "interface": {
                "eth0": {
                    "service": {
                        "custom-cloudflare": {
                            "host-name": [
                                "{{ unifi_domain }}"
                            ],
                            "login": "{{ unifi_email }}",
                            "options": [
                                "zone={{ unifi_domain }}"
                            ],
                            "password": "{{ unifi_cloudflare_global_api_key }}",
                            "protocol": "cloudflare",
                            "server": "api.cloudflare.com/client/v4"
                        }
                    }
                }
            }
        },
    }
}
```
