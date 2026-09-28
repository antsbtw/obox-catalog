# obox-catalog

OBox 应用平台的**签名目录仓库**:VPS 上能装的应用,由这里的清单(manifest)与配方(recipe)描述。
App 下载目录包、在手机上验签,再经 SSH 在用户机器上执行配方。后端只指路(`GET /api/v1/obox/catalog`),
**不签名、不执行**。

设计文档(saas-platform 仓 `backend-v3/document/obox/`):`09-应用平台-清单与配方-设计.md`、`10-迁移与迭代策略.md`、
回执 `BACKEND_ANSWERS_APP_PLATFORM_AND_HOSTING_2026-09-28.md`。

## 结构

```
schema/manifest.schema.json   清单 schema v1(CI 逐个校验)
apps/<id>/manifest.json       清单;id 必须等于目录名
apps/<id>/install             可重入:再跑一次 = 修复 / 升级
apps/<id>/uninstall
apps/<id>/status              只读
apps/<id>/action-<id>         每个 actions[] 条目一个
apps/<id>/inspect-<id>        可选:透明度面板的只读查询
lib/obox.sh                   配方公共函数(随包下发,与配方放同一临时目录)
platform.json                 签名的平台配置(兜底 release tag、镜像偏好)
tools/                        validate / build / sign / verify / keygen
keys/*.pub.pem                签名公钥(App 内置同一份)
```

目录里只允许以上几种文件;脚本首行必须是 `#!/bin/bash`,必须可执行、过 `bash -n` 与 shellcheck。

## 配方执行约定(App 执行器实现,对所有配方相同)

| 项 | 约定 |
|---|---|
| 上传 | App 把本次要用的脚本与 `lib/obox.sh` 写到 `/tmp/obox-<随机>/`,权限 700,结束后(无论成败)删除 |
| 身份 | 非 root 时 `sudo -n` |
| 参数 | 非密参数经环境变量 `OBOX_PARAM_<KEY大写>`;**`secret` 类型经 stdin**(环境变量在 `/proc` 可见) |
| 日志 | stdout/stderr 逐行实时显示在 App |
| 结果 | **最后一行** `OBOX_RESULT {json}`;退出码非 0 = 失败 |
| `status` | `{"state":"running|stopped|failed|not_installed","version":…,"ports":[{"port":…,"protocols":[…]}],"outputs":{…}}`。**实际端口以这里为准**,防火墙读它 |
| 持久化 | `/var/lib/obox/apps/<id>/`:非密参数、输出、安装版本。密参由应用自己保管 |
| 操作记录 | App 执行器每次执行追加一行到 `/var/log/obox/audit.log`(配方不用管) |
| 退出保证 | 每个应用是**自己的 systemd 服务**,不依赖 agent;卸 agent 后照常运行 |
| 第三方服务 | 优先 docker compose |
| 存量识别 | `status` 必须能识别旧版 App 装出来的同一应用,报告为已安装 |

⚠️ 参数永远当数据用:引用时加双引号,不要 `eval`、不要拼进命令字符串。这是配方评审的第一条。

## 目录包格式(App 验签依据)

- `catalog-<N>.tar.gz`:确定性打包(同样的输入与序号 → 同样的字节)。包内 `index.json` 含
  `sequence`、`created_at`、`platform`,以及每个应用每个文件的 sha256
- `catalog-<N>.tar.gz.sig`:`{"alg":"ed25519","key_id":"<16 hex>","sig":"<base64>"}`
  - 签名对象 = 包文件**全部字节**,RFC 8032 Ed25519(非预哈希)。iOS:`Curve25519.Signing.PublicKey.isValidSignature(sig, for: bundle)`
  - `key_id` = sha256(32 字节原始公钥) 的前 16 个十六进制字符,用来选内置公钥
- `latest.json`(每版都附,**不签名**):`{"sequence","bundle_url","signature_url"}`,只用来找最新一版

App 的判定顺序:下载包与签名 → 按 `key_id` 选内置公钥验签,不过即丢弃 → 解包读 `index.json` →
**包内 `sequence` 小于已见过的最大值即拒绝**(防回滚)→ 逐文件核对 sha256。

取最新一版(I0 ~ I4 期间 App 直接用 GitHub;I5 起改走后端 `GET /api/v1/obox/catalog`,形状相同):

```
https://github.com/antsbtw/obox-catalog/releases/latest/download/latest.json
```

## 发布与签名

- PR:`validate` 工作流(schema、交叉检查、shellcheck、确定性打包、ubuntu-24.04 虚拟机上跑 `status`)
- 合并到 main:`release` 工作流在受保护环境 **`catalog-signing`** 里打包、签名、用 `keys/` 验签、发布 `catalog-<N>`,N 严格递增
- **能合并 main 并批准 `catalog-signing` 的人,就是签名权限的持有人。** main 分支保护:必须 PR、至少 2 个批准且后端与客户端各一人、禁止 force push
- 签名私钥只在 `catalog-signing` 的 secret 里;第二把离线保管。见 `keys/README.md`

本地演练:

```bash
openssl genpkey -algorithm ed25519 -out /tmp/test.pem
mkdir -p /tmp/k && openssl pkey -in /tmp/test.pem -pubout -out /tmp/k/test.pub.pem
python3 tools/build.py --sequence 1 --out /tmp/dist
tools/sign.sh /tmp/dist/catalog-1.tar.gz /tmp/test.pem
tools/verify.sh /tmp/dist/catalog-1.tar.gz /tmp/k
```

## 加一个应用

1. `apps/<id>/manifest.json` + 三个必需脚本(+ 每个 action 一个脚本)
2. 用到新的参数或输出**类型**、新的原生扩展、或 `min_client` 高于当前 App → 先和客户端对齐,那需要发版
3. 托管机:不允许就写 `"hosted": {"allowed": false}`;会让托管机变相中转的参数放进 `hidden_params`
4. 开 PR,两边各一人评审
