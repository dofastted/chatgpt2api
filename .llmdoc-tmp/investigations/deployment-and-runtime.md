# deployment-and-runtime

- 镜像构建是双阶段。前端先在 `Dockerfile:1` 的 Node 阶段打出 `web/out`，后端再在 `Dockerfile:13` 的 Python 阶段复制 `web_dist` 并启动 FastAPI。
- 容器启动命令在 `Dockerfile:33`，容器内固定监听 `80` 端口。
- 仓库自带两个 compose 文件。`docker-compose.yml:7` 用远端镜像并映射 `3000:80`，`docker-compose-local.yml:9` 本地构建并映射 `3002:80`。
- 两个 compose 都会挂载 `./data` 和只读的 `./config.json`，见 `docker-compose.yml:8` 与 `docker-compose-local.yml:10`。
- 配置样例只包含 `auth-key`、`admin-auth-key`、`tls-verify`，见 `config.example.json:2`。
- 已知当前项目还有一条仓库外部署链路：`img.fkcodex.com -> nginx -> frps -> frpc -> 本机 3002`。这部分配置不在仓库里，文档只记录入口和检查点。
