# frontend-routing-and-auth

前端鉴权分三层：

- 存储层：`web/src/store/auth.ts:12`、`web/src/store/auth.ts:20`、`web/src/store/auth.ts:29` 用 `localforage` 读取、写入、清空密钥。
- 请求层：`web/src/lib/request.ts:14` 自动加 Bearer Token，`web/src/lib/request.ts:27` 统一处理响应错误。
- 页面层：各页面再根据 `role` 做跳转或隐藏入口；画图页另外会根据 `/api/quota` 的结果限制发送。

页面路由：

- 首页 `web/src/app/page.tsx:8` 启动后读取会话并按角色分流。
- 登录页 `web/src/app/login/page.tsx:28` 登录成功后也按角色分流。
- 顶部导航 `web/src/components/top-nav.tsx:13` 只在 `admin` 时显示“号池管理”。
- 账号页 `web/src/app/accounts/page.tsx:277` 会再次检查角色，普通用户会被送回 `/image`。

错误处理：

- `401` 会清掉本地密钥并直接跳 `/login`，见 `web/src/lib/request.ts:27` 到 `web/src/lib/request.ts:31`。
- `403` 不会自动跳转，所以页面内权限不足要自己处理，例如 `web/src/app/accounts/page.tsx:277`。

账号页 JSON 导入：

- 递归查找 `access_token` 字段的逻辑在 `web/src/lib/account-import.ts:1`。
- 账号页管理员启动时会同时拉账户列表和用户 key 列表，入口见 `web/src/app/accounts/page.tsx:277`。
- 用户 key 管理区支持批量生成、复制、编辑和删除，交互入口见 `web/src/app/accounts/page.tsx:598`、`web/src/app/accounts/page.tsx:632`、`web/src/app/accounts/page.tsx:1316`。
- 用户 key 对应的请求封装在 `web/src/lib/api.ts:119`、`web/src/lib/api.ts:148`、`web/src/lib/api.ts:180`、`web/src/lib/api.ts:193`。

画图页：

- 画图页不再读账号列表，而是调用 `/api/quota` 显示当前 key 可用次数，入口在 `web/src/app/image/page.tsx:188`。
- 前端发送时会先按模型和张数算成本，展示“本次消耗”，实现见 `web/src/app/image/page.tsx:122`、`web/src/app/image/page.tsx:612`。
- 如果当前额度不够，发送按钮会禁用，并显示提示，位置在 `web/src/app/image/page.tsx:644` 和 `web/src/app/image/page.tsx:652`。
- 图片请求改成一次请求带 `n`，位置在 `web/src/app/image/page.tsx:330` 和 `web/src/lib/api.ts:210`。
- 会话历史保存在浏览器本地，读写入口在 `web/src/store/image-conversations.ts:52`、`web/src/store/image-conversations.ts:57`、`web/src/store/image-conversations.ts:64`、`web/src/store/image-conversations.ts:72`。
