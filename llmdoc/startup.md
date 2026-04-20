# startup

处理这个仓库前，按下面顺序读：

1. `llmdoc/index.md`
2. `llmdoc/must/read-this-first.md`
3. `llmdoc/must/auth-and-roles.md`
4. `llmdoc/must/runtime-layout.md`
5. `llmdoc/overview/project-overview.md`

按任务继续读：

- 改鉴权、权限页、登录跳转，先看 `llmdoc/architecture/backend-api.md` 和 `llmdoc/architecture/frontend-routing-and-auth.md`。
- 改账号导入、刷新、额度状态，先看 `llmdoc/architecture/account-pool-and-refresh.md`。
- 改生图代理，先看 `llmdoc/architecture/image-generation-flow.md`。
- 改配置、容器、域名转发，先看 `llmdoc/reference/runtime-config.md`、`llmdoc/guides/local-run.md`、`llmdoc/guides/domain-and-frp.md`。

处理时注意：

- 运行时数据文件是 `data/accounts.json`，来源见 `services/config.py:72`。除非任务明确要求，不要手改。
- 前端产物目录是 `web/out`，容器内复制成 `web_dist`，来源见 `Dockerfile:29`。除非任务是构建或发布，不要直接改生成产物。
- 本地优先看 `docker-compose-local.yml:9` 的 `3002:80` 映射；线上镜像 compose 是 `docker-compose.yml:7` 的 `3000:80`。
