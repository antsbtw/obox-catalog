#!/bin/bash
# 生成一对 Ed25519 签名钥匙。★在离线或受信任的机器上跑,私钥永不进仓库、永不放后端服务器。
#   tools/keygen.sh <name>   → <name>.pem(私钥,自己保管) + keys/<name>.pub.pem(公钥,提交进仓库并内置进 App)
set -euo pipefail
name=$1; root=$(cd "$(dirname "$0")/.." && pwd)
umask 077
openssl genpkey -algorithm ed25519 -out "$name.pem"
openssl pkey -in "$name.pem" -pubout -out "$root/keys/$name.pub.pem"
openssl pkey -in "$name.pem" -pubout -outform DER | tail -c 32 > "$name.pub.raw"
echo "private: $name.pem   public: keys/$name.pub.pem   key_id: $(sha256sum "$name.pub.raw" | cut -c1-16)"
rm -f "$name.pub.raw"
