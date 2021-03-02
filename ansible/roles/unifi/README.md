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
                        }
                    }
                }
            }
        }
    }
}
```
