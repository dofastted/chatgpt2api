# runtime-layout

- 本地开发和本机部署优先用 `docker-compose-local.yml`。它会本地构建镜像，并把服务暴露到 `3002`，见 `docker-compose-local.yml:9`。
- 仓库默认的发布 compose 是 `docker-compose.yml`，直接拉 `ghcr.io/basketikun/chatgpt2api:latest`，见 `docker-compose.yml:3`。
- 两个 compose 都要求根目录有 `config.json`，并把它只读挂进容器，见 `docker-compose-local.yml:11` 与 `docker-compose.yml:9`。
- Dockerfile 先编前端，再装 Python 依赖，最后复制 `web/out` 到 `web_dist`，见 `Dockerfile:1` 到 `Dockerfile:29`。
- 如果不走容器，`python main.py` 也能起服务，监听地址来自 `services/config.py:70` 和 `main.py:10`。
- 当前项目还有一条仓库外入口 `img.fkcodex.com`。它依赖远端 Nginx 和 FRP，把流量转回本机 `3002`。仓库里没有这些配置文件，修改这条线路时要同时检查服务器和本机。
