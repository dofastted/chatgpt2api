# auth-and-roles

- 这个项目现在有三类密钥：普通密钥 `auth_key`、管理员密钥 `admin_auth_key`、用户 key 数据文件，配置入口见 `services/config.py:15` 和 `services/config.py:75`。
- `admin-auth-key` 没配时会回退到 `auth-key`，见 `services/config.py:54`。如果两者相同，普通用户和管理员就没有实际区分。
- Bearer Token 统一先走 `services/api.py:86` 的 `resolve_auth_context`。管理员密钥返回 `admin_auth_key`，普通密钥返回 `auth_key`，启用中的用户 key 返回 `user_key`。
- `POST /auth/login` 和 `GET /auth/session` 都会返回 `role`、`auth_type`、`remaining_quota`，实现见 `services/api.py:114`、`services/api.py:244`、`services/api.py:249`。
- 账号池接口和用户 key 管理接口都只给管理员，限制点在 `services/api.py:156`、`services/api.py:260`、`services/api.py:301`、`services/api.py:326`、`services/api.py:395`。
- 画图接口 `/v1/images/generations` 和额度接口 `/api/quota` 对普通密钥和用户 key 都开放，位置在 `services/api.py:337` 和 `services/api.py:422`。
- 用户 key 走独立存储与读写，服务入口在 `services/user_key_service.py:125`、`services/user_key_service.py:129`、`services/user_key_service.py:213`。
- 前端登录后仍只按 `role` 分流，逻辑在 `web/src/app/login/page.tsx:28` 和 `web/src/app/page.tsx:16`。
- 顶部导航继续只给管理员显示“号池管理”，位置在 `web/src/components/top-nav.tsx:13`。
- 账号页还有二次保护。非管理员进入时会提示并跳到 `/image`，见 `web/src/app/accounts/page.tsx:277`。
