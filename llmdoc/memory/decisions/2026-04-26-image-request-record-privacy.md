# 2026-04-26 image request record privacy

## Decision

`image_request_records` 只保存可排查请求生命周期所需的摘要字段：

- Bearer Token 和账号 token 只保存 sha256。
- prompt 只保存前 80 字和 sha256。
- 输入图、生成图、base64、原始请求体和完整 prompt 不写入请求记录。

## Reason

请求记录的目的，是让管理员能按 `X-Image-Queue-Request-Id` 查询状态、耗时、扣费、错误和账号路线。完整 prompt、原始请求体和图片内容对这些排查目标不是必需字段，却会扩大隐私和数据泄露风险。

## Current implementation

- 表结构在 `services/sqlite_store.py`。
- 写入服务在 `services/image_request_log_service.py`。
- 三条入口接入在 `services/api.py`。
- 管理页查看在 `web/src/app/accounts/page.tsx`。
