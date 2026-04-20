# http-endpoints

接口都走 Bearer Token，说明见 `README.md:25`。

公开接口：

- `GET /v1/models`，返回支持的模型列表，位置在 `services/api.py:157`。
- `GET /version`，返回当前版本，位置在 `services/api.py:176`。

登录与会话：

- `POST /auth/login`，校验 key 后返回 `ok`、`version`、`role`，位置在 `services/api.py:166`。
- `GET /auth/session`，返回当前 key 对应的角色，位置在 `services/api.py:171`。

普通用户可用：

- `GET /api/quota`，返回所有未禁用账号的额度总和，位置在 `services/api.py:214`。
- `POST /v1/images/generations`，请求体是 prompt、model、n，位置在 `services/api.py:265`。

管理员可用：

- `GET /api/accounts`，返回账号列表，位置在 `services/api.py:180`。
- `POST /api/accounts`，接收 `tokens: string[]`，先新增再刷新账号信息，位置在 `services/api.py:184`。
- `DELETE /api/accounts`，接收 `tokens: string[]`，位置在 `services/api.py:199`。
- `POST /api/accounts/refresh`，接收 `access_tokens: string[]`，为空时刷新全部，位置在 `services/api.py:225`。
- `POST /api/accounts/update`，接收 `access_token` 和部分更新字段，位置在 `services/api.py:238`。

前端对应封装：

- 登录、会话、额度、账号列表、新增、刷新、更新都在 `web/src/lib/api.ts:58` 到 `web/src/lib/api.ts:120`。
