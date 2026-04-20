# account-pool-and-refresh

账号池由 `services/account_service.py:17` 的 `AccountService` 管理，数据常驻内存，修改后再写回文件。

核心规则：

- Token 会先清洗去重，见 `services/account_service.py:38`。
- 所有账号最终都会规范成统一字段集合，见 `services/account_service.py:98`。
- 写回文件只走 `services/account_service.py:161`，不要绕开它手动改结构。

增删改查：

- 列表接口的数据来自 `services/account_service.py:250`。
- 批量新增在 `services/account_service.py:263`，重复 token 会记为 `skipped`。
- 批量删除在 `services/account_service.py:293`。
- 单个更新在 `services/account_service.py:313`。

额度与状态：

- 图像额度和恢复时间从 `limits_progress` 提取，逻辑在 `services/account_service.py:139`。
- 成功生成后会更新 `success`、`last_used_at` 并扣减 `quota`，见 `services/account_service.py:329`。
- `quota` 降到 0 时状态切到“限流”；刷新后恢复额度则会回到“正常”。

远端刷新：

- 单账号刷新在 `services/account_service.py:357`。
- 它会并发请求 `chatgpt.com/backend-api/me` 和 `chatgpt.com/backend-api/conversation/init`。
- 批量刷新在 `services/account_service.py:428`，最多 10 个线程。
- 如果 `/backend-api/me` 返回 401，刷新逻辑会把账号改成“异常”，额度归零。

和前端上传 JSON 的关系：

- 后端只接收已经整理好的 token 列表，接口在 `services/api.py:186`。
- JSON 清洗和 `access_token` 提取都在前端账号页完成，后端不接收原始 JSON 文件。
