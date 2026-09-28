# shellcheck shell=bash
# 配方公共函数。App 执行器把它与配方脚本一起上传到同一临时目录;配方用
#   . "$(dirname "$0")/obox.sh"
# 引入。约定见 README「配方执行约定」。

# obox_json_str 把任意字符串编码为 JSON 字符串字面量(含引号)。
obox_json_str() {
  local s=${1-}
  s=${s//\\/\\\\}; s=${s//\"/\\\"}
  s=${s//$'\n'/\\n}; s=${s//$'\r'/\\r}; s=${s//$'\t'/\\t}
  printf '"%s"' "$s"
}

# obox_result 输出结果行(必须是最后一行)。参数是已编码好的 JSON 对象。
obox_result() { printf 'OBOX_RESULT %s\n' "$1"; }

# obox_fail 打印原因并以非 0 退出(App 视为失败)。
obox_fail() { echo "[obox] error: $*" >&2; obox_result "{\"ok\":false,\"error\":$(obox_json_str "$*")}"; exit 1; }

# obox_state_dir 应用的持久化目录:只放非密参数、输出、安装版本。
obox_state_dir() { echo "/var/lib/obox/apps/$1"; }
