#!/usr/bin/env python3
"""lifecycle.py 的参数处理与期望判定。用法: python3 tools/test_lifecycle.py(无第三方依赖)"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lifecycle import check_expect, effective_params, redact  # noqa: E402

MANIFEST = {"params": [
    {"key": "login_method", "type": "select", "default": "web", "options": ["web", "key"]},
    {"key": "auth_key", "type": "secret", "show_if": {"login_method": "key"}},
    {"key": "exit_node", "type": "bool", "default": False},
    {"key": "hostname", "type": "text"},
]}


class EffectiveParamsTest(unittest.TestCase):
    def test_defaults_and_hidden_secret_dropped(self):
        env, secrets = effective_params(MANIFEST, {"auth_key": "tskey-x"})
        self.assertEqual(env, {"OBOX_PARAM_LOGIN_METHOD": "web", "OBOX_PARAM_EXIT_NODE": "false"})
        self.assertEqual(secrets, {}, "auth_key is hidden when login_method=web and must not be passed")

    def test_shown_secret_goes_to_stdin_not_env(self):
        env, secrets = effective_params(MANIFEST, {"login_method": "key", "auth_key": "tskey-x", "hostname": "vps"})
        self.assertEqual(secrets, {"auth_key": "tskey-x"})
        self.assertNotIn("OBOX_PARAM_AUTH_KEY", env)
        self.assertEqual(env["OBOX_PARAM_HOSTNAME"], "vps")

    def test_unknown_param_rejected(self):
        with self.assertRaises(SystemExit):
            effective_params(MANIFEST, {"typo": 1})


class ExpectTest(unittest.TestCase):
    def test_state_and_outputs(self):
        check_expect("status", {"state": "stopped", "outputs": {"login_url": "https://login.tailscale.com/a/x"}},
                     {"state": "stopped", "outputs": ["login_url"]})
        with self.assertRaises(AssertionError):
            check_expect("status", {"state": "running", "outputs": {}}, {"state": "stopped"})
        with self.assertRaises(AssertionError):
            check_expect("status", {"state": "stopped", "outputs": {"login_url": ""}}, {"outputs": ["login_url"]})
        with self.assertRaises(AssertionError):
            check_expect("status", {"state": "weird"}, {})

    def test_no_outputs(self):
        check_expect("status", {"state": "stopped", "outputs": {"login_url": "https://login.tailscale.com/a/x"}},
                     {"outputs": ["login_url"], "no_outputs": ["backend_state"]})
        check_expect("status", {"state": "stopped"}, {"no_outputs": ["backend_state"]})
        with self.assertRaises(AssertionError):
            check_expect("status", {"state": "stopped", "outputs": {"backend_state": "NeedsLogin"}},
                         {"no_outputs": ["backend_state"]})


class RedactTest(unittest.TestCase):
    def test_login_url(self):
        self.assertEqual(redact('"login_url": "https://login.tailscale.com/a/1b2c3d4e5f"'),
                         '"login_url": "https://login.tailscale.com/a/<redacted>"')


if __name__ == "__main__":
    unittest.main()
