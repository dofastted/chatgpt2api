# backend-api

后端入口是 `services/api.py:187` 的 `create_app`。这里同时做四件事：

- 初始化 `BackendService`，把图片请求交给账号池轮询处理，见 `services/api.py:188`。
- 注册 CORS 中间件，见 `services/api.py:202`。
- 注册业务路由，见 `services/api.py:211` 到 `services/api.py:447`。
- 注册静态文件回退，让导出的前端站点和 API 共用一个进程，见 `services/api.py:450`。

鉴权模型：

- 认证上下文解析在 `services/api.py:86`。
- 普通鉴权在 `services/api.py:150`。
- 管理员鉴权在 `services/api.py:157`。
- 图片扣点公式在 `services/api.py:126`，当前只支持 `gpt-image-1 = 1` 和 `gpt-image-2 = 4`。

接口分组：

- 公共信息：`/v1/models`、`/version`，位置在 `services/api.py:211` 与 `services/api.py:252`。
- 登录与会话：`/auth/login`、`/auth/session`，位置在 `services/api.py:242` 与 `services/api.py:247`。
- 账号池：`/api/accounts`、`/api/accounts/refresh`、`/api/accounts/update`，位置在 `services/api.py:256`、`services/api.py:347`、`services/api.py:360`。
- 用户 key：`/api/user-keys`、`/api/user-keys/update`，位置在 `services/api.py:260`、`services/api.py:301`、`services/api.py:326`、`services/api.py:395`。
- 额度接口：`/api/quota`，位置在 `services/api.py:337`。
- 图片生成：`/v1/images/generations`，位置在 `services/api.py:422`。

后台线程：

- `services/api.py:163` 会每 300 秒刷新一次“限流”账号。
- 线程只处理 `account_service.list_limited_tokens()` 返回的 token，不会全量刷新所有账号。
