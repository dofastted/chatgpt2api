# image-generation-flow

图片生成请求可以从两条入口进入：

- 旧接口 `POST /v1/images/generations`，位置在 `services/api.py:558`。
- 新兼容层主入口是 `POST /v1/response`，同时兼容 `POST /v1/responses`，第一版支持文本加单张 `input_image`，位置在 `services/api.py` 的 Responses 路由段。

两条路最终都会交给 `BackendService.generate_with_pool`，位置在 `services/backend_service.py:37`。

处理顺序：

- 如果当前鉴权是 `user_key`，会先按这个 key 自己的 `pricing[model] * n` 预扣次数，公共逻辑在 `services/api.py:176`。
- 先从账号池选一个当前可用的 token，逻辑在 `services/backend_service.py:38`。
- 再用 `services/backend_service.py:21` 先刷新这个 token 的远端信息，确认它还有额度、状态也可用。
- 刷新结果不满足条件时会跳过这个 token，继续尝试下一个。
- 真正的远端图片请求交给 `services/image_service.py:446`。

远端请求过程：

- Session 和指纹头在 `services/image_service.py:88` 组装。
- Chat requirements token 在 `services/image_service.py:184` 获取。
- 如果请求里带 `input_image`，会先抓取或解码图片，再走 `/backend-api/files` 上传并写进会话 `attachments`。
- 会话流请求在 `services/image_service.py:215` 发出。
- SSE 解析在 `services/image_service.py:295`，会从流里提取文件标识和文字结果。
- `gpt-image-1` 继续走原生生图路径；`gpt-image-2` 现在直接走真实上游模型 `gpt-image-2`，转换逻辑在 `services/image_service.py` 的 `_resolve_upstream_target`。
- 如果请求来自 `user_key`，成功响应还会附带 `billing`，里面有本次模型、单价、实际扣减次数和剩余次数，公共逻辑在 `services/api.py:206`。
- 如果入口是 `/v1/response` 或 `/v1/responses`，结果还会被包成 `response.output[]`，图片项类型是 `image_generation_call`。对外应按官方格式把文本模型放在顶层 `model`，把真实图片模型放在 `tools[].model`；如果没传图片模型，当前默认按 `gpt-image-1` 处理。
- 对外协议转换都在 `services/api.py`。`build_responses_payload` 和 `iter_responses_stream` 负责 Responses 风格输出；`build_images_response_payload` 和 `iter_images_stream` 负责图片接口风格输出。
- `/v1/images/generations` 流式时，最后一定会给 `image_generation.completed` 和 `data: [DONE]`。
- `/v1/response` 或 `/v1/responses` 流式时，最后一定会给 `response.completed` 和 `data: [DONE]`。
- 前端图片页现在会把已选参考图存进本地会话历史，刷新后仍能在对话记录里区分“参考图”和“生成结果”。

2026-04-22 本地实测现状：

- 用本地 `3002` 上的真实接口、现有管理员密钥和提示词 `ABCD一二三` 做验收时，`gpt-image-1` 没有稳定输出目标文本，而是偏成了字母卡片和词汇配图。
- 同一组测试里，`gpt-image-2` 能稳定给出 `A B C D`，也能给出接近 `一 二 三` 的横线字形，但版式会被改写，不会严格原样排成连续的 `ABCD一二三`。
- 因此当前仓库层面的状态是：`gpt-image-2` 的文字控制明显好于 `gpt-image-1`，但两者都不能承诺“按提示逐字忠实还原”。

失败处理：

- 成功和失败统计都回写账号池，见 `services/account_service.py:329`。
- 如果报错命中失效 token 条件，判断在 `services/image_service.py:205`，随后 `services/backend_service.py:68` 会把 token 从池里删掉。
- 如果整个池里没有可用 token，`services/backend_service.py:38` 会抛出 `503`。
- 如果上游失败、接口中途抛错或路由层提前拒绝，`user_key` 的预扣次数会退回，公共逻辑在 `services/api.py:220`。
