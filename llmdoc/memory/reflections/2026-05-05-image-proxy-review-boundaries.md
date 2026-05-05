# 2026-05-05 image proxy review boundaries

## Context

- 这轮要收口的不是单点 bug，而是一串会把人带偏的误判：页面卡住、`low quality text render`、以及本机 Clash 代理瞬时失败被混成一类。
- 本轮稳定修复提交链已经固定为 `764ea86 fix: recover stuck image queue turns`、`6c26946 fix: disable image text render review`、`ef515b5 fix: retry transient proxy connect failures`。
- 后续文档要明确哪些结论已经稳定，避免下次排障又把后端文字质量审查、代理瞬时失败和账号质量问题混在一起。

## Stable facts

- 生图链路不允许恢复后端文字质量审查。无输入图时，prompt 直接按原文发给上游。
- 下载完成后不再做本地 `low quality text render` 复核。
- `low quality text render` 不再作为本地阻拦用户 prompt、丢弃结果、或改判失败的理由。
- `curl: (7) Failed to connect ... 10808` 先按本机 Clash 或代理瞬时连接失败处理，不先判成文字质量问题，也不先判成账号质量问题。
- 代码层面对这类代理瞬时错误应做短退避重试；前提是先确认代理链路本身还能通。
- 当前稳定发布目标是 `fork/main`。`origin/main` 和本地 `main` 已严重分叉，除非用户明确要求处理上游分叉，不要直接推或强推 `origin/main`。
- Git 操作继续用 Windows Git。遇到 Git 代理失败，只允许命令级一次性 `-c http.proxy= -c https.proxy=` 直连，不改全局配置。

## Diagnosis order

1. 先看队列和终态传播，确认是不是旧请求、丢失 ticket、或前端还在等一个已经结束的请求。
2. 再看本机代理连通性，确认 `127.0.0.1:10808` 是否只是瞬时失败。
3. 最后才看账号状态、套餐类型、额度和上游真实返回。

## What to avoid next time

- 不要因为日志里出现 `low quality text render` 就恢复本地文字审查逻辑。
- 不要把 `curl: (7) Failed to connect ... 10808` 直接解释成 prompt 有问题或账号坏了。
- 不要在未确认分叉状态时把本地 `main` 直接推到 `origin/main`。
- 不要为了临时 push/fetch 失败去改全局 Git 代理配置。

## Verification anchor

- `git log --oneline -3` 应能看到 `ef515b5`、`6c26946`、`764ea86` 这条稳定修复链。
- `git branch -vv` 的稳定发布分支应以 `fork/main` 为准，不以 `origin/main` 为准。
- 相关 llmdoc 页面要同时体现这三件事：不恢复后端文字质量审查、代理瞬时失败先测连通性再短退避重试、发布边界是 `fork/main`。
