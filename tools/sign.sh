#!/bin/bash
# 用 Ed25519 私钥给目录包签名,输出 <bundle>.sig(JSON)。
#   tools/sign.sh <bundle.tar.gz> <private.pem>
# 签名对象 = 包文件的全部字节(raw Ed25519,非预哈希);App 用 CryptoKit
# Curve25519.Signing.PublicKey.isValidSignature(sig, for: bundleBytes) 验证。
# key_id = sha256(32 字节原始公钥) 的前 16 个十六进制字符,App 按它选内置公钥。
set -euo pipefail
bundle=$1 key=$2
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
openssl pkeyutl -sign -inkey "$key" -rawin -in "$bundle" -out "$tmp/sig"
openssl pkey -in "$key" -pubout -outform DER 2>/dev/null | tail -c 32 > "$tmp/pub.raw"
kid=$(sha256sum "$tmp/pub.raw" | cut -c1-16)
printf '{"alg":"ed25519","key_id":"%s","sig":"%s"}\n' "$kid" "$(base64 -w0 "$tmp/sig")" > "$bundle.sig"
echo "$bundle.sig (key_id=$kid)"
