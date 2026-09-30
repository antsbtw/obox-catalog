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
lib/obox.sh                   配方公共函数(随包下发,上传到临时目录的 lib/)
platform.json                 签名的平台配置(兜底 release tag、镜像偏好)
ci/<id>.json                  CI 全流程步骤(install → status → uninstall …),不进签名包
tools/                        validate / build / sign / verify / keygen / lifecycle(+ 单元测试)
keys/*.pub.pem                签名公钥(App 内置同一份)
```

目录里只允许以上几种文件;脚本首行必须是 `#!/bin/bash`,必须可执行、过 `bash -n` 与 shellcheck。

## 配方执行约定(App 执行器实现,对所有配方相同)

| 项 | 约定 |
|---|---|
| 上传 | App 把**该应用的全部脚本**(`apps/<id>/` 下除 `manifest.json` 外的文件)写到临时目录 `/tmp/obox-<随机>/` 的**根**上 —— 配方之间会互相调用(如 `install` 末尾 `exec ./status`);`lib/` 下的文件写到其 `lib/`;权限 700,结束后(无论成败)删除 |
| 路径 | 上传到机器上的路径最多两级(如 `status`、`lib/obox.sh`),每级只含字母数字与 `._-`,不以点开头 |
| 入口 | 入口脚本位于临时目录根上,App 读出 shebang(`#!/bin/bash`)**用解释器执行**(`bash ./install`),**工作目录即临时目录**;公共函数用 `. "$(dirname "$0")/lib/obox.sh"` 引入 |
| 权限 | 临时目录建在 `umask 077` 下,上传的文件都是 **600、没有执行权限**,`/tmp` 还可能挂成 `noexec`。**调用同伴脚本必须经解释器**:写 `bash ./status`,不能写 `./status` 或 `exec ./status`(`validate.py` 检查) |
| 同名 | 应用自己的文件与 `lib/` 下的文件重名时,以应用自己的为准 |
| 身份 | 非 root 时 `sudo -n` |
| 参数 | 非密参数经环境变量 `OBOX_PARAM_<KEY大写>`(bool 为 `true`/`false`);**`secret` 类型经 stdin**(环境变量在 `/proc` 可见):一个 JSON 对象 `{"<key>": "<值>"}`,只含本次显示的密参(没有则 `{}`),**写完必须关闭 stdin(EOF)**,配方读到 EOF 为止 |
| 显示条件 | 参数带 `show_if` 且条件不满足时,该参数不显示、不校验、**不传给配方**(环境变量与 stdin 都没有) |
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

- `catalog-<N>.tar.gz`:确定性打包(同样的输入与序号 → 同样的字节)。包内 `index.json`:
  ```json
  {"schema": 1, "sequence": N, "generated_at": "2026-09-28T00:00:00Z",
   "platform": {…platform.json…},
   "files": {"apps/hello/status": "<sha256>", "lib/obox.sh": "<sha256>", "platform.json": "<sha256>", …}}
  ```
  `files` 覆盖包内除 `index.json` 外的**全部**文件,键为包内路径;不在 `files` 里的文件 App 一律拒绝。
  包内路径是 `apps/<id>/<文件>`、`lib/<文件>`、`platform.json`;上传到机器时去掉 `apps/<id>/` 前缀
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
python3 tools/build.py --sequence 1 --out /tmp/dist   # 可加 --generated-at 固定时间
tools/sign.sh /tmp/dist/catalog-1.tar.gz /tmp/test.pem
tools/verify.sh /tmp/dist/catalog-1.tar.gz /tmp/k
```

## 清单字段补充(2026-09-30)

| 字段 | 位置 | 含义 |
|---|---|---|
| `channel` | 顶层 | `stable`(缺省)/ `beta`。beta 只给测试版 App,正式版 App 不显示;签名、发布与 stable 相同 |
| `show_if` | `params[]` | `{"<其他参数 key>": 值或值列表}`,全部满足才显示。不能引用自己、secret 参数,不能成环;select 的取值必须是其选项,bool 必须是 true/false(`validate.py` 检查) |
| `options` | `params[]`(`select`) | 字符串数组 `["web","key"]`,或带显示名 `[{"value":"web","label":{…}}]`,两种写法不能混用;`default` 必须是选项之一 |

老版本 App 不认识 `show_if` 只会多显示一个框;`options` 两种写法新版 App 都认。

## CI 全流程(C-3)

`ci/<id>.json` 写该应用在真实机器上的生命周期,`tools/lifecycle.py` 按 App 执行器的方式执行并核对:

```json
{"os": ["ubuntu-24.04", "debian-12"],
 "steps": [{"run": "install", "params": {"login_method": "web"}},
           {"run": "status", "expect": {"state": "stopped", "outputs": ["login_url"]}},
           {"run": "uninstall"},
           {"run": "status", "expect": {"state": "not_installed"}}]}
```

- Ubuntu 24.04:GitHub runner 本机(完整 VM,systemd,`sudo -n`);
- Debian 12:runner 上的 incus 系统容器(systemd、透传 `/dev/net/tun`),以 root 执行;
- 本地调试:`python3 tools/lifecycle.py --target docker:<容器名> <id>`(多数容器没有 systemd,只适合不依赖服务的配方)。

需要真实凭据的路径(如 Tailscale 的 Auth Key)不进 CI,联调时手测。

## 加一个应用

1. `apps/<id>/manifest.json` + 三个必需脚本(+ 每个 action 一个脚本);能在 CI 里跑通的,加 `ci/<id>.json`
2. 用到新的参数或输出**类型**、新的原生扩展、或 `min_client` 高于当前 App → 先和客户端对齐,那需要发版
3. 托管机:不允许就写 `"hosted": {"allowed": false}`;会让托管机变相中转的参数放进 `hidden_params`
4. 开 PR,两边各一人评审
