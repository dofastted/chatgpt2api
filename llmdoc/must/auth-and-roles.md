# auth-and-roles

- 这个项目现在有两把密钥：普通密钥 `auth_key` 和管理员密钥 `admin_auth_key`，加载位置见 `services/config.py:49` 到 `services/config.py:69`。
- `admin-auth-key` 没配时会回退到 `auth-key`，见 `services/config.py:54`。如果两者相同，普通用户和管理员就没有实际区分。
- 请求头统一使用 Bearer Token，角色判断在 `services/api.py:51`。
- 只要 key 合法，`/auth/login` 和 `/auth/session` 都会返回角色，接口位置在 `services/api.py:166` 与 `services/api.py:171`。
- 账号池相关接口只给管理员，限制在 `services/api.py:180`、`services/api.py:225`、`services/api.py:238`。
- 画图接口 `/v1/images/generations` 和额度接口 `/api/quota` 只要求合法 key，位置在 `services/api.py:214` 与 `services/api.py:265`。
- 前端登录后会按角色跳转，逻辑在 `web/src/app/login/page.tsx:30` 和 `web/src/app/page.tsx:18`。
- 顶部导航会把“号池管理”藏起来，位置在 `web/src/components/top-nav.tsx:15`。
- 账号页还有二次保护。非管理员进入时会提示并跳到 `/image`，见 `web/src/app/accounts/page.tsx:269`。
