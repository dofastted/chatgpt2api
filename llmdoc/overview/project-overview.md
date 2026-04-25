# project-overview

`chatgpt2api` 把两件事放在一个服务里：

- 维护一组 `access_token`，刷新邮箱、套餐类型、图片额度和恢复时间，主逻辑在 `services/account_service.py:17`。
- 对外提供兼容 OpenAI 风格的图片生成接口 `/v1/images/generations`，调度逻辑在 `services/backend_service.py:44` 和 `services/image_service.py:446`。

当前前端分成三块：

- 画图页给普通用户和管理员共用，页面在 `web/src/app/image/page.tsx:18`。
- 号池管理页只给管理员用，页面在 `web/src/app/accounts/page.tsx:199`。
- 画廊页给已登录用户使用，页面在 `web/src/app/gallery/page.tsx:5`。

最近这个仓库已经包含两项直接可见的能力：

- 普通密钥只能画图和看额度，管理员密钥才可进入号池管理，判断点见 `services/api.py:86` 和 `web/src/components/top-nav.tsx:25`。
- 账号页支持批量上传 JSON 文件，前端先清洗并递归提取 `access_token`，再直接调用新增接口，见 `web/src/lib/account-import.ts:1`、`web/src/app/accounts/page.tsx:372`、`web/src/lib/api.ts:127`。
- 画图页头部还有一个公开的“捐赠上传”入口。它会上传 JSON，提取 token，然后调用捐赠入池接口，见 `web/src/components/top-nav.tsx:68` 和 `web/src/lib/api.ts:134`。
- 账号页包含代理管理区，接口封装在 `web/src/lib/api.ts`，后端路由在 `services/api.py` 的 `/api/proxies` 段。
- 出站代理配置保存在 `services/proxy_service.py` 管理的 JSON 文件里，账号刷新和生图请求会读取当前启用代理。

如果要继续改：

- 改后端接口先看 `llmdoc/architecture/backend-api.md`。
- 改账号池行为先看 `llmdoc/architecture/account-pool-and-refresh.md`。
- 改前端权限和页面跳转先看 `llmdoc/architecture/frontend-routing-and-auth.md`。
- 改图片代理先看 `llmdoc/architecture/image-generation-flow.md`。
