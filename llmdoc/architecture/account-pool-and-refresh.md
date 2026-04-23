# account-pool-and-refresh

账号池由 `services/account_service.py:17` 的 `AccountService` 管理，数据常驻内存，修改后再写回文件。

核心规则：

- Token 会先清洗去重，见 `services/account_service.py:38`。
- 所有账号最终都会规范成统一字段集合，见 `services/account_service.py:117`。
- 账号现在带 `category`，只接受“普通”和“捐赠”两类，默认是“普通”，规范化逻辑也在 `services/account_service.py:117`。
- 纯 token 或只带 auth 产物字段的 JSON 导入，会被标成 `needs_refresh=true`。这类账号即使当前 `quota=0`，也允许进入下一轮选号，再由请求前刷新补全真实额度，逻辑在 `services/account_service.py:57`、`services/account_service.py:147`、`services/account_service.py:355`。
- 写回文件只走 `services/account_service.py:161`，不要绕开它手动改结构。

增删改查：

- 列表接口的数据来自 `services/account_service.py:256`。
- 批量新增在 `services/account_service.py:309`，可额外带分类；纯 token 重复导入时会保留手工禁用状态，但会把运行时额度信息重置成待刷新。
- 批量导入完整账号对象在 `services/account_service.py:355`。如果同一个 token 已存在，会按新 JSON 覆盖已有字段，而不是只跳过。
- 批量删除在 `services/account_service.py:301`。
- 单个更新在 `services/account_service.py:321`。

额度与状态：

- 图像额度和恢复时间从 `limits_progress` 提取，逻辑在 `services/account_service.py:139`。
- 成功生成后会更新 `success`、`last_used_at` 并扣减 `quota`，见 `services/account_service.py:329`。
- `quota` 降到 0 时状态切到“限流”；刷新后恢复额度则会回到“正常”。
- 如果旧账号已经是“异常”，后面再次导入同一个 token 的 bare auth JSON，会回到“正常 + needs_refresh=true”，避免号池长期卡在 `No available tokens found`。

远端刷新：

- 单账号刷新在 `services/account_service.py:357`。
- 它会并发请求 `chatgpt.com/backend-api/me` 和 `chatgpt.com/backend-api/conversation/init`。
- 批量刷新在 `services/account_service.py:428`，最多 10 个线程。
- 如果 `/backend-api/me` 返回 401，刷新逻辑会把账号改成“异常”，额度归零。
- 刷新成功后会把 `needs_refresh` 清掉，逻辑在 `services/account_service.py:525`。

和前端上传 JSON 的关系：

- 管理员新增接口和捐赠新增接口都支持两种请求体：`tokens` 和 `accounts`，位置在 `services/api.py:607` 和 `services/api.py:635`。
- JSON 清洗和完整账号对象提取走前端公共工具 `web/src/lib/account-import.ts:1`，账号页和页头捐赠入口共用。
- 账号页与捐赠上传现在都会尽量保留原 JSON 里的 `email`、`refresh_token`、`user-agent`、`oai-device-id` 等字段，再交给后端规范化。
- 捐赠账户和普通账户都会留在同一个号池里。区别只在 `category`，可用性判断仍然只看状态和额度，见 `services/account_service.py:57`。
