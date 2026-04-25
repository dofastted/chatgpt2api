# 2026-04-25 main worktree and data handoff

## Context

- Chat image migration was first completed in `X:/project/chatgpt2api-chat-image-worktree`.
- The user clarified that `X:/project/chatgpt2api` must remain the local `main` working tree; the migration worktree must not keep `main` checked out.
- Before switching `X:/project/chatgpt2api`, its uncommitted and untracked state was backed up under `/mnt/x/project/chatgpt2api-runtime-backups/current-repo-before-main-20260425-215519`.

## Lesson

- Do not leave `main` checked out in a temporary worktree after local rollout. Move the temporary worktree to an archive branch first, then switch the primary repo to `main`.
- Do not replace a larger runtime `data/` directory with a smaller migration copy. Compare counts first, merge JSON records and uploaded files, then restart the container.
- `acc/`, `.llmdoc-tmp/`, and `config.json` are local or sensitive runtime files. They must stay ignored and must not be committed.

## Promoted facts

- Current local main repo is `X:/project/chatgpt2api`, branch `main`, commit `daff82e`.
- The running local container is `chatgpt2api:local` on host port `3002`.
- The running local container mounts `X:/project/chatgpt2api/data` to `/app/data` and `X:/project/chatgpt2api/config.json` to `/app/config.json`.
- The temporary migration worktree now uses branch `archive/chat-image-main-20260425`.
