#!/usr/bin/env python3
"""schema 与 validate.py 交叉检查的单元测试。用法: python3 tools/test_validate.py(需要 jsonschema)"""
import copy
import json
import os
import sys
import unittest

from jsonschema import Draft202012Validator

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from validate import check_params, direct_sibling_calls  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(ROOT, "schema", "manifest.schema.json")) as f:
    VALIDATOR = Draft202012Validator(json.load(f))

# 与客户端 2026-09-30 Tailscale 通知描述一致的清单形状
BASE = {
    "schema": 1, "id": "tailscale", "version": "1.0.0", "min_client": "1.4.0", "channel": "beta",
    "name": {"zh-Hans": "Tailscale", "en": "Tailscale"},
    "summary": {"zh-Hans": "把这台机器加入你的 Tailscale 网络"},
    "category": "network",
    "requires": {"os": ["debian>=12", "ubuntu>=22.04"], "arch": ["amd64", "arm64"]},
    "params": [
        {"key": "login_method", "type": "select", "default": "web", "label": {"zh-Hans": "登录方式"},
         "options": [{"value": "web", "label": {"zh-Hans": "网页登录", "en": "Web login"}},
                     {"value": "key", "label": {"zh-Hans": "Auth Key", "en": "Auth Key"}}]},
        {"key": "auth_key", "type": "secret", "required": True, "label": {"zh-Hans": "Auth Key"},
         "show_if": {"login_method": "key"}},
        {"key": "exit_node", "type": "bool", "default": False, "label": {"zh-Hans": "作为出口节点"}},
    ],
    "ports": [{"port": 41641, "protocols": ["udp"], "public": True}],
    "actions": [{"id": "logout", "label": {"zh-Hans": "退出登录"}, "confirm": True, "destructive": True},
                {"id": "restart", "label": {"zh-Hans": "重启"}}],
    "outputs": [{"key": "login_url", "type": "url", "label": {"zh-Hans": "登录链接"}}],
    "hosted": {"allowed": True, "hidden_params": ["exit_node"]},
}


def schema_errors(m):
    return [e.message for e in VALIDATOR.iter_errors(m)]


def cross_errors(m):
    out = []
    check_params(m.get("params", []), out.append)
    return out


class SchemaTest(unittest.TestCase):
    def test_base_manifest_is_valid(self):
        self.assertEqual(schema_errors(BASE), [])
        self.assertEqual(cross_errors(BASE), [])

    def test_options_as_plain_strings(self):
        m = copy.deepcopy(BASE)
        m["params"][0]["options"] = ["web", "key"]
        self.assertEqual(schema_errors(m), [])
        self.assertEqual(cross_errors(m), [])

    def test_options_mixed_forms_rejected(self):
        m = copy.deepcopy(BASE)
        m["params"][0]["options"] = ["web", {"value": "key", "label": {"zh-Hans": "k"}}]
        self.assertNotEqual(schema_errors(m), [])

    def test_channel_values(self):
        m = copy.deepcopy(BASE)
        del m["channel"]
        self.assertEqual(schema_errors(m), [], "channel is optional")
        m["channel"] = "nightly"
        self.assertNotEqual(schema_errors(m), [])

    def test_show_if_value_list_and_bool(self):
        m = copy.deepcopy(BASE)
        m["params"][1]["show_if"] = {"login_method": ["key", "web"], "exit_node": False}
        self.assertEqual(schema_errors(m), [])
        self.assertEqual(cross_errors(m), [])

    def test_show_if_schema_shape(self):
        for bad in ({}, {"Login": "key"}, {"login_method": []}, {"login_method": {"x": 1}}):
            m = copy.deepcopy(BASE)
            m["params"][1]["show_if"] = bad
            self.assertNotEqual(schema_errors(m), [], bad)


class CrossCheckTest(unittest.TestCase):
    def expect(self, mutate, fragment):
        m = copy.deepcopy(BASE)
        mutate(m)
        errs = cross_errors(m)
        self.assertTrue(any(fragment in e for e in errs), f"want {fragment!r} in {errs}")

    def test_unknown_ref(self):
        self.expect(lambda m: m["params"][1].update(show_if={"method": "key"}), "unknown param")

    def test_self_ref(self):
        self.expect(lambda m: m["params"][1].update(show_if={"auth_key": "x"}), "itself")

    def test_value_not_an_option(self):
        self.expect(lambda m: m["params"][1].update(show_if={"login_method": "token"}), "not an option")

    def test_bool_needs_bool(self):
        self.expect(lambda m: m["params"][1].update(show_if={"exit_node": "true"}), "true/false")

    def test_cannot_depend_on_secret(self):
        self.expect(lambda m: m["params"][2].update(show_if={"auth_key": "x"}), "secret")

    def test_cycle(self):
        def mutate(m):
            m["params"][0]["show_if"] = {"exit_node": True}
            m["params"][2]["show_if"] = {"login_method": "web"}
        self.expect(mutate, "cycle")

    def test_default_must_be_option(self):
        self.expect(lambda m: m["params"][0].update(default="sso"), "default")

    def test_duplicate_option_values(self):
        self.expect(lambda m: m["params"][0].update(options=[{"value": "web", "label": {"zh-Hans": "a"}},
                                                               {"value": "web", "label": {"zh-Hans": "b"}}]),
                    "duplicate option")


class SiblingCallTest(unittest.TestCase):
    SIB = {"install", "status", "uninstall", "lib"}

    def test_flags_direct_exec(self):
        self.assertEqual(direct_sibling_calls("x\nexec ./status\n", self.SIB), [2])
        self.assertEqual(direct_sibling_calls("out=$(./status)\n", self.SIB), [1])
        self.assertEqual(direct_sibling_calls("./status || true\n", self.SIB), [1])

    def test_allows_interpreter_and_source(self):
        text = ('. ./lib/obox.sh\nexec bash ./status\nsource ./lib/obox.sh\n'
                'KEY_FILE="$PWD/.authkey"\n# exec ./status in a comment\ncurl -o ./tmpfile x\n')
        self.assertEqual(direct_sibling_calls(text, self.SIB), [])


if __name__ == "__main__":
    unittest.main()
