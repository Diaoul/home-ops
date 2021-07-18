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
