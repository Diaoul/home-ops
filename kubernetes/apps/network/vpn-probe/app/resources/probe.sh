#!/bin/sh

: "${GATUS_VPN_TOKEN:?}"

get() { curl -4 -fsS -m 10 --retry 2 --retry-all-errors --retry-delay 5 "$@"; }

# The fallback must not sit behind Cloudflare, or one Cloudflare outage fails both.
egress() {
  ip=$(get "$@" https://1.1.1.1/cdn-cgi/trace | sed -n 's/^ip=//p')
  [ -n "$ip" ] || ip=$(get "$@" https://checkip.amazonaws.com)
  echo "$ip"
}

vpn=$(egress)
wan=$(egress --interface eth0)

if [ -z "$vpn" ]; then
  query="success=false&error=no%20egress%20through%20the%20VPN"
elif [ -z "$wan" ]; then
  query="success=false&error=no%20WAN%20egress%20to%20compare%20against"
elif [ "$vpn" = "$wan" ]; then
  query="success=false&error=VPN%20traffic%20leaves%20through%20the%20WAN"
else
  query="success=true"
fi

curl -fsS -m 10 -o /dev/null -X POST -H "Authorization: Bearer $GATUS_VPN_TOKEN" \
  "http://gatus-gatus-sidecar.observability.svc.cluster.local:8080/api/v1/endpoints/services_vpn/external?$query"
exit 0
