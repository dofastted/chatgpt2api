# read-this-first

- 这是一个把图片生成代理和账号池管理放在一起的项目，仓库说明见 `README.md:5`。
- 后端是 FastAPI，应用入口在 `main.py:7`，主要路由和静态文件分发在 `services/api.py:132`。
- 前端是 Next.js App Router，构建后导出静态站点，再由后端直接提供静态文件，相关位置是 `web/next.config.ts:4`、`Dockerfile:10`、`Dockerfile:29`。
- 容器里只跑一个进程：`uvicorn main:app --port 80`，见 `Dockerfile:33`。
- 运行数据主存储是 `data/chatgpt2api.sqlite3`，配置读取位置是 `services/config.py`。旧 `data/*.json` 只在 SQLite 对应文档为空时导入一次。本地 compose 会把 `./data` 挂进容器，见 `docker-compose-local.yml`。
- 前端源码在 `web/src/`，不要去改 `web/.next/` 和 `web/out/` 里的生成文件。
