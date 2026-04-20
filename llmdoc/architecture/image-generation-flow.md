# image-generation-flow

图片生成请求从 `services/api.py:265` 进入后，会交给 `BackendService.generate_with_pool`，位置在 `services/backend_service.py:44`。

处理顺序：

- 先从账号池选一个当前可用的 token，逻辑在 `services/backend_service.py:38`。
- 再用 `services/backend_service.py:21` 先刷新这个 token 的远端信息，确认它还有额度、状态也可用。
- 刷新结果不满足条件时会跳过这个 token，继续尝试下一个。
- 真正的远端图片请求交给 `services/image_service.py:446`。

远端请求过程：

- Session 和指纹头在 `services/image_service.py:88` 组装。
- Chat requirements token 在 `services/image_service.py:184` 获取。
- 会话流请求在 `services/image_service.py:215` 发出。
- SSE 解析在 `services/image_service.py:295`，会从流里提取文件标识和文字结果。

失败处理：

- 成功和失败统计都回写账号池，见 `services/account_service.py:329`。
- 如果报错命中失效 token 条件，判断在 `services/image_service.py:205`，随后 `services/backend_service.py:68` 会把 token 从池里删掉。
- 如果整个池里没有可用 token，`services/backend_service.py:38` 会抛出 `503`。
