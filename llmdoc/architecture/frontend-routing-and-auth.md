# frontend-routing-and-auth

前端鉴权分三层：

- 存储层：`web/src/store/auth.ts:12`、`web/src/store/auth.ts:20`、`web/src/store/auth.ts:29` 用 `localforage` 读取、写入、清空密钥。
- 请求层：`web/src/lib/request.ts:14` 自动加 Bearer Token，`web/src/lib/request.ts:27` 统一处理响应错误。API 基址优先取 `NEXT_PUBLIC_API_URL`；未配置时，浏览器里默认跟当前页面 origin 走，只有本机 `localhost:3000` 开发态才回退到 `127.0.0.1:8000`，入口在 `web/src/constants/common-env.ts:1`。
- 页面层：各页面再根据 `role` 做跳转或隐藏入口；画图页另外会根据 `/api/quota` 返回的余额和 `pricing` 限制发送。

页面路由：

- 首页 `web/src/app/page.tsx:8` 启动后读取会话并按角色分流。
- 登录页 `web/src/app/login/page.tsx:28` 登录成功后也按角色分流。
- 顶部导航 `web/src/components/top-nav.tsx` 只在 `admin` 时显示“号池管理”。所有已登录用户都能看到“兑换中心”；里面保留捐赠上传，也给 `user_key` 提供兑换码输入和直达购买链接。
- 兑换中心的购买链接是 `https://ldc.fkcodex.com/buy/4` 和 `https://ldc.fkcodex.com/buy/5`，分别对应 20 额度和 100 额度兑换码；弹窗里不再显示购买积分。
- 账号页 `web/src/app/accounts/page.tsx:251` 会再次检查角色，普通用户会被送回 `/image`。如果只是会话探测失败或请求地址不通，不会再直接误跳 `/login`，而是停留当前页报错。

错误处理：

- `401` 会清掉本地密钥并直接跳 `/login`，见 `web/src/lib/request.ts:27` 到 `web/src/lib/request.ts:31`。
- `403` 不会自动跳转，所以页面内权限不足要自己处理，例如 `web/src/app/accounts/page.tsx:257`。

账号页 JSON 导入：

- 递归查找 `access_token` 字段的逻辑在 `web/src/lib/account-import.ts:1`。
- 账号页管理员启动时会同时拉账户列表、用户 key 列表和兑换码列表。
- 账号列表支持按账户来源筛选，也能在编辑弹窗里把来源改成“普通”或“捐赠”，见 `web/src/app/accounts/page.tsx:277`、`web/src/app/accounts/page.tsx:504`、`web/src/app/accounts/page.tsx:795`。
- 账号页现在是 tab 布局，分成“账号池”“用户 Key”“兑换码”三块；`user key` 和兑换码列表默认每页 10 条。
- 用户 key 管理区支持批量生成、复制、单条编辑、批量编辑和删除。批量编辑可一次改状态、次数、积分余额和 `gpt-image-2` 单价。列表里的 key 现在只显示前 3 位和后 3 位。
- 兑换码管理区支持批量生成、复制、批量选择下载、批量删除，以及一键删除全部已使用兑换码；管理员只能生成 `20` 或 `100` 两档额度。
- 兑换码生成成功后，前端会把本次新生成的 code 按“一行一个”的 txt 直接下载，同时保留“下载本次 txt”按钮可重复导出。仓库里另存了一份 20 额度兑换码导出文件 `data/redeem_codes_quota20.txt`，给线下发码直接使用。
- 用户 key 和兑换码对应的请求封装都在 `web/src/lib/api.ts`。

画图页：

- 画图页不再读账号列表，而是调用 `/api/quota` 显示当前 key 可用次数。如果当前是 `user_key`，也会拿到这个 key 自己的 `pricing`，入口在 `web/src/app/image/page.tsx:240`。
- 前端发送时会先按当前 key 的模型单价和张数算成本，展示“本次消耗”和“当前单价”。当前默认模型已经固定成 `gpt-image-2`，实现见 `web/src/app/image/page.tsx:151`、`web/src/app/image/page.tsx:169`、`web/src/app/image/page.tsx:864`。
- 如果当前额度不够，发送按钮会禁用，并显示提示，位置在 `web/src/app/image/page.tsx:644` 和 `web/src/app/image/page.tsx:652`。
- 图片请求继续一次请求带 `n`。如果后端返回 `billing.remaining_quota`，前端会先就地刷新余额，再同步拉一次 `/api/quota`，位置在 `web/src/app/image/page.tsx:373` 和 `web/src/lib/api.ts:235`。
- 如果后端返回了 `copied_text`，画图页会把它保存到当前会话，并在结果区渲染一个“可复制文本”卡片，入口在 `web/src/app/image/page.tsx:489` 和 `web/src/app/image/page.tsx:724`。
- 会话历史保存在浏览器本地，读写入口在 `web/src/store/image-conversations.ts:26`、`web/src/store/image-conversations.ts:89`、`web/src/store/image-conversations.ts:98`、`web/src/store/image-conversations.ts:103`。
