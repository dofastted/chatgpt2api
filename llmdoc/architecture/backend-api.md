# backend-api

后端入口是 `services/api.py:132` 的 `create_app`。这里同时做四件事：

- 初始化 `BackendService`，把图片请求交给账号池轮询处理，见 `services/api.py:133`。
- 注册 CORS 中间件，见 `services/api.py:147`。
- 注册业务路由，见 `services/api.py:157` 到 `services/api.py:273`。
- 注册静态文件回退，让导出的前端站点和 API 共用一个进程，见 `services/api.py:278`。

鉴权模型：

- 角色解析在 `services/api.py:51`。
- 普通鉴权在 `services/api.py:78`。
- 管理员鉴权在 `services/api.py:83`。

接口分组：

- 公共信息：`/v1/models`、`/version`，位置在 `services/api.py:157` 与 `services/api.py:176`。
- 登录与会话：`/auth/login`、`/auth/session`，位置在 `services/api.py:166` 与 `services/api.py:171`。
- 账号池：`/api/accounts`、`/api/accounts/refresh`、`/api/accounts/update`，位置在 `services/api.py:180`、`services/api.py:225`、`services/api.py:238`。
- 普通额度接口：`/api/quota`，位置在 `services/api.py:214`。
- 图片生成：`/v1/images/generations`，位置在 `services/api.py:265`。

后台线程：

- `services/api.py:89` 会每 300 秒刷新一次“限流”账号。
- 线程只处理 `account_service.list_limited_tokens()` 返回的 token，不会全量刷新所有账号。
