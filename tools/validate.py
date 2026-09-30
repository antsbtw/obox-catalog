#!/usr/bin/env python3
"""校验目录仓库:每个清单过 JSON Schema,再做 schema 表达不了的交叉检查。

用法: python3 tools/validate.py            (需要 pip install jsonschema)
退出码非 0 = 有错误,CI 据此拒绝合并。
"""
import json
import os
import re
import subprocess
import sys

from jsonschema import Draft202012Validator

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REQUIRED_SCRIPTS = ("install", "uninstall", "status")
SCRIPT_RE = re.compile(r"^(install|uninstall|status|action-[a-z][a-z0-9-]*|inspect-[a-z][a-z0-9-]*)$")


def direct_sibling_calls(text: str, siblings: set) -> list:
    """上传后的脚本是 600 且 /tmp 可能 noexec:调用同伴脚本必须经解释器(bash ./status),
    source 用 `. ./lib/obox.sh`。返回直接执行同伴脚本(./status、exec ./status)的行号。"""
    bad = []
    for n, line in enumerate(text.splitlines(), 1):
        code = line.split("#", 1)[0] if not line.lstrip().startswith("#!") else ""
        for m in re.finditer(r"\./([A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)?)", code):
            name = m.group(1)
            if name.split("/")[0] not in siblings:
                continue
            before = code[: m.start()].rstrip()
            prev = before.split()[-1] if before.split() else ""
            if prev not in ("bash", ".", "source"):
                bad.append(n)
                break
    return bad


def option_values(param):
    """select 的取值集合:options 是字符串数组或 {value, label} 数组。"""
    return [o if isinstance(o, str) else o.get("value") for o in param.get("options", [])]


def check_params(params, err):
    """schema 表达不了的参数交叉检查:select 取值、default、show_if 的引用与取值、show_if 成环。"""
    by_key = {p.get("key"): p for p in params}
    for p in params:
        key = p.get("key")
        if p.get("type") == "select":
            values = option_values(p)
            if len(values) != len(set(values)):
                err(f"param {key}: duplicate option values")
            if "default" in p and p["default"] not in values:
                err(f"param {key}: default {p['default']!r} is not one of the options")
        for ref, want in (p.get("show_if") or {}).items():
            if ref == key:
                err(f"param {key}: show_if refers to itself")
                continue
            target = by_key.get(ref)
            if target is None:
                err(f"param {key}: show_if refers to unknown param {ref!r}")
                continue
            wants = want if isinstance(want, list) else [want]
            if target.get("type") == "select":
                bad = [w for w in wants if w not in option_values(target)]
                if bad:
                    err(f"param {key}: show_if {ref}={bad!r} is not an option of {ref}")
            elif target.get("type") == "bool":
                if any(not isinstance(w, bool) for w in wants):
                    err(f"param {key}: show_if {ref} must be true/false (bool param)")
            elif target.get("type") == "secret":
                err(f"param {key}: show_if cannot depend on secret param {ref!r}")
    # show_if 依赖不能成环(A 看 B、B 看 A → App 永远算不出显示状态)
    graph = {k: [r for r in (p.get("show_if") or {}) if r in by_key and r != k] for k, p in by_key.items()}
    state = {}  # 1 = 访问中, 2 = 完成

    def visit(k):
        state[k] = 1
        for r in graph[k]:
            if state.get(r) == 1 or (state.get(r) is None and visit(r)):
                return True
        state[k] = 2
        return False

    for k in graph:
        if state.get(k) is None and visit(k):
            err(f"param {k}: show_if dependencies form a cycle")
            break


def main() -> int:
    with open(os.path.join(ROOT, "schema", "manifest.schema.json")) as f:
        validator = Draft202012Validator(json.load(f))
    errors = []
    apps_dir = os.path.join(ROOT, "apps")
    ids = sorted(d for d in os.listdir(apps_dir) if os.path.isdir(os.path.join(apps_dir, d)))
    for app in ids:
        base = os.path.join(apps_dir, app)
        err = lambda m: errors.append(f"apps/{app}: {m}")
        try:
            with open(os.path.join(base, "manifest.json")) as f:
                m = json.load(f)
        except Exception as e:  # noqa: BLE001
            err(f"manifest.json unreadable: {e}")
            continue
        for e in validator.iter_errors(m):
            err(f"schema: {'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}")
        if m.get("id") != app:
            err(f"id {m.get('id')!r} must equal directory name")

        keys = [p["key"] for p in m.get("params", [])]
        if len(keys) != len(set(keys)):
            err("duplicate param keys")
        actions = [a["id"] for a in m.get("actions", [])]
        if len(actions) != len(set(actions)):
            err("duplicate action ids")
        outs = [o["key"] for o in m.get("outputs", [])]
        if len(outs) != len(set(outs)):
            err("duplicate output keys")
        check_params(m.get("params", []), err)
        for hp in m.get("hosted", {}).get("hidden_params", []):
            if hp not in keys:
                err(f"hosted.hidden_params {hp!r} is not a param")
        for dep in m.get("conflicts", []) + m.get("requires", {}).get("components", []):
            if dep not in ids:
                err(f"references unknown app {dep!r}")
        if m.get("icon") and not os.path.isfile(os.path.join(base, m["icon"])):
            err(f"icon {m['icon']} missing")

        files = set(os.listdir(base)) - {"manifest.json", "icons"}
        for s in REQUIRED_SCRIPTS + tuple(f"action-{a}" for a in actions):
            if s not in files:
                err(f"missing script {s}")
        for fname in sorted(files):
            if not SCRIPT_RE.match(fname):
                err(f"unexpected file {fname} (only install/uninstall/status/action-*/inspect-*)")
                continue
            if fname.startswith("action-") and fname[len("action-"):] not in actions:
                err(f"{fname} has no matching actions[] entry")
            path = os.path.join(base, fname)
            with open(path, "rb") as f:
                head = f.readline()
            if head.strip() != b"#!/bin/bash":
                err(f"{fname}: first line must be #!/bin/bash")
            if not os.access(path, os.X_OK):
                err(f"{fname}: not executable")
            r = subprocess.run(["bash", "-n", path], capture_output=True, text=True)
            if r.returncode != 0:
                err(f"{fname}: bash -n: {r.stderr.strip()}")
            with open(path, encoding="utf-8", errors="replace") as f:
                lines = direct_sibling_calls(f.read(), files | {"lib"})
            if lines:
                err(f"{fname}: line {lines}: 同伴脚本须经解释器调用(bash ./x),上传后无执行权限且 /tmp 可能 noexec")

    with open(os.path.join(ROOT, "platform.json")) as f:
        p = json.load(f)
    if p.get("schema") != 1 or not re.match(r"^v[0-9]+\.[0-9]+\.[0-9]+$", p.get("obox_release_fallback", "")):
        errors.append("platform.json: schema must be 1 and obox_release_fallback must be vX.Y.Z")

    for e in errors:
        print("✗", e)
    print(f"{len(ids)} apps, {len(errors)} errors")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
