# runtime-config

配置来源：

- 主配置类是 `services/config.py:15` 的 `AppSettings`。
- `auth_key`、`admin_auth_key`、`accounts_file`、`user_keys_file`、`proxies_file`、`tls_verify` 和图片迁移开关都在这里定义，见 `services/config.py`。

配置加载规则：

- `auth-key` 从环境变量 `CHATGPT2API_AUTH_KEY` 或 `config.json` 读取，见 `services/config.py:49`。
- `admin-auth-key` 从环境变量 `CHATGPT2API_ADMIN_AUTH_KEY` 或 `config.json` 读取，见 `services/config.py:54`。
- `tls-verify` 走布尔解析，见 `services/config.py:62`。
- 账号文件默认写到 `data/accounts.json`，也可用 `CHATGPT2API_DATA_DIR` 改整组数据目录。
- 用户 key 文件默认写到 `data/user_keys.json`，也可用 `CHATGPT2API_USER_KEYS_FILE` 或 `user-keys-file` 覆盖，见 `services/config.py:75`。
- 代理文件默认写到 `data/proxies.json`，也可用 `CHATGPT2API_PROXIES_FILE` 或 `proxies-file` 覆盖。
- `IMAGE_ENGINE` 只允许 `legacy` 或 `chat_image`，当前默认 `chat_image`。旧值只保留给手工回退，不作为主容器默认路线。
- `IMAGE_ROUTE_POLICY` 只允许 `plan_type`、`force_responses`、`force_images` 或 `legacy`，当前默认 `plan_type`。默认情况下 Free 账号走 Images 路线，Plus/Pro/Team 走 Responses 路线。
- `IMAGE_DEV_PORT` 默认 `18201`，用于隔离迁移环境记录。
- `IMAGE_ENABLE_FREE_IMAGES_FALLBACK`、`IMAGE_ENABLE_RESPONSES_PRIMARY`、`IMAGE_LOG_REQUESTS` 都走布尔解析。

样例文件：

- 仓库只提供最小化的 `config.example.json`，里面没有把 `user-keys-file` 写出来；实际运行时没配也会回退到 `data/user_keys.json`。
- 实际运行时要在根目录放 `config.json`，compose 会把它挂到容器内 `/app/config.json`，见 `docker-compose-local.yml:11`。

端口与入口：

- 直接跑 `main.py` 时，默认用 `main.py:10` 的 `0.0.0.0:8000`，可用 `CHATGPT2API_PORT` 覆盖端口。
- 容器模式由 `Dockerfile:33` 覆盖成 `0.0.0.0:80`。
- 本地 compose 对外暴露 `3002`，默认 compose 对外暴露 `3000`，见 `docker-compose-local.yml:9` 与 `docker-compose.yml:7`。

`tls_verify` 说明：

- 它同时影响账号刷新和图片生成请求，因为 `services/account_service.py` 和 `services/image_service.py` 都把它传给了 `curl_cffi.requests.Session`。
- 当前启用代理也在这两个位置传入 `curl_cffi.requests.Session`。没有启用代理时传入值为空，运行时直连上游。
