#!/bin/bash
set -euo pipefail

# seed.iso creation
echo "Create seed.iso"
cloud-localds seed.iso user-data.yaml

echo "Done!"
