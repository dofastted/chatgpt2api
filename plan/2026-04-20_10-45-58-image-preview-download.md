---
mode: plan
task: 图片预览与下载增强
created_at: "2026-04-20T10:46:33+08:00"
complexity: medium
---

# Plan: 图片预览与下载增强

## Goal
- 在画图页中，用户点击已生成图片后可进入大图预览。
- 预览层内可查看当前会话的其他成功图片，并能前后切换。
- 用户可直接下载当前预览图片，移动端和桌面端都能正常使用。

## Scope
- In:
- `web/src/app/image/page.tsx` 增加图片预览状态、交互入口和下载按钮。
- 复用现有 `Dialog` 组件做大图预览层。
- 补充前端辅助方法，例如从 `b64_json` 生成下载文件。
- 验证现有历史会话、本地存储、生成流程不被影响。
- Out:
- 不改后端接口。
- 不改账号池、鉴权、额度逻辑。
- 不新增服务端文件落盘或下载接口。
- 不处理图片编辑能力。

## Assumptions / Dependencies
- 当前图片结果仍然是 `b64_json`，来源保持不变。
- 画图页会继续从本地会话历史读取图片数据。
- 仓库已有 `Dialog` 组件可直接用于预览层。
- 仓库已有下载文件写法可直接参考，不需要新依赖。

## Phases
1. 读清当前画图页的图片结果渲染方式，确认成功图片列表、当前会话数据和可插入的交互点。
2. 设计预览状态模型。
   例如当前会话成功图片数组、当前预览索引、打开和关闭行为、切换边界。
3. 在画图页接入点击放大。
   只给成功图片加可点击态和预览入口，保留失败态、加载态现有表现。
4. 接入预览层。
   复用现有 `Dialog` 组件，显示当前图片、当前序号、关闭按钮、前后切换按钮。
5. 接入下载功能。
   基于当前预览图片的 base64 数据生成下载链接，文件名带上时间或会话信息。
6. 做样式与交互收尾。
   处理移动端布局、按钮禁用态、空数据保护、键盘切换和滚动体验。
7. 做回归验证。
   检查生成流程、历史切换、删除会话、清空历史、刷新页面后的展示是否正常。

## Tests & Verification
- 点击成功图片 -> 打开预览层并显示对应大图。
- 预览上一张和下一张 -> 正确切换同一会话中的成功图片。
- 首张和末张 -> 切换按钮禁用或隐藏符合预期。
- 点击下载 -> 浏览器成功下载当前图片文件。
- 当前会话含失败图或加载图 -> 不影响成功图预览和切换。
- 刷新页面后重新进入历史会话 -> 仍可预览和下载。
- `cd web && npm run lint` -> 无新增 lint 错误。
- `cd web && npm run build` -> 前端可构建通过。

## Issue CSV
- Path: issues/2026-04-20_10-45-58-image-preview-download.csv
- Must share the same timestamp and slug as this plan.

## Tools / MCP
- `feedback:codebase_retrieval`，用于找画图页、会话存储、现有下载模式。
- `functions:exec_command`，用于读取模板、查看相关文件、跑 lint 和 build。
- `functions:apply_patch`，用于后续改动前端文件。

## Acceptance Checklist
- [ ] 成功图片支持点击放大。
- [ ] 预览层可在当前会话的成功图片间切换。
- [ ] 预览层提供下载当前图片功能。
- [ ] 失败图和加载图不会误触发预览。
- [ ] 历史会话、本地存储、额度显示、生成流程保持原样。
- [ ] 桌面端和移动端都能正常操作。
- [ ] `lint` 和 `build` 通过。

## Risks / Blockers
- base64 图片体积较大，预览层切换时可能有明显卡顿。
- 当前瀑布流展示是按全部图片渲染，预览层需要只取成功图并保持索引映射清楚。
- `next/image` 加 `data:` URL 在弹层中的尺寸控制要小心，避免拉伸和布局抖动。

## Rollback / Recovery
- 预览和下载只放在前端单页中实现，若效果不合适，可直接回退 `web/src/app/image/page.tsx` 的交互代码。
- 若预览层影响主流程，可先保留下载功能，临时移除弹层入口。

## Checkpoints
- Commit after: 预览状态与弹层接入完成。
- Commit after: 下载功能与交互收尾完成。
- Commit after: lint 和 build 验证完成。

## References
- `web/src/app/image/page.tsx:86`
- `web/src/app/image/page.tsx:232`
- `web/src/app/image/page.tsx:469`
- `web/src/store/image-conversations.ts:7`
- `web/src/store/image-conversations.ts:57`
- `web/src/components/ui/dialog.tsx:7`
- `web/src/app/accounts/page.tsx:144`
- `llmdoc/architecture/frontend-routing-and-auth.md`
- `llmdoc/architecture/image-generation-flow.md`
