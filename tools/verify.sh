#!/bin/bash
# 用 keys/*.pub.pem 验签(与 App 同一逻辑:按 key_id 选公钥)。CI 发布前、以及任何人对照公开仓时用。
#   tools/verify.sh <bundle.tar.gz> [keys_dir]
set -euo pipefail
bundle=$1 keys=${2:-$(dirname "$0")/../keys}
sigjson=$(cat "$bundle.sig")
kid=$(sed -E 's/.*"key_id":"([0-9a-f]+)".*/\1/' <<<"$sigjson")
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
sed -E 's/.*"sig":"([^"]+)".*/\1/' <<<"$sigjson" | base64 -d > "$tmp/sig"
for pub in "$keys"/*.pub.pem; do
  [ -e "$pub" ] || continue
  openssl pkey -pubin -in "$pub" -outform DER 2>/dev/null | tail -c 32 > "$tmp/raw"
  [ "$(sha256sum "$tmp/raw" | cut -c1-16)" = "$kid" ] || continue
  if openssl pkeyutl -verify -pubin -inkey "$pub" -rawin -in "$bundle" -sigfile "$tmp/sig" >/dev/null 2>&1; then
    echo "OK   $(basename "$bundle") signed by $(basename "$pub") (key_id=$kid)"; exit 0
  fi
  echo "FAIL $(basename "$bundle"): bad signature for key_id=$kid"; exit 1
done
echo "FAIL $(basename "$bundle"): no public key with key_id=$kid in $keys"; exit 1
