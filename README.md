# Discord-to-Telegram Monitoring System

一个基于 FastAPI 和 React 的 Discord 消息监听与 Telegram 转发学习项目。它支持多个 Discord 用户 Token 轮换、目标服务器/用户过滤、运行状态面板、日志查看和 Telegram 测试发送。

> 注意：使用 Discord 用户 Token 进行 self-bot 行为违反 Discord 服务条款，可能导致账号被封。本项目仅适合学习和个人测试。

## 核心功能

- 多账号轮换：同一时间只运行一个 Discord Token，异常后自动切换或退避重试。
- Token 生命周期：支持 `standby`、`online`、`offline`、`invalid`、`rate_limited`、`disabled` 等状态。
- 精准监控：按 Discord Guild ID 和 User ID 过滤消息。
- Telegram 转发：支持保存配置并发送测试消息。
- AI 翻译/摘要：支持 OpenAI 兼容接口，可按“原文 / 中文摘要 + 原文 / 仅中文”格式推送。
- 运行状态面板：展示任务线程、活跃 Token、最近转发、错误信息和账号统计。
- 日志保留策略：系统日志和转发去重记录自动清理，仅保留最近 1 小时。
- 工程化基础：提供 Alembic 迁移、后端 API 测试、前端构建脚本和 Docker Compose 部署。

## 技术栈

- 后端：Python 3.10、FastAPI、SQLAlchemy、Alembic、discord.py-self、python-telegram-bot
- 前端：React 18、Vite、TypeScript、Lucide Icons、CSS
- 数据库：默认 SQLite，可通过 `DATABASE_URL` 切换到 MySQL/PostgreSQL
- 部署：Docker、Docker Compose、Nginx

## 服务器安装

先下载项目：

```bash
git clone https://github.com/wuxiansheng8/DCCCC.git
cd DCCCC
```

运行安装向导：

```bash
bash install.sh
```

安装向导会自动询问：

- 网页访问端口，默认 `8888`
- 后端 API 端口，默认 `8000`
- 管理员用户名，默认 `admin`
- 管理员密码，直接回车会自动生成
- `SECRET_KEY` 会自动随机生成

向导结束后会生成 `.env` 并询问是否立即启动服务。

启动后访问：

```text
http://服务器IP:8888
```

## 服务器更新

服务器上需要升级到 GitHub 最新版时执行：

```bash
cd /opt/DCCCC
./scripts/update.sh
```

`scripts/update.sh` 会丢弃项目目录里的本地代码改动，强制同步 GitHub 最新 `main` 分支，并重建 Docker 服务。`.env` 和 `backend/data` 等运行数据不在 Git 跟踪里，会保留。

如果服务器还没安装 Docker：

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo apt install -y docker-compose-plugin
```

## 手动启动

如果你不想使用向导，也可以复制示例配置：

```bash
cp .env.example .env
nano .env
docker compose up -d --build
```

## 使用流程

1. 登录后台。
2. 在“系统设置”里填写 Telegram Bot Token 和 Chat ID，并发送测试消息。
3. 在“DC 账号”里添加 Discord 用户 Token。
4. 在“监控目标”里添加目标 Guild ID 和 User ID。
5. 回到“系统概览”启动监控。

## 本地开发

前端：

```bash
cd frontend
npm install
npm run build
```

后端：

```bash
cd backend
pip install -r requirements.txt
alembic upgrade head
pytest
python main.py
```

## 数据库迁移

迁移配置位于 `backend/alembic`。容器启动时会自动执行：

```bash
alembic upgrade head
```

如果你手动修改模型，建议新增迁移，而不是依赖 `create_all` 修改已有表结构。

## 免责声明

本工具仅用于自动化学习和个人测试。使用 Discord 用户账号 Token 存在封号和合规风险，请谨慎使用。开发者不对任何账号封禁、数据丢失或其他后果负责。
