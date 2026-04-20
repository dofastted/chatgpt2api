# image-generation-pipeline

- 图片生成入口在 `services/backend_service.py:44` 的 `generate_with_pool`。
- 每次请求先从账号池里拿一个可用 token，再用 `services/backend_service.py:21` 刷新该账号的远端信息，确认它仍能生图。
- 真正的远端请求在 `services/image_service.py:446` 的 `generate_image_result`。
- 会话初始化依赖 `services/image_service.py:88` 创建带指纹信息的 Session，再通过 `services/image_service.py:184` 获取 `chat-requirements` token。
- 发起图片生成流请求的逻辑在 `services/image_service.py:215`，SSE 解析在 `services/image_service.py:295`。
- 如果生成报错且判断为 token 已失效，`services/image_service.py:205` 会返回命中结果，随后 `services/backend_service.py:68` 会把这个 token 从账号池移除。
- 前端画图页通过 `web/src/lib/api.ts:120` 调 `/v1/images/generations`，额度显示改用 `web/src/lib/api.ts:78` 的 `/api/quota`。
