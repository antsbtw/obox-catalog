#!/usr/bin/env python3
"""按 App 执行器的方式在真实机器上跑配方,验证 ci/<app>.json 里写的生命周期(C-3)。

执行方式对齐 README「配方执行约定」:
  - 该应用的全部脚本放在临时目录 /tmp/obox-<随机>/ 的根上(配方会互相调用,如 install 末尾 exec ./status),
    lib/obox.sh 放在其 lib/,权限 700,结束后删除;
  - 工作目录即临时目录;非 root 时 sudo -n;
  - 非密参数经环境变量 OBOX_PARAM_<KEY大写>;secret 参数经 stdin(见 secret_stdin);
  - 按清单补默认值、按 show_if 去掉不显示的参数(不显示的不传);
  - 最后一行必须是 OBOX_RESULT {json},退出码非 0 = 失败。

目标机器(--target):
  local           本机(GitHub ubuntu-24.04 runner 是完整 VM,有 systemd)
  incus:<name>    incus 系统容器(Debian 12 等),以 root 执行
  docker:<name>   已在运行的 docker 容器,仅本地调试用(多数没有 systemd)

用法:
  python3 tools/lifecycle.py --target local [app ...]      # 不给 app = ci/ 下全部
ci/<app>.json 格式:
  {"os": ["ubuntu-24.04", "debian-12"],                     # 可选,缺省两者都跑
   "steps": [
     {"run": "install", "params": {"login_method": "web"}, "secrets": {}},
     {"run": "status", "expect": {"state": "stopped", "outputs": ["login_url"]}},
     {"run": "uninstall"},
     {"run": "status", "expect": {"state": "not_installed"}}]}
"""
import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATES = ("running", "stopped", "failed", "not_installed")

# 仓库公开,Actions 日志任何人可见。登录链接谁打开授权、机器就进谁的网络,一律打码后再打印。
REDACT = [re.compile(r"(https://login\.tailscale\.com/a/)[A-Za-z0-9]+")]


def redact(text: str) -> str:
    for pat in REDACT:
        text = pat.sub(r"\1<redacted>", text)
    return text


def secret_stdin(secrets: dict) -> bytes:
    """secret 参数经 stdin 的编码:JSON 对象,写完关闭 stdin(README「配方执行约定」)。"""
    return (json.dumps(secrets) + "\n").encode()


def effective_params(manifest: dict, given: dict) -> tuple:
    """补默认值 → 按 show_if 过滤 → 拆成 (非密环境变量, 密参)。与 App 表单行为一致:不显示的参数不传。"""
    params = manifest.get("params", [])
    values = {p["key"]: p["default"] for p in params if "default" in p}
    values.update(given)

    def shown(p):
        for ref, want in (p.get("show_if") or {}).items():
            wants = want if isinstance(want, list) else [want]
            if values.get(ref) not in wants:
                return False
        return True

    env, secrets = {}, {}
    for p in params:
        k = p["key"]
        if k not in values or not shown(p):
            continue
        v = values[k]
        if p["type"] == "secret":
            secrets[k] = v
        else:
            env["OBOX_PARAM_" + k.upper()] = ("true" if v else "false") if isinstance(v, bool) else str(v)
    unknown = set(given) - {p["key"] for p in params}
    if unknown:
        raise SystemExit(f"ci params not in manifest: {sorted(unknown)}")
    return env, secrets


class Target:
    def __init__(self, spec: str):
        self.kind, _, self.name = spec.partition(":")
        if self.kind not in ("local", "incus", "docker") or (self.kind != "local" and not self.name):
            raise SystemExit(f"bad --target {spec!r}")

    def sh(self, script: str, stdin: bytes = b"", check=True) -> subprocess.CompletedProcess:
        if self.kind == "local":
            argv = ["bash", "-c", script]
        elif self.kind == "incus":
            argv = ["incus", "exec", self.name, "--", "bash", "-c", script]
        else:
            argv = ["docker", "exec", "-i", self.name, "bash", "-c", script]
        return subprocess.run(argv, input=stdin, capture_output=True, check=check)

    def put(self, local_path: str, remote_path: str, mode: str):
        with open(local_path, "rb") as f:
            data = f.read()
        self.sh(f"umask 077; cat > {shlex.quote(remote_path)} && chmod {mode} {shlex.quote(remote_path)}", stdin=data)

    def run_entry(self, tmp: str, entry: str, env: dict, stdin: bytes) -> subprocess.CompletedProcess:
        # App 执行器:工作目录 = 临时目录,非 root 时 sudo -n;环境变量只带 OBOX_PARAM_*
        assigns = " ".join(f"{k}={shlex.quote(v)}" for k, v in sorted(env.items()))
        cmd = (f"cd {shlex.quote(tmp)} && "
               f"if [ \"$(id -u)\" = 0 ]; then env {assigns} ./{entry}; "
               f"else sudo -n env {assigns} ./{entry}; fi")
        return self.sh(cmd, stdin=stdin, check=False)


def run_entry(target: Target, app: str, entry: str, env: dict, secrets: dict) -> dict:
    tmp = f"/tmp/obox-{uuid.uuid4().hex[:12]}"
    target.sh(f"mkdir -m 700 {tmp} {tmp}/lib")
    try:
        app_dir = os.path.join(ROOT, "apps", app)
        for name in sorted(os.listdir(app_dir)):
            if name != "manifest.json" and os.path.isfile(os.path.join(app_dir, name)):
                target.put(os.path.join(app_dir, name), f"{tmp}/{name}", "700")
        target.put(os.path.join(ROOT, "lib", "obox.sh"), f"{tmp}/lib/obox.sh", "600")
        r = target.run_entry(tmp, entry, env, secret_stdin(secrets))
    finally:
        # 配方以 root 身份可能在临时目录里留下 root 的文件,本机非 root 时退回 sudo 删
        target.sh(f"rm -rf {tmp} 2>/dev/null || sudo -n rm -rf {tmp}", check=False)

    out = r.stdout.decode(errors="replace")
    err = r.stderr.decode(errors="replace")
    for line in out.splitlines():
        print(f"    | {redact(line)}")
    for line in err.splitlines():
        print(f"    ! {redact(line)}")
    lines = [ln for ln in out.splitlines() if ln.strip()]
    last = lines[-1] if lines else ""
    if not last.startswith("OBOX_RESULT "):
        raise AssertionError(f"{entry}: last stdout line is not OBOX_RESULT (exit {r.returncode})")
    result = json.loads(last[len("OBOX_RESULT "):])
    if r.returncode != 0:
        raise AssertionError(f"{entry}: exit code {r.returncode}: {result}")
    return result


def check_expect(entry: str, result: dict, expect: dict):
    if entry == "status" and result.get("state") not in STATES:
        raise AssertionError(f"status.state {result.get('state')!r} not in {STATES}")
    if "state" in expect and result.get("state") != expect["state"]:
        raise AssertionError(f"{entry}: state {result.get('state')!r}, want {expect['state']!r}")
    for key in expect.get("outputs", []):
        if not (result.get("outputs") or {}).get(key):
            raise AssertionError(f"{entry}: outputs.{key} missing or empty")


def run_app(target: Target, app: str) -> bool:
    with open(os.path.join(ROOT, "ci", f"{app}.json")) as f:
        spec = json.load(f)
    with open(os.path.join(ROOT, "apps", app, "manifest.json")) as f:
        manifest = json.load(f)
    ok = True
    for i, step in enumerate(spec["steps"], 1):
        entry = step["run"]
        env, secrets = effective_params(manifest, step.get("params", {}))
        secrets.update(step.get("secrets", {}))
        print(f"[{app}] step {i}: {entry} {sorted(env)}")
        try:
            result = run_entry(target, app, entry, env, secrets)
            check_expect(entry, result, step.get("expect", {}))
            print(f"[{app}] step {i}: ok {redact(json.dumps(result, ensure_ascii=False))[:300]}")
        except (AssertionError, json.JSONDecodeError) as e:
            print(f"[{app}] step {i}: FAIL {e}")
            ok = False
            break
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default="local")
    ap.add_argument("--os", help="只跑 ci/<app>.json 的 os 列表里含此值的应用,如 debian-12")
    ap.add_argument("apps", nargs="*")
    a = ap.parse_args()
    target = Target(a.target)
    apps = a.apps or sorted(f[:-5] for f in os.listdir(os.path.join(ROOT, "ci")) if f.endswith(".json"))
    failed = []
    for app in apps:
        if not os.path.isdir(os.path.join(ROOT, "apps", app)):
            raise SystemExit(f"ci/{app}.json: no apps/{app}")
        with open(os.path.join(ROOT, "ci", f"{app}.json")) as f:
            oses = json.load(f).get("os", ["ubuntu-24.04", "debian-12"])
        if a.os and a.os not in oses:
            print(f"[{app}] skipped on {a.os}")
            continue
        if not run_app(target, app):
            failed.append(app)
    print(f"{len(apps)} apps, {len(failed)} failed {failed or ''}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
