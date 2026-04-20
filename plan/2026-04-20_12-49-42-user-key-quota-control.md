---
mode: plan
task: 用户 key 与次数额度控制
created_at: "2026-04-20T12:50:22+08:00"
complexity: complex
---

# Plan: 用户 key 与次数额度控制

## Goal
- 增加可批量生成的用户 key。
- 每个用户 key 都有独立可配的剩余次数。
- 图片生成时按模型倍率和张数扣点。
- 当前额度不足时，前端发送按钮不可点，后端请求也会被拒绝。
- 管理员能查看、批量创建、更新和停用用户 key。

## Scope
- In:
- 后端新增用户 key 数据模型、存储、鉴权与扣点逻辑。
- 管理员接口新增用户 key 的批量创建、列表、更新、删除或停用能力。
- 前端管理员页面新增用户 key 管理区。
- 前端画图页新增“本次将消耗多少次数”和“当前剩余额度是否足够”的判断。
- `/api/quota` 和登录会话信息扩展为能反映用户 key 剩余次数。
- Out:
- 不改账号池 `access_token` 的远端刷新逻辑。
- 不改图片生成上游协议。
- 不做多级角色系统，只保留现有 `admin` 和普通用户使用面。
- 不做充值、订单、支付。

## Assumptions / Dependencies
- 用户 key 和管理员 key、普通 key 分开存放，不复用现有 `auth_key` 配置位。
- 用户 key 存储方式沿用当前项目风格，落在 `data/` 下的新 JSON 文件，由服务层统一读写。
- 用户 key 只允许访问 `/auth/login`、`/auth/session`、`/api/quota`、`/v1/images/generations`。
- 现有普通 `auth_key` 仍可保留；新用户 key 是额外能力，不强制替换。
- 扣点公式：`cost = n * multiplier`，其中 `gpt-image-1 = 1`，`gpt-image-2 = 4`。
- 发送前禁用只做提示，真正的扣点与拦截以后端为准。

## Phases
1. 梳理现有鉴权与额度路径。
2. 设计用户 key 数据结构。
   建议至少包含：`key`、`label`、`quota`、`status`、`createdAt`、`updatedAt`、`lastUsedAt`。
3. 设计后端服务层。
   新增用户 key 读写、批量生成、更新次数、扣点、停用等方法。
4. 调整鉴权模型。
   在现有 `admin` 和 `user` 判断上，补一层用户 key 识别，并让会话接口能返回剩余次数。
5. 调整额度接口与图片接口。
   `/api/quota` 返回当前 key 自己的可用次数。
   `/v1/images/generations` 在进入账号池前先校验本次成本，成功通过后再扣点或预扣并结算。
6. 增加管理员接口。
   包括用户 key 列表、批量创建、更新额度、停用或删除。
7. 调整前端管理页。
   在现有管理页里增加用户 key 区块，支持批量生成和修改次数。
8. 调整画图页。
   根据当前模型和张数实时计算本次消耗；额度不足时按钮禁用并给出提示。
9. 做回归验证。
   覆盖管理员、普通 key、用户 key 三种路径，确认互不串线。

## Tests & Verification
- 管理员可批量创建多条用户 key。
- 新用户 key 登录成功，会话接口能返回角色和剩余次数。
- 用户 key 访问管理接口返回 `403`。
- 用户 key 访问 `/api/quota` 返回自己的剩余次数，而不是账号池总和。
- `gpt-image-1` 生成 `n=3` 时扣 `3`。
- `gpt-image-2` 生成 `n=2` 时扣 `8`。
- 剩余次数不足时，前端发送按钮禁用。
- 即使绕过前端，后端也会拒绝额度不足的请求。
- 多个用户 key 之间额度彼此独立。
- 管理员 key 和现有普通 key 现有能力不回退。
- `cd web && npm run build` 通过。
- 项目本地部署命令 `docker compose -f docker-compose-local.yml up -d --build` 通过。

## Issue CSV
- Path: issues/2026-04-20_12-49-42-user-key-quota-control.csv
- Must share the same timestamp and slug as this plan.

## Tools / MCP
- `feedback:codebase_retrieval`，用于找鉴权、额度、管理页现有模式。
- `functions:exec_command`，用于读取文档、查看文件、跑构建和部署命令。
- `functions:apply_patch`，用于后续代码修改。

## Acceptance Checklist
- [ ] 管理员可以批量生成用户 key。
- [ ] 用户 key 可配置初始次数。
- [ ] 用户 key 的权限一致且不可进入后台管理。
- [ ] 生成扣点按模型倍率和张数计算。
- [ ] 额度不足时前端发送按钮不可点。
- [ ] 额度不足时后端请求也会被拒绝。
- [ ] 管理员可以查看和调整用户 key 次数。
- [ ] 现有管理员 key 和普通 key 不回退。
- [ ] 构建与本地部署检查通过。

## Risks / Blockers
- 现有 `/api/quota` 语义是“账号池总额度”，引入用户 key 后要改成“按当前 key 返回”，会影响现有前端和接口文档。
- 如果继续保留原 `auth_key`，需要明确它是否也受新次数规则影响，否则会出现两套普通使用路径。
- 扣点时机如果定义不清，容易出现前端显示和后端实际扣点不一致。
- 管理员页当前只有账号池管理，直接塞入用户 key 管理会让页面更长，需要先定好布局。

## Rollback / Recovery
- 用户 key 相关能力独立在新数据文件和新接口上，出问题时可先关闭用户 key 入口，不影响账号池画图主链路。
- 若前端管理区影响过大，可先保留后端接口和画图限制，暂时隐藏管理 UI。
- 若扣点规则争议较大，可先只做后端校验和额度展示，暂时不做前端禁用。

## Checkpoints
- Commit after: 用户 key 数据模型与服务层完成。
- Commit after: 鉴权、额度接口、图片扣点逻辑完成。
- Commit after: 管理页与画图页联动完成。
- Commit after: 构建与部署验证完成。

## References
- `llmdoc/must/auth-and-roles.md`
- `llmdoc/architecture/backend-api.md`
- `llmdoc/architecture/frontend-routing-and-auth.md`
- `llmdoc/reference/http-endpoints.md`
- `llmdoc/reference/runtime-config.md`
- `llmdoc/architecture/account-pool-and-refresh.md`
- `web/src/lib/api.ts`
- `llmdoc/overview/project-overview.md`
