#!/bin/bash

set -e

echo "============================================"
echo "   Discord-to-Telegram Monitor 安装向导"
echo "============================================"
echo

prompt_default() {
  local label="$1"
  local default_value="$2"
  local value
  read -p "$label [$default_value]: " value
  echo "${value:-$default_value}"
}

prompt_password() {
  local value
  local generated
  generated=$(tr -dc 'a-zA-Z0-9' </dev/urandom | fold -w 14 | head -n 1)
  read -s -p "请输入管理员密码 [直接回车自动生成]: " value
  echo >&2
  echo "${value:-$generated}"
}

validate_port() {
  local name="$1"
  local value="$2"
  if ! [[ "$value" =~ ^[0-9]+$ ]] || [ "$value" -lt 1 ] || [ "$value" -gt 65535 ]; then
    echo "错误：$name 必须是 1-65535 之间的数字。" >&2
    exit 1
  fi
}

if ! [ -x "$(command -v docker)" ]; then
  echo "错误：未检测到 Docker，请先安装 Docker。" >&2
  echo "Ubuntu 可执行：curl -fsSL https://get.docker.com | sudo sh" >&2
  exit 1
fi

if docker compose version >/dev/null 2>&1; then
  compose_cmd="docker compose"
elif [ -x "$(command -v docker-compose)" ]; then
  compose_cmd="docker-compose"
else
  echo "错误：未检测到 Docker Compose，请先安装 docker-compose-plugin。" >&2
  echo "Ubuntu 可执行：sudo apt install -y docker-compose-plugin" >&2
  exit 1
fi

frontend_port=$(prompt_default "请输入网页访问端口" "8888")
backend_port=$(prompt_default "请输入后端 API 端口" "8000")
admin_username=$(prompt_default "请输入管理员用户名" "admin")
admin_password=$(prompt_password)
secret_key=$(tr -dc 'a-zA-Z0-9' </dev/urandom | fold -w 48 | head -n 1)

validate_port "网页访问端口" "$frontend_port"
validate_port "后端 API 端口" "$backend_port"

if [ -f ".env" ]; then
  backup_file=".env.backup.$(date +%Y%m%d%H%M%S)"
  cp .env "$backup_file"
  echo "检测到已有 .env，已备份为 $backup_file"
fi

cat > .env <<EOF
FRONTEND_PORT=$frontend_port
BACKEND_PORT=$backend_port
ADMIN_USERNAME=$admin_username
ADMIN_PASSWORD=$admin_password
SECRET_KEY=$secret_key
EOF

echo
echo "--------------------------------------------"
echo "配置已生成："
echo "网页端口：$frontend_port"
echo "后端端口：$backend_port"
echo "管理员账号：$admin_username"
echo "管理员密码：$admin_password"
echo "--------------------------------------------"
echo

read -p "是否现在构建并启动服务？[Y/n]: " should_start
should_start=${should_start:-Y}

if [[ "$should_start" =~ ^[Yy]$ ]]; then
  echo "正在启动容器，请稍候..."
  $compose_cmd up -d --build
  echo
  echo "============================================"
  echo "   安装完成"
  echo "   请访问：http://服务器IP:$frontend_port"
  echo "============================================"
else
  echo "已生成 .env。稍后可执行：$compose_cmd up -d --build"
fi
