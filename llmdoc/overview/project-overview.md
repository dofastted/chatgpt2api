# project-overview

`chatgpt2api` 把两件事放在一个服务里：

- 维护一组 `access_token`，刷新邮箱、套餐类型、图片额度和恢复时间，主逻辑在 `services/account_service.py:17`。
- 对外提供兼容 OpenAI 风格的图片生成接口 `/v1/images/generations`，调度逻辑在 `services/backend_service.py:44` 和 `services/image_service.py:446`。

当前前端分成两块：

- 画图页给普通用户和管理员共用，页面在 `web/src/app/image/page.tsx:18`。
- 号池管理页只给管理员用，页面在 `web/src/app/accounts/page.tsx:269`。

最近这个仓库已经包含两项直接可见的能力：

- 普通密钥只能画图和看额度，管理员密钥才可进入号池管理，判断点见 `services/api.py:51` 和 `web/src/components/top-nav.tsx:15`。
- 账号页支持批量上传 JSON 文件，前端先清洗并递归提取 `access_token`，再直接调用新增接口，见 `web/src/app/accounts/page.tsx:179`、`web/src/app/accounts/page.tsx:382`、`web/src/lib/api.ts:82`。

如果要继续改：

- 改后端接口先看 `llmdoc/architecture/backend-api.md`。
- 改账号池行为先看 `llmdoc/architecture/account-pool-and-refresh.md`。
- 改前端权限和页面跳转先看 `llmdoc/architecture/frontend-routing-and-auth.md`。
- 改图片代理先看 `llmdoc/architecture/image-generation-flow.md`。
