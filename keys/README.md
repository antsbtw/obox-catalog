# 签名公钥

这里只放**公钥**(`*.pub.pem`)。App 内置同样的公钥,按签名文件里的 `key_id` 选用。

| 文件 | 私钥在哪 | 用途 |
|---|---|---|
| `primary.pub.pem` | GitHub 环境 `catalog-signing` 的 secret `CATALOG_SIGNING_KEY` | 日常发布 |
| `backup.pub.pem` | **离线**,由产品指定的持有人保管(回执 R-11) | 主钥泄露或轮换时启用 |

两把都要在 App 发版前放进来并内置,否则轮换时老 App 不认新钥匙。
生成:在离线机器上 `tools/keygen.sh primary` / `tools/keygen.sh backup`,只提交生成的 `keys/*.pub.pem`。

轮换:把 `backup` 的私钥放进 `catalog-signing` 环境 → 发一版 → 下一次 App 发版时用新的第二把替换已泄露的那把。
