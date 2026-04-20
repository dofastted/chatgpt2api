# frontend-routes-and-auth

- 前端请求层在 `web/src/lib/request.ts:14` 自动补 `Authorization` 请求头，`web/src/lib/request.ts:27` 统一处理错误。
- `401` 会清掉本地密钥并跳回登录页，位置在 `web/src/lib/request.ts:34`。`403` 只抛错，不强制跳转。
- 登录接口封装在 `web/src/lib/api.ts:58`，会话接口在 `web/src/lib/api.ts:70`，额度汇总接口在 `web/src/lib/api.ts:78`。
- 首页 `web/src/app/page.tsx:8` 启动后会先取会话，再按角色跳到 `/accounts` 或 `/image`。
- 登录页 `web/src/app/login/page.tsx:30` 也是同样的跳转规则。文案在 `web/src/app/login/page.tsx:49` 已明确普通密钥和管理员密钥的权限差异。
- 顶部导航在 `web/src/components/top-nav.tsx:15` 把“号池管理”限制为 `admin` 角色可见。
- 账号页在 `web/src/app/accounts/page.tsx:269` 会拦截非管理员访问，提示后跳去 `/image`。
- 批量 JSON 上传的清洗逻辑都在账号页本地完成：递归提取在 `web/src/app/accounts/page.tsx:179`，统一入口在 `web/src/app/accounts/page.tsx:382`，文件选择器在 `web/src/app/accounts/page.tsx:599`。
