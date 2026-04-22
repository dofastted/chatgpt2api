# backend-api

后端入口是 `services/api.py:187` 的 `create_app`。这里同时做四件事：

- 初始化 `BackendService`，把图片请求交给账号池轮询处理，见 `services/api.py:249`。
- 注册 CORS 中间件，见 `services/api.py:263`。
- 注册业务路由，见 `services/api.py:275` 到 `services/api.py:613`。
- 注册静态文件回退，让导出的前端站点和 API 共用一个进程，见 `services/api.py:540`。

鉴权模型：

- 认证上下文解析在 `services/api.py:100`。
- 普通鉴权在 `services/api.py:192`。
- 管理员鉴权在 `services/api.py:199`。
- `user_key` 的模型单价解析在 `services/api.py:142`，图片模型名校验在 `services/api.py:169`。
- 图片请求如果走 `user_key`，实际扣费不再是全局固定倍率，而是 `pricing[model] * n`，预扣与回退逻辑在 `services/api.py:481`。
- 图片协议转换也在这一层完成：`build_images_response_payload`、`iter_images_stream`、`build_responses_payload`、`iter_responses_stream` 会把内部结果包成对外接口需要的 JSON 或 SSE。

接口分组：

- 公共信息：`/v1/models`、`/version`，位置在 `services/api.py:273` 与 `services/api.py:293`。
- Response 图片兼容：主入口是 `/v1/response`、`/v1/response/{response_id}`，同时保留 `/v1/responses`、`/v1/responses/{response_id}` 兼容，位置在 `services/api.py` 的 Responses 路由段。
- 登录与会话：`/auth/login`、`/auth/session`，位置在 `services/api.py:283` 与 `services/api.py:288`。
- 账号池：`/api/accounts`、`/api/accounts/refresh`、`/api/accounts/update`，位置在 `services/api.py:297`、`services/api.py:412`、`services/api.py:425`。
- 用户 key：`/api/user-keys`、`/api/user-keys/update`，位置在 `services/api.py:302`、`services/api.py:362`、`services/api.py:388`、`services/api.py:453`。
- 额度接口：`/api/quota`，位置在 `services/api.py:399`。
- 图片生成：`/v1/images/generations`，位置在 `services/api.py:558`。

协议约定：

- `/v1/response` 和 `/v1/responses` 对外按 OpenAI Responses 风格返回 `response.output[]`，图片项类型是 `image_generation_call`。
- Responses 生图的顶层 `model` 应是文本模型，真实图片模型放在 `tools[].model`。API 层会把内部图片结果挂到 `response.output[]`，并保持 `billing.requested_model` 是真实生图模型。
- Responses 生图第一版现在支持 `input_text + 单张 input_image`。API 层会校验 `image_url` 只能是 `http(s)` 或 `data:image/*`，然后把图片上传成上游附件再发会话请求。
- `/v1/images/generations` 的流式输出按图片接口风格返回；最终结果一定会给 `image_generation.completed`，然后给 `data: [DONE]`。
- `/v1/response` 的流式输出按 Responses 接口风格返回；最终结果一定会给 `response.completed`，然后给 `data: [DONE]`。

后台线程：

- `services/api.py:206` 会每 300 秒刷新一次“限流”账号。
- 线程只处理 `account_service.list_limited_tokens()` 返回的 token，不会全量刷新所有账号。
