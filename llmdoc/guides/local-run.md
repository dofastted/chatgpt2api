# local-run

本地起服务优先用 `docker-compose-local.yml`，因为这个文件会本地构建当前代码，而不是拉远端镜像，定义见 `docker-compose-local.yml:3`。

这台机器的本地主工作树是 `X:/project/chatgpt2api`。如果曾在 `X:/project/chatgpt2api-chat-image-worktree` 验证迁移代码，正式本机容器仍应回到主工作树启动；临时 worktree 只能保留在归档分支。

发布和 Git 边界：

1. 当前稳定发布目标是 `fork/main`。
2. push 到 `fork/main` 会触发 fork 仓库的 `Publish Docker Image` workflow，默认镜像是 `ghcr.io/dofastted/chatgpt2api:latest`。
3. `origin/main` 和本地 `main` 已严重分叉；除非用户明确要求处理上游分叉，不要推 `origin/main`，也不要强推 `origin/main`。
4. `basketikun/chatgpt2api` 只作为历史上游参考，不作为部署来源；不要把默认 compose 或 README 改回原始仓库。
5. Git 操作继续用 Windows Git，不要切回 WSL Git 混用。
6. 如果 Git 因代理失败，可对单条命令临时禁用代理直连，例如 `git -c http.proxy= -c https.proxy= fetch`、`pull`、`push`。只限这一次命令，不改全局配置。

最短路径：

1. 以 `config.example.json:2` 到 `config.example.json:4` 为样例，在仓库根目录准备 `config.json`。
2. 至少设置一把普通密钥；如果要进号池管理，再单独设置管理员密钥，读取规则见 `services/config.py:49` 到 `services/config.py:55`。
3. 启动 `docker compose -f docker-compose-local.yml up -d --build`。
4. 打开 `http://127.0.0.1:3002/login`。

运行后会得到：

- 前端静态站点由同一个 FastAPI 进程提供，见 `services/api.py:278`。
- 运行数据默认写到宿主机 `./data/chatgpt2api.sqlite3`。旧 `./data/accounts.json` 等 JSON 只作为 SQLite 对应文档为空时的一次性导入来源或人工备份来源。
- 本地容器会带 `restart: unless-stopped`，也就是 Docker daemon 自己恢复后会自动拉起当前服务，定义见 `docker-compose-local.yml:3`。

接管或重启主容器前：

- 先确认容器挂载来自主工作树：`docker inspect chatgpt2api --format '{{json .Mounts}}'`。
- 先查队列：`GET /api/image-queue/me`，等待和运行都应为 `0` 后再切换容器。
- `data-migration/` 不能直接覆盖 `data/`。如果要迁入数据，先备份主工作树 `data/`，再按 JSON 记录和上传文件逐项合并。
- 清理开发容器和镜像时，只删临时容器、临时镜像和临时 worktree 产物；不要删除 `data/`、`config.json`、`acc/`、`.llmdoc-tmp/`。

检查点：

- 普通密钥登录后应该进入 `/image`，规则见 `web/src/app/login/page.tsx:30`。
- 管理员密钥登录后应该进入 `/accounts`，规则也在 `web/src/app/login/page.tsx:30`。
- 普通密钥访问号池管理页时应被挡回 `/image`，见 `web/src/app/accounts/page.tsx:269`。
- 如果要确认当前实例已经带上自启动，可在宿主机执行 `docker inspect chatgpt2api --format '{{.HostConfig.RestartPolicy.Name}}'`，期望值是 `unless-stopped`。
- 如果生图请求报 `curl: (7) Failed to connect ... 10808`，先做本机代理连通性检查，再按短退避重试或重新触发请求；不要先回滚成文字质量审查，也不要先判成账号坏。
