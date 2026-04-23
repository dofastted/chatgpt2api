# frontend-routing-and-auth

前端鉴权分三层：

- 存储层：`web/src/store/auth.ts:12`、`web/src/store/auth.ts:20`、`web/src/store/auth.ts:29` 用 `localforage` 读取、写入、清空密钥。
- 请求层：`web/src/lib/request.ts:14` 自动加 Bearer Token，`web/src/lib/request.ts:27` 统一处理响应错误。API 基址优先取 `NEXT_PUBLIC_API_URL`；未配置时，浏览器里默认跟当前页面 origin 走，只有本机 `localhost:3000` 开发态才回退到 `127.0.0.1:8000`，入口在 `web/src/constants/common-env.ts:1`。
- 页面层：各页面再根据 `role` 做跳转或隐藏入口；画图页另外会根据 `/api/quota` 返回的余额和 `pricing` 限制发送。

页面路由：

- 首页 `web/src/app/page.tsx:8` 启动后读取会话并按角色分流。
- 登录页 `web/src/app/login/page.tsx:28` 登录成功后也按角色分流。
- 顶部导航 `web/src/components/top-nav.tsx:25` 只在 `admin` 时显示“号池管理”，但“捐赠上传”对所有已登录用户都可见，逻辑在 `web/src/components/top-nav.tsx:68` 到 `web/src/components/top-nav.tsx:229`。
- 账号页 `web/src/app/accounts/page.tsx:251` 会再次检查角色，普通用户会被送回 `/image`。如果只是会话探测失败或请求地址不通，不会再直接误跳 `/login`，而是停留当前页报错。

错误处理：

- `401` 会清掉本地密钥并直接跳 `/login`，见 `web/src/lib/request.ts:27` 到 `web/src/lib/request.ts:31`。
- `403` 不会自动跳转，所以页面内权限不足要自己处理，例如 `web/src/app/accounts/page.tsx:257`。

账号页 JSON 导入：

- 递归查找 `access_token` 字段的逻辑在 `web/src/lib/account-import.ts:1`。
- 账号页管理员启动时会同时拉账户列表和用户 key 列表，入口见 `web/src/app/accounts/page.tsx:251`。
- 账号列表支持按账户来源筛选，也能在编辑弹窗里把来源改成“普通”或“捐赠”，见 `web/src/app/accounts/page.tsx:277`、`web/src/app/accounts/page.tsx:504`、`web/src/app/accounts/page.tsx:795`。
- 用户 key 管理区支持批量生成、复制、编辑和删除。当前公开生图只保留 `gpt-image-2`，所以页面里 `gpt-image-1` 会显示为已下架且固定为 0，交互入口见 `web/src/app/accounts/page.tsx:661`、`web/src/app/accounts/page.tsx:972`、`web/src/app/accounts/page.tsx:1481`。
- 用户 key 对应的请求封装在 `web/src/lib/api.ts:43`、`web/src/lib/api.ts:98`、`web/src/lib/api.ts:109`、`web/src/lib/api.ts:203`、`web/src/lib/api.ts:217`。

画图页：

- 画图页不再读账号列表，而是调用 `/api/quota` 显示当前 key 可用次数。如果当前是 `user_key`，也会拿到这个 key 自己的 `pricing`，入口在 `web/src/app/image/page.tsx:240`。
- 前端发送时会先按当前 key 的模型单价和张数算成本，展示“本次消耗”和“当前单价”。当前默认模型已经固定成 `gpt-image-2`，实现见 `web/src/app/image/page.tsx:151`、`web/src/app/image/page.tsx:169`、`web/src/app/image/page.tsx:864`。
- 如果当前额度不够，发送按钮会禁用，并显示提示，位置在 `web/src/app/image/page.tsx:644` 和 `web/src/app/image/page.tsx:652`。
- 图片请求继续一次请求带 `n`。如果后端返回 `billing.remaining_quota`，前端会先就地刷新余额，再同步拉一次 `/api/quota`，位置在 `web/src/app/image/page.tsx:373` 和 `web/src/lib/api.ts:235`。
- 如果后端返回了 `copied_text`，画图页会把它保存到当前会话，并在结果区渲染一个“可复制文本”卡片，入口在 `web/src/app/image/page.tsx:489` 和 `web/src/app/image/page.tsx:724`。
- 会话历史保存在浏览器本地，读写入口在 `web/src/store/image-conversations.ts:26`、`web/src/store/image-conversations.ts:89`、`web/src/store/image-conversations.ts:98`、`web/src/store/image-conversations.ts:103`。
