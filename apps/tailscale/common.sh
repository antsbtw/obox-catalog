# shellcheck shell=bash
# Tailscale 配方内部共用的函数（install / action-restart / uninstall）。随应用一起上传，用
#   . ./common.sh
# 引入。依赖 python3（install 会确保装上）。

# 读 tailscale status --json 的一个字段；读不到输出空。
ts_field() {
  tailscale status --json 2>/dev/null | python3 -c "import json,sys
try: s = json.load(sys.stdin)
except Exception: s = {}
print(s.get('$1') or '')"
}
ts_backend_state() { ts_field BackendState; }
ts_auth_url() { ts_field AuthURL; }

# 结束之前留在后台等登录的 tailscale up —— 反复安装 / 重启时不要越积越多。
ts_stop_pending_login() { pkill -f '(^|/)tailscale up( |$)' 2>/dev/null || true; }

# 按非密参数拼 tailscale up 的参数，放进全局数组 TS_UP_ARGS。$1 = 设备名，$2 = 是否出口节点
ts_build_up_args() {
  TS_UP_ARGS=(--reset)
  [ -n "${1:-}" ] && TS_UP_ARGS+=(--hostname="$1")
  [ "${2:-false}" = "true" ] && TS_UP_ARGS+=(--advertise-exit-node)
  return 0
}

# 后台发起网页登录，最多等 30 秒拿到登录链接（或已登录）。参数原样传给 tailscale up。
# tailscale up 会一直等到用户授权；放到后台，授权后它自己结束。
ts_start_web_login() {
  ts_stop_pending_login
  # 日志里有登录链接（谁打开授权，这台机器就进谁的 tailnet），只给 root 读
  install -m 600 /dev/null /var/log/obox-tailscale-up.log
  setsid nohup tailscale up "$@" >/var/log/obox-tailscale-up.log 2>&1 </dev/null &
  for _ in $(seq 1 30); do
    sleep 1
    [ -n "$(ts_auth_url)" ] && return 0
    [ "$(ts_backend_state)" = "Running" ] && return 0
  done
  return 0
}
