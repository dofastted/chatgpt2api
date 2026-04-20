# account-pool-service

- 核心类是 `services/account_service.py:17` 的 `AccountService`，启动时把 `config.accounts_file` 读入内存。
- Token 清洗和去重在 `services/account_service.py:38`，持久化写回在 `services/account_service.py:161`。
- 公开返回给前端的数据会经过 `_public_items` 处理，原始 `access_token` 仍会保留在响应里，定义在 `services/account_service.py:194`。
- 轮询取可用账号靠 `services/account_service.py:224` 的 `next_token`，它只挑未禁用且 `quota > 0` 的账号。
- 批量新增、删除、更新分别在 `services/account_service.py:263`、`services/account_service.py:293`、`services/account_service.py:313`。
- 成功或失败后的统计更新在 `services/account_service.py:329`。成功会扣减额度，并在额度归零时把状态改成“限流”。
- 远端刷新逻辑在 `services/account_service.py:357`。它会并发请求 `chatgpt.com/backend-api/me` 和 `chatgpt.com/backend-api/conversation/init`，再提取邮箱、类型、额度、恢复时间。
- 批量刷新在 `services/account_service.py:428`。远端返回 401 时会把账号改成“异常”，额度清零。
