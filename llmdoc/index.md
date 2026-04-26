# llmdoc

这个目录记录 `chatgpt2api` 的稳定说明。先读 `llmdoc/startup.md`，再读 `llmdoc/must/`。

## 起步

- `llmdoc/startup.md`
- `llmdoc/must/read-this-first.md`
- `llmdoc/must/auth-and-roles.md`
- `llmdoc/must/runtime-layout.md`

## 概览

- `llmdoc/overview/project-overview.md`

## 架构

- `llmdoc/architecture/backend-api.md`
- `llmdoc/architecture/account-pool-and-refresh.md`
- `llmdoc/architecture/frontend-routing-and-auth.md`
- `llmdoc/architecture/image-generation-flow.md`

## 参考

- `llmdoc/reference/runtime-config.md`
- `llmdoc/reference/http-endpoints.md`
- `llmdoc/reference/chat-image-compatibility-matrix.md`

当前稳定数据面：

- 主存储是 `data/chatgpt2api.sqlite3`。
- 旧 `data/*.json` 只作为首次导入和人工备份来源。
- 管理员页“数据管理”负责 SQLite 状态、备份、S3 设置、图片会话和日志查看。
- 生图请求记录在 SQLite 表 `image_request_records`，管理员页“数据管理”可查询请求摘要、耗时、扣费和路线。

## 指南

- `llmdoc/guides/local-run.md`
- `llmdoc/guides/domain-and-frp.md`

## 记忆区

- `llmdoc/memory/decisions/` 留给后续设计决策。
- `llmdoc/memory/decisions/2026-04-26-image-request-record-privacy.md` 记录生图请求记录只保存摘要和哈希的原因。
- `llmdoc/memory/reflections/` 留给后续任务回顾。
- `llmdoc/memory/reflections/2026-04-26-cherry-image-api-compat.md` 记录 Cherry Studio 图片 API 兼容、`response_format=url` 和 HTTP 图片 URL 的验证要点。
- `llmdoc/memory/reflections/2026-04-25-main-worktree-data-handoff.md` 记录主工作树接管、运行数据合并和迁移 worktree 归档规则。

## 临时调查

- `.llmdoc-tmp/investigations/` 只放本次初始化时的草稿，不当作稳定文档。
