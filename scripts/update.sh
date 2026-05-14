#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

branch="${1:-main}"
remote="${2:-origin}"

echo "正在强制同步 $remote/$branch ..."
git fetch "$remote" "$branch"
git reset --hard "$remote/$branch"

if docker compose version >/dev/null 2>&1; then
  compose_cmd="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  compose_cmd="docker-compose"
else
  echo "错误：未检测到 Docker Compose。" >&2
  exit 1
fi

echo "正在重建并启动服务..."
$compose_cmd up -d --build

echo "当前版本：$(git rev-parse --short HEAD)"
echo "更新完成。"
