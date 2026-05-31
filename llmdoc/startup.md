# startup

处理这个仓库前，按下面顺序读：

1. `llmdoc/index.md`
2. `llmdoc/must/read-this-first.md`
3. `llmdoc/must/auth-and-roles.md`
4. `llmdoc/must/runtime-layout.md`
5. `llmdoc/overview/project-overview.md`
6. 如果任务碰到生图卡住、`low quality text render`、代理报错 `curl: (7) Failed to connect ... 10808`、或发布分支判断，继续读 `llmdoc/memory/reflections/2026-05-05-image-proxy-review-boundaries.md`

按任务继续读：

- 改鉴权、权限页、登录跳转，先看 `llmdoc/architecture/backend-api.md` 和 `llmdoc/architecture/frontend-routing-and-auth.md`。
- 改账号导入、刷新、额度状态，先看 `llmdoc/architecture/account-pool-and-refresh.md`。
- 改生图代理，先看 `llmdoc/architecture/image-generation-flow.md`。
- 改配置、容器、域名转发，先看 `llmdoc/reference/runtime-config.md`、`llmdoc/guides/local-run.md`、`llmdoc/guides/domain-and-frp.md`。

处理时注意：

- 运行主存储是 `data/chatgpt2api.sqlite3`。旧 `data/accounts.json` 等 JSON 只作为对应 SQLite 文档为空时的一次性导入来源或人工备份来源；除非任务明确要求，不要手改运行数据。
- 前端产物目录是 `web/out`，容器内复制成 `web_dist`，来源见 `Dockerfile:29`。除非任务是构建或发布，不要直接改生成产物。
- 本地优先看 `docker-compose-local.yml:9` 的 `3002:80` 映射；线上镜像 compose 是 `docker-compose.yml:7` 的 `3000:80`，默认镜像必须是 `ghcr.io/dofastted/chatgpt2api:latest`。
- 生图问题先区分三类：队列终态传播、代理瞬时失败、上游账号/配额问题。不要把 `curl: (7) Failed to connect ... 10808` 先归因成文字质量审查或账号质量。
- 这轮稳定发布目标是 `fork/main`，push 后由 fork 仓库 workflow 发布 `ghcr.io/dofastted/chatgpt2api:latest`。`origin/main` 和本地 `main` 已严重分叉；除非用户明确要求处理上游分叉，不要推或强推 `origin/main`。`basketikun/chatgpt2api` 不作为部署来源。
