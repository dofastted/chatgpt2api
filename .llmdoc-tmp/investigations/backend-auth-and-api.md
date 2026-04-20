# backend-auth-and-api

- 入口在 `main.py:7`，应用由 `services/api.py:create_app` 组装，实际接口、静态文件回退和生命周期都在 `services/api.py:132`。
- 鉴权先走 `services/api.py:51` 的 `resolve_auth_role`。命中 `admin_auth_key` 返回 `admin`，命中 `auth_key` 返回 `user`。
- `services/api.py:78` 的 `require_auth_key` 负责普通鉴权，`services/api.py:83` 的 `require_admin_auth_key` 在此基础上再限制管理员。
- 登录和会话接口分别在 `services/api.py:166` 与 `services/api.py:171`，都会返回 `ok`、`version`、`role`。
- 账号池接口都挂在 `/api/accounts*`，只给管理员使用，位置在 `services/api.py:180`、`services/api.py:225`、`services/api.py:238`。
- 普通用户可以访问 `/api/quota` 和 `/v1/images/generations`，位置在 `services/api.py:214` 与 `services/api.py:265`。
- `services/api.py:89` 会启动一个后台线程，定时检查状态为“限流”的账号并刷新信息。
- API 层同时负责静态前端分发，找不到命中的资源时会回退到首页，逻辑在 `services/api.py:101` 与 `services/api.py:278`。
