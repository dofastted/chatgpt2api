# runtime-layout

- 本地开发和本机部署优先用 `docker-compose-local.yml`。它会本地构建镜像，并把服务暴露到 `3002`，见 `docker-compose-local.yml:9`。
- 这台机器上的本地主工作树是 `X:/project/chatgpt2api`。临时迁移 worktree 不能长期占用 `main`，完成验证后应切到归档分支。
- 本机主容器应挂载主工作树的 `./data` 和 `./config.json`，也就是 `X:/project/chatgpt2api/data` 到 `/app/data`、`X:/project/chatgpt2api/config.json` 到 `/app/config.json`。
- 仓库默认的发布 compose 是 `docker-compose.yml`，直接拉 `ghcr.io/dofastted/chatgpt2api:latest`，见 `docker-compose.yml:3`。
- 当前稳定发布目标是 `fork/main`，push 到 `fork/main` 会触发 fork 仓库的 `Publish Docker Image` workflow，并发布 `ghcr.io/dofastted/chatgpt2api:latest`。`origin/main` 和本地 `main` 已严重分叉；除非用户明确要求处理上游分叉，不要直接推 `origin/main`，也不要强推 `origin/main`。
- `basketikun/chatgpt2api` 只作为历史上游参考，不作为默认部署来源。不要把 compose、README 或发布说明改回原始仓库地址。
- 两个 compose 都要求根目录有 `config.json`，并把它只读挂进容器，见 `docker-compose-local.yml:11` 与 `docker-compose.yml:9`。
- `data/`、`config.json`、`acc/`、`.llmdoc-tmp/` 都是本机运行或敏感文件，不能提交。清理开发容器和镜像时，不能删除这些目录和文件。
- `data-migration/` 只适合隔离验证和人工比较。不要用它直接覆盖主工作树 `data/`；先比较 `accounts.json`、`user_keys.json`、`redeem_codes.json`、`uploaded_images.json` 和 `uploaded_images/` 文件数，再合并缺失记录。
- Dockerfile 先编前端，再装 Python 依赖，最后复制 `web/out` 到 `web_dist`，见 `Dockerfile:1` 到 `Dockerfile:29`。
- 如果不走容器，`python main.py` 也能起服务，监听地址来自 `services/config.py:70` 和 `main.py:10`。
- 当前项目还有一条仓库外入口 `img.fkcodex.com`。它依赖远端 Nginx 和 FRP，把流量转回本机 `3002`。仓库里没有这些配置文件，修改这条线路时要同时检查服务器和本机。
- Git 操作继续用 Windows Git。遇到 Git 代理失败时，只做一次性命令级绕过，例如 `git -c http.proxy= -c https.proxy= fetch` 或 `push`；不要改全局 Git 代理配置。
