# account-pool-and-refresh

账号池由 `services/account_service.py:17` 的 `AccountService` 管理，数据常驻内存，修改后再写回文件。

核心规则：

- Token 会先清洗去重，见 `services/account_service.py:38`。
- 所有账号最终都会规范成统一字段集合，见 `services/account_service.py:117`。
- 账号现在带 `category`，只接受“普通”和“捐赠”两类，默认是“普通”，规范化逻辑也在 `services/account_service.py:117`。
- 写回文件只走 `services/account_service.py:161`，不要绕开它手动改结构。

增删改查：

- 列表接口的数据来自 `services/account_service.py:256`。
- 批量新增在 `services/account_service.py:269`，可额外带分类；重复 token 会记为 `skipped`。
- 批量删除在 `services/account_service.py:301`。
- 单个更新在 `services/account_service.py:321`。

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

- 后端只接收已经整理好的 token 列表。管理员新增接口在 `services/api.py:265`，捐赠新增接口在 `services/api.py:283`。
- JSON 清洗和 `access_token` 提取走前端公共工具 `web/src/lib/account-import.ts:1`，账号页和页头捐赠入口共用。
- 捐赠账户和普通账户都会留在同一个号池里。区别只在 `category`，可用性判断仍然只看状态和额度，见 `services/account_service.py:57`。
