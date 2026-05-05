# runtime-config

配置来源：

- 主配置类是 `services/config.py:15` 的 `AppSettings`。
- `auth_key`、`admin_auth_key`、`accounts_file`、`user_keys_file`、`proxies_file`、`sqlite_path`、`backup_dir`、`backup_max_bytes`、`backup_interval_minutes`、`tls_verify` 和图片迁移开关都在这里定义，见 `services/config.py`。

配置加载规则：

- `auth-key` 从环境变量 `CHATGPT2API_AUTH_KEY` 或 `config.json` 读取，见 `services/config.py:49`。
- `admin-auth-key` 从环境变量 `CHATGPT2API_ADMIN_AUTH_KEY` 或 `config.json` 读取，见 `services/config.py:54`。
- `tls-verify` 走布尔解析，见 `services/config.py:62`。
- SQLite 主库默认写到 `data/chatgpt2api.sqlite3`，可用 `CHATGPT2API_SQLITE_PATH` 或 `sqlite-path` 覆盖。
- `data/accounts.json`、`data/user_keys.json`、`data/redeem_codes.json`、`data/proxies.json`、`data/uploaded_images.json` 只作为对应 SQLite 文档为空时的首次导入来源。
- 用户 key 导入来源可用 `CHATGPT2API_USER_KEYS_FILE` 或 `user-keys-file` 覆盖，见 `services/config.py`。
- 代理导入来源可用 `CHATGPT2API_PROXIES_FILE` 或 `proxies-file` 覆盖。
- 本地备份目录默认是 `data/backups`；`CHATGPT2API_BACKUP_MAX_BYTES` 默认 `524288000`；`CHATGPT2API_BACKUP_INTERVAL_MINUTES=0` 表示关闭定时备份。
- `IMAGE_ENGINE` 只允许 `legacy` 或 `chat_image`，当前默认 `chat_image`。旧值只保留给手工回退，不作为主容器默认路线。
- `IMAGE_ROUTE_POLICY` 只允许 `plan_type`、`force_responses`、`force_images` 或 `legacy`，当前默认 `plan_type`。默认情况下无输入图走 Images 路线；Plus/Pro/Team 带输入图才走 Responses 路线。
- `IMAGE_DEV_PORT` 默认 `18201`，用于隔离迁移环境记录。
- `IMAGE_ENABLE_FREE_IMAGES_FALLBACK`、`IMAGE_ENABLE_RESPONSES_PRIMARY`、`IMAGE_LOG_REQUESTS` 都走布尔解析。
- `IMAGE_QUEUE_PER_USER_ACTIVE_LIMIT` 默认 `10`，限制单个 Bearer Token 的 `waiting + running`。
- `IMAGE_QUEUE_PER_USER_WAIT_LIMIT` 默认 `10`，限制单个 Bearer Token 的等待请求。
- `IMAGE_QUEUE_GLOBAL_WAIT_LIMIT` 默认 `2000`，限制全局等待请求。
- `IMAGE_QUEUE_GLOBAL_START_LIMIT` 默认 `60`，配合启动窗口限制生图启动速率。
- `IMAGE_QUEUE_GLOBAL_START_WINDOW_SECONDS` 默认 `60`。
- `IMAGE_GENERATION_MAX_ACCOUNT_ATTEMPTS` 默认 `4`，限制单次生图最多尝试多少个账号；超过后返回失败，避免某个提示词或上游异常让 Web 请求一直停在生成中。
- 主容器默认不需要在 `config.json` 里显式写 `image-engine` 或 `image-route-policy`；不写时就是 `chat_image` 加 `plan_type`。只有排障或临时回退时才改这些值。

样例文件：

- 仓库只提供最小化的 `config.example.json`，里面没有把 `user-keys-file` 写出来；实际运行时没配也会回退到 `data/user_keys.json`。
- 实际运行时要在根目录放 `config.json`，compose 会把它挂到容器内 `/app/config.json`，见 `docker-compose-local.yml:11`。
- 本机正式运行的 `config.json` 和 `data/` 应保留在 `X:/project/chatgpt2api` 主工作树。迁移 worktree 或 `data-migration/` 里的副本只能用于验证和人工比较。
- 上传原图仍保存在 `data/uploaded_images/`，元数据由 `services/uploaded_image_service.py` 写入 SQLite。合并旧数据时必须同时保留 JSON 记录和实际文件，让首次导入能找到它们。

端口与入口：

- 直接跑 `main.py` 时，默认用 `main.py:10` 的 `0.0.0.0:8000`，可用 `CHATGPT2API_PORT` 覆盖端口。
- 容器模式由 `Dockerfile:33` 覆盖成 `0.0.0.0:80`。
- 本地 compose 对外暴露 `3002`，默认 compose 对外暴露 `3000`，见 `docker-compose-local.yml:9` 与 `docker-compose.yml:7`。
- 本机当前主容器名固定为 `chatgpt2api`，镜像名是 `chatgpt2api:local`，来源见 `docker-compose-local.yml:5` 到 `docker-compose-local.yml:6`。

`tls_verify` 说明：

- 它同时影响账号刷新和图片生成请求，因为 `services/account_service.py` 和 `services/image_service.py` 都把它传给了 `curl_cffi.requests.Session`。
- 当前启用代理也在这两个位置传入 `curl_cffi.requests.Session`。没有启用代理时传入值为空，运行时直连上游。
