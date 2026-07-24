# account-pool-and-refresh

账号池由 `services/account_service.py:17` 的 `AccountService` 管理，数据常驻内存，修改后写入 SQLite 文档。旧 `data/accounts.json` 只在 SQLite 对应文档为空时导入。

核心规则：

- Token 会先清洗去重，见 `services/account_service.py:38`。
- 所有账号最终都会规范成统一字段集合，见 `services/account_service.py:117`。
- 账号现在带 `category`，只接受“普通”和“捐赠”两类，默认是“普通”，规范化逻辑也在 `services/account_service.py:117`。
- 纯 token 或只带 auth 产物字段的 JSON 导入会先标成 `needs_refresh=true`；账号新增 API 会在同一次请求内刷新刚导入或更新的账号，只有远端验活成功并取得额度后才参与图片选号。
- 列表接口额外返回 `quotaKnown`、`availableForImages`、`availabilityReason`、槽位、冷却、最近错误和输入图统计。`needs_refresh=true` 时额度未知，不等同于确认额度为 0。
- 写回只走 `services/account_service.py` 的保存方法，最终进入 `services/sqlite_store.py`。不要绕开服务手动改结构。

增删改查：

- 列表接口的数据来自 `services/account_service.py:256`。
- 批量新增在 `services/account_service.py:309`，可额外带分类；纯 token 重复导入时会保留手工禁用状态，但会把运行时额度信息重置成待刷新。
- 批量导入完整账号对象在 `services/account_service.py:355`。如果同一个 token 已存在，会按新 JSON 覆盖已有字段，而不是只跳过。
- 批量删除在 `services/account_service.py:301`。
- 单个更新在 `services/account_service.py:321`。

额度与状态：

- 图像额度和恢复时间从 `limits_progress` 提取，逻辑在 `services/account_service.py:139`。
- 账号 Dashboard 展示资产、可调度、待刷新、停用、额度等汇总，也展示脱敏账号标识、邮箱、套餐、额度、恢复时间、槽位、成功/失败次数和最近错误；页面逻辑在 `web/src/app/accounts/page.tsx`。
- 成功生成会更新 `success`、`last_used_at`、清理最近错误并扣减 `quota`；失败会更新失败统计、冷却和诊断错误。账号池摘要由 `pool_summary()` 提供。
- `quota` 降到 0 时状态切到“限流”；刷新后恢复额度会回到“正常”。成功远端刷新也会清除旧的凭据停用原因，使重新取得有效凭据的账号恢复调度。

远端刷新：

- 单账号刷新在 `services/account_service.py:357`。
- 它会并发请求 `chatgpt.com/backend-api/me` 和 `chatgpt.com/backend-api/conversation/init`。
- 批量刷新在 `services/account_service.py:428`，最多 10 个线程。
- `POST /api/accounts/refresh` 仍支持管理员手动刷新；`POST /api/accounts`、`POST /api/external/accounts` 和捐赠导入会自动刷新本次导入的账号。
- HTTP 401、明确的 revoked/invalidated/expired token 等终态凭据错误会调用 `disable_account()`：保留账号资产，设为“禁用”、额度归零，并记录 `disabled_reason=credential_invalid`。代理、429、502、503、504 等瞬时错误只记录最近错误，不永久停用。
- 刷新成功后会清掉 `needs_refresh`、旧错误和旧停用原因。

和前端上传 JSON 的关系：

- 管理员新增接口和捐赠新增接口都支持两种请求体：`tokens` 和 `accounts`，位置在 `services/api.py` 的账号接口段。
- JSON 清洗和完整账号对象提取走前端公共工具 `web/src/lib/account-import.ts:1`，账号页和页头捐赠入口共用。
- 账号页与捐赠上传现在都会尽量保留原 JSON 里的 `email`、`refresh_token`、`user-agent`、`oai-device-id` 等字段，再交给后端规范化。
- 新增和捐赠上传会在保存后立即验活；响应返回 `refreshed`、`disabled`、`available` 和逐账号 `errors`，前端据此展示成功、可调度、自动停用和失败数量。
- 捐赠账户和普通账户留在同一个号池里。区别只在 `category`；调度要求账号未禁用、已刷新、额度大于 0、冷却结束且有空闲槽位。全部账号只是临时 busy/cooldown 时会等待，不会立即误报号池为空。

代理诊断：

- 管理员可调用 `POST /api/proxies/test` 检查当前出口。接口只返回代理来源、脱敏 URL、可达性、HTTP 状态、延迟和错误，不泄露代理用户名或密码。
- `CHATGPT2API_DEFAULT_PROXY_URL` 可显式覆盖默认值；`CHATGPT2API_DEPLOYMENT_PROFILE=local_frp` 默认使用 `http://host.docker.internal:10808`，`vps` 默认使用 `http://172.20.0.1:3208`，其他环境回退到 `http://127.0.0.1:10808`。
