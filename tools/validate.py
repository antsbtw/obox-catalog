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
