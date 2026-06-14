# frontend-routing-and-auth

前端鉴权分三层：

- 存储层：`web/src/store/auth.ts` 通过内存缓存、`localStorage` 和 `localforage` 三层读写密钥，用于兼顾同步读取、刷新保留和旧数据兼容。
- 请求层：`web/src/lib/request.ts:14` 自动加 Bearer Token，`web/src/lib/request.ts:27` 统一处理响应错误。API 基址优先取 `NEXT_PUBLIC_API_URL`；未配置时，浏览器里默认跟当前页面 origin 走，只有本机 `localhost:3000` 开发态才回退到 `127.0.0.1:8000`，入口在 `web/src/constants/common-env.ts:1`。
- 页面层：各页面再根据 `role` 做跳转或隐藏入口；画图页另外会根据 `/api/quota` 返回的余额和 `pricing` 限制发送。

页面路由：

- 首页 `web/src/app/page.tsx:8` 启动后读取会话并按角色分流。
- 登录页 `web/src/app/login/page.tsx:28` 登录成功后也按角色分流。
- 主要可见业务页共用一套 minimal-dark 主题入口：`web/src/app/layout.tsx` 负责字体和全局壳子，`web/src/app/globals.css` 提供暗色 token、页面壳子和导航样式，基础控件默认外观在 `web/src/components/ui/`。
- 顶部导航 `web/src/components/top-nav.tsx` 对所有已登录用户显示“画图”和“画廊”，只在 `admin` 时显示“号池管理”。所有已登录用户都能看到“兑换中心”；里面保留捐赠上传，也给 `user_key` 提供兑换码输入和直达购买链接。
- 兑换中心的购买链接是 `https://ldc.fkcodex.com/buy/4` 和 `https://ldc.fkcodex.com/buy/5`，分别对应 20 额度和 100 额度兑换码；弹窗里不再显示购买积分。
- 账号页 `web/src/app/accounts/page.tsx:251` 会再次检查角色，普通用户会被送回 `/image`。如果只是会话探测失败或请求地址不通，不会再直接误跳 `/login`，而是停留当前页报错。
- 画廊页 `web/src/app/gallery/page.tsx` 复用 `web/src/components/image-gallery-panel.tsx`。公开画廊优先读 `GET /api/gallery/public`；后端不可用或没有数据时才回退 `web/src/data/gallery-ui-seed.json` 和 `web/src/data/gallery-image-dimensions.json`。

错误处理：

- `401` 会清掉本地密钥并直接跳 `/login`，见 `web/src/lib/request.ts:27` 到 `web/src/lib/request.ts:31`。
- `403` 不会自动跳转，所以页面内权限不足要自己处理，例如 `web/src/app/accounts/page.tsx:257`。

账号页 JSON 导入：

- 递归查找 `access_token` 字段的逻辑在 `web/src/lib/account-import.ts:1`。
- 账号页管理员启动时会同时拉账户列表、用户 key 列表和兑换码列表。
- 账号资产区不再展示 token、邮箱、恢复时间、成功/失败次数等明细，只显示“可用”“无效”“可使用生图次数”和派发规则面板；远端账号信息只通过管理员手动刷新。
- 账号资产面板使用后端 `quotaKnown` 区分待刷新和已确认额度。只有 `status=正常`、`quotaKnown=true` 且 `quota>0` 的账号计入“可用”和“可使用生图次数”，其他账号都计入“无效”，避免把未知额度当作真实可用额度。
- 账号页现在是 tab 布局，分成“账号池”“用户 Key”“兑换码”“数据管理”“画廊管理”五块；`user key` 和兑换码列表默认每页 10 条。账号池页顶部还提供 proxy 管理，接口封装在 `web/src/lib/api.ts` 的 `fetchProxies`、`upsertProxy`、`deleteProxy`。
- 用户 key 管理区支持批量生成、复制、单条编辑、批量编辑和删除。批量编辑可一次改状态、次数、积分余额和 `gpt-image-2`、`gpt-image-2-2K`、`gpt-image-2-4K` 单价。列表里的 key 现在只显示前 3 位和后 3 位。
- 兑换码管理区支持批量生成、复制、批量选择下载、批量删除，以及一键删除全部已使用兑换码；管理员只能生成 `20` 或 `100` 两档额度。
- 兑换码生成成功后，前端会把本次新生成的 code 按“一行一个”的 txt 直接下载，同时保留“下载本次 txt”按钮可重复导出。仓库里另存了一份 20 额度兑换码导出文件 `data/redeem_codes_quota20.txt`，给线下发码直接使用。
- 用户 key 和兑换码对应的请求封装都在 `web/src/lib/api.ts`。
- “数据管理”tab 只给管理员显示。它调用 `fetchDataManagementStatus`、`fetchDataManagementSettings`、`createDataBackup`、`fetchDataBackups`、`testDataManagementS3` 和 `fetchDataManagementLogs`，用于查看 SQLite、保存备份设置、手动备份和配置 S3 备份上传。
- “画廊管理”tab 只给管理员显示。它调用 `fetchAdminGalleryItems`、`updateAdminGalleryItem` 和 `deleteAdminGalleryItem`，用于审核用户投稿、发布/隐藏公开项、置顶、编辑标题和 prompt、调整排序、删除画廊项。

画图页：

- 画图页不再读账号列表，而是调用 `/api/quota` 显示当前 key 可用次数。如果当前是 `user_key`，也会拿到这个 key 自己的 `pricing`，入口在 `web/src/app/image/page.tsx:240`。
- 画图页工具区提供“打开画廊”入口，画廊预览弹层可把 prompt 带回 `/image?prompt=...&focus=prompt`。`/image` 收到 `focus=prompt` 后会聚焦并滚动到输入框，再清掉查询串。
- 画图页顶部栏放“新建”和“配置”。主界面在桌面端是历史侧栏、对话区、画廊栏三栏结构；中间对话区使用 `minmax(0, 1fr)` 风格的弹性区域承载结果和 composer，避免被左右两栏挤出。侧栏默认隐藏且只显示会话历史；桌面端用左上角按钮展开或收起，移动端用浮层抽屉打开。桌面历史侧栏使用约 500ms 的宽度、透明度和位移动画，不再用 spring 弹性动画；历史条目只做轻微 fade 和 y 轴移动。隐藏后的桌面侧栏不可点击，避免挡住顶部按钮。首屏不拉会话历史。侧栏打开后先请求 `/api/image-conversations?summary=true` 读取轻量摘要，摘要只保留最新 turn、`turnCount` 和状态字段；点选某条会话时再请求 `/api/image-conversations/{conversation_id}` 读取完整图片和 turn 数据。清空历史按钮在侧栏底部，点击后必须在弹窗里二次确认。图像尺寸默认 `auto`，配置弹窗支持自动、只控分辨率、只控比例三种方式；自动时分辨率和比例不可控，单项自定义时另一项保存为 `auto`，尺寸计算在 `web/src/lib/image-size.ts`。侧栏、历史条目、结果图和输入区使用 `motion/react` 做轻量动效，并通过 `prefers-reduced-motion` 降低动效。
- 画图页右侧桌面端常驻画廊栏由 `web/src/app/image/page.tsx` 内部的 `ImageInspirationRail` 渲染。它优先读取 `GET /api/gallery/public`，后端不可用或没有数据时回退 `gallery-ui-seed.json` 和 `gallery-image-dimensions.json`，两列展示小图，点击小图只打开预览弹窗，不直接改输入框。弹窗里提供复制 prompt 和“带入 prompt”，用户点“带入 prompt”后才写入 composer 并聚焦。右侧画廊栏可隐藏；隐藏状态只存在当前页面 state，不写后端。
- `ImageInspirationRail` 的滚动容器带 `data-auto-scroll="image-inspiration-rail"`，会按自身 `scrollTop` 自动下滚；鼠标移入右侧“画廊灵感”时暂停，鼠标移出后等待 3 秒再继续滚动。真实瀑布布局和自动滚动都在 `web/src/app/image/page.tsx` 内部完成，验证时应检查这个滚动容器，而不是独立 `/gallery` 页面。
- 画图页生成成功的结果图下方会显示“添加到本地画廊”。点击后会把这张生成图存入 `web/src/store/gallery-prompts.ts` 的 `user_waterfall_items:<hashed scope>` 本地记录，并在右侧“画廊灵感”最前面显示为“我的作品”；同一张图再次添加时按钮显示“已在本地画廊”。本地 scope 来自当前 auth key 的哈希，不再把原始 Bearer Token 写进 localforage key 名。
- 添加到本地画廊后，前端会异步调用 `POST /api/gallery/submissions` 提交后台审核；提交失败不会回滚本地置顶项。管理员批准后，该项会进入所有用户可见的公开画廊。
- 右侧“画廊灵感”的公开图仍先按 prompt 使用次数排序，再按页面加载时生成的随机权重排序；用户本地添加的生成图在公开图之前。空状态快捷 prompt 仍只展示 prompt，不展示用户生成图。
- 画图页空状态标题是“今天你想创造什么?”。标题下方展示 `gallery-ui-seed.json` 中有 prompt 的前 8 条快捷 prompt，点击后直接写入 composer 并聚焦输入框，不跳转。
- 画图页 composer 在 `web/src/app/image/page.tsx` 中实现，结构接近 ChatGPT 输入栏：大圆角输入框，上方是 prompt textarea，下方是上传、画廊、1 到 10 张的张数快捷按钮和数字输入、状态提示和圆形发送按钮。上传图预览仍在输入框内显示，Enter 发送、Shift+Enter 换行。
- 画图页会保留带 `queueRequestId` 的 `queued`、`assigning_account` 和 `running` turn。另一个 `/image` 窗口加载历史后，会用 `web/src/lib/image-transfer-leases.ts` 的浏览器端租约接管最多 3 个网页传输，再通过 `GET /api/image-queue/me?request_id=...` 和 `GET /v1/responses/{response_id}` 恢复终态。这个 3 个上限只限制同一浏览器 profile 下的网页窗口或标签，不改变后端公共 API 队列上限。
- 没有 `queueRequestId` 的遗留 `queued`、`assigning_account`、`running` 和 `loading` 图片状态仍会被改成可重试错误态。带 `queueRequestId` 的 turn 只有在当前窗口拿到租约、后端队列和终态记录都找不到该 request、且本地请求开始超过短保护时间后，才会改成“未找回这个请求”。composer 旁的“重置”按钮仍可手动清掉旧请求状态。
- 画图页的聊天区图片按中间聊天栏宽度自适应。参考图在用户消息里使用 `object-contain`，结果图单张时占满聊天栏，多张时最多两列，避免右侧画廊栏显示时结果图被压得过小。
- 前端发送时会先按当前 key 的模型单价和张数算成本，默认单价是 `1K=2`、`2K=2`、`4K=8`。画图页模型按钮提供 `gpt-image-2`、`gpt-image-2-2K`、`gpt-image-2-4K`，默认模型是 `gpt-image-2`。
- 前端画图页向 `/v1/responses` 发送请求时，会把选中的公开模型放在 `tools[].model`，并把当前尺寸选择放在 `tools[].size`。配置保持自动时，prompt 里明确写到 `1K`、`2K`、`4K`、`1024`、`2048`、`4096` 或常见高分辨率词时，页面只用它推断显示和模型档位，`tools[].size` 仍保持 `auto`。
- 如果当前额度不够，发送按钮会禁用，并显示提示，位置在 `web/src/app/image/page.tsx:644` 和 `web/src/app/image/page.tsx:652`。
- 图片请求继续一次请求带 `n`。如果后端返回 `billing.remaining_quota`，前端会先就地刷新余额，再同步拉一次 `/api/quota`，位置在 `web/src/app/image/page.tsx:373` 和 `web/src/lib/api.ts:235`。
- 如果后端返回了 `copied_text` 或 `text_content`，画图页会把它保存到当前 turn，并在结果区渲染一个“可复制文本”卡片，入口在 `web/src/app/image/page.tsx`。没有图片但有文本时，当前 turn 会结束为成功态，图片占位改成错误态，composer 不再继续等待。
- 会话历史主存到后端 `/api/image-conversations`，读写入口仍在 `web/src/store/image-conversations.ts`。本地 `localforage` 继续作为缓存；第一次读取时会把旧本地会话上传到后端。新结构是会话级 `id/title/clientConversationId/createdAt` 加 `turns[]`，旧单轮记录读取时自动映射成一个 turn。
- 在已有会话内继续发送时，前端会追加新 turn，不覆盖旧结果；结果按 `conversationId + turnId` 回写，避免切换会话后写到当前可见会话。
