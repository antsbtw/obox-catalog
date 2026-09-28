#!/usr/bin/env python3
"""打包目录:catalog-<seq>.tar.gz(字节确定:同样的输入 + 序号 + 时间 → 同样的字节)。

包内 index.json 带序号与每个文件的 sha256。序号在被签名的内容里 —— App 以验签后包内的
序号判断回滚,不信目录接口返回的 sequence(回执 R-6 ③)。

用法: python3 tools/build.py --sequence 42 --out dist [--created-at 2026-09-28T00:00:00Z]
"""
import argparse
import gzip
import hashlib
import io
import json
import os
import tarfile
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def collect():
    """(包内路径, 字节, 是否可执行)。lib/obox.sh 放进每个应用目录旁的 lib/,App 上传时一并带上。"""
    files = []
    for rel in ("platform.json", "lib/obox.sh"):
        with open(os.path.join(ROOT, rel), "rb") as f:
            files.append((rel, f.read(), rel.endswith(".sh")))
    apps = os.path.join(ROOT, "apps")
    for app in sorted(os.listdir(apps)):
        for dirpath, _, names in sorted(os.walk(os.path.join(apps, app))):
            for n in sorted(names):
                full = os.path.join(dirpath, n)
                rel = os.path.relpath(full, ROOT)
                with open(full, "rb") as f:
                    files.append((rel, f.read(), os.access(full, os.X_OK)))
    return sorted(files)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sequence", type=int, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--created-at", default=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    a = ap.parse_args()
    if a.sequence < 1:
        raise SystemExit("sequence must be >= 1")

    files = collect()
    apps = {}
    for rel, data, _ in files:
        if rel.startswith("apps/"):
            app = rel.split("/")[1]
            apps.setdefault(app, {})[rel[len(f"apps/{app}/"):]] = sha256(data)
    versions = {}
    for app in apps:
        with open(os.path.join(ROOT, "apps", app, "manifest.json")) as f:
            versions[app] = json.load(f)["version"]
    with open(os.path.join(ROOT, "platform.json")) as f:
        platform = json.load(f)
    index = {
        "schema": 1,
        "sequence": a.sequence,
        "created_at": a.created_at,
        "platform": platform,
        "lib": {"obox.sh": sha256(dict((r, d) for r, d, _ in files)["lib/obox.sh"])},
        "apps": [{"id": app, "version": versions[app], "files": apps[app]} for app in sorted(apps)],
    }
    index_bytes = (json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for rel, data, exe in [("index.json", index_bytes, False)] + files:
            ti = tarfile.TarInfo(rel)
            ti.size, ti.mtime, ti.mode = len(data), 0, 0o755 if exe else 0o644
            ti.uid = ti.gid = 0
            ti.uname = ti.gname = ""
            tar.addfile(ti, io.BytesIO(data))
    os.makedirs(a.out, exist_ok=True)
    out = os.path.join(a.out, f"catalog-{a.sequence}.tar.gz")
    with open(out, "wb") as f, gzip.GzipFile(fileobj=f, mode="wb", mtime=0, filename="") as gz:
        gz.write(buf.getvalue())
    print(out)


if __name__ == "__main__":
    main()
