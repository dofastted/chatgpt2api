# http-endpoints

接口都走 Bearer Token，说明见 `README.md:25`。

公开接口：

- `GET /v1/models`，返回支持的模型列表，位置在 `services/api.py:211`。
- `GET /version`，返回当前版本，位置在 `services/api.py:252`。

登录与会话：

- `POST /auth/login`，校验 key 后返回 `ok`、`version`、`role`、`auth_type`、`remaining_quota`，位置在 `services/api.py:242`。
- `GET /auth/session`，返回当前 key 对应的角色和剩余次数，位置在 `services/api.py:247`。

普通用户可用：

- `GET /api/quota`，普通密钥返回账号池总额度，用户 key 返回自己的剩余次数，位置在 `services/api.py:337`。
- `POST /v1/images/generations`，请求体是 `prompt`、`model`、`n`。用户 key 会先按 `n * multiplier` 预扣，成功保留，失败退回，位置在 `services/api.py:422`。

管理员可用：

- `GET /api/accounts`，返回账号列表，位置在 `services/api.py:256`。
- `POST /api/accounts`，接收 `tokens: string[]`，先新增再刷新账号信息，位置在 `services/api.py:264`。
- `DELETE /api/accounts`，接收 `tokens: string[]`，位置在 `services/api.py:314`。
- `POST /api/accounts/refresh`，接收 `access_tokens: string[]`，为空时刷新全部，位置在 `services/api.py:347`。
- `POST /api/accounts/update`，接收 `access_token` 和部分更新字段，位置在 `services/api.py:360`。
- `GET /api/user-keys`，返回用户 key 列表，位置在 `services/api.py:260`。
- `POST /api/user-keys`，接收 `count`、`quota`、`prefix`、`label_prefix`，批量生成用户 key，位置在 `services/api.py:301`。
- `DELETE /api/user-keys`，接收 `keys: string[]`，位置在 `services/api.py:326`。
- `POST /api/user-keys/update`，接收 `key` 和部分更新字段，位置在 `services/api.py:395`。

前端对应封装：

- 登录、会话、额度、账号列表、新增、刷新、更新都在 `web/src/lib/api.ts:84` 到 `web/src/lib/api.ts:210`。
