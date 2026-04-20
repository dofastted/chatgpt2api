# runtime-config

配置来源：

- 主配置类是 `services/config.py:15` 的 `AppSettings`。
- `auth_key`、`admin_auth_key`、`accounts_file`、`tls_verify` 都在这里定义，见 `services/config.py:16` 到 `services/config.py:21`。

配置加载规则：

- `auth-key` 从环境变量 `CHATGPT2API_AUTH_KEY` 或 `config.json` 读取，见 `services/config.py:49`。
- `admin-auth-key` 从环境变量 `CHATGPT2API_ADMIN_AUTH_KEY` 或 `config.json` 读取，见 `services/config.py:54`。
- `tls-verify` 走布尔解析，见 `services/config.py:62`。
- 账号文件固定写到 `data/accounts.json`，见 `services/config.py:72`。

样例文件：

- 仓库只提供 `config.example.json`，字段见 `config.example.json:2` 到 `config.example.json:4`。
- 实际运行时要在根目录放 `config.json`，compose 会把它挂到容器内 `/app/config.json`，见 `docker-compose-local.yml:11`。

端口与入口：

- 直接跑 `main.py` 时，默认用 `services/config.py:70` 和 `main.py:10` 的 `0.0.0.0:8000`。
- 容器模式由 `Dockerfile:33` 覆盖成 `0.0.0.0:80`。
- 本地 compose 对外暴露 `3002`，默认 compose 对外暴露 `3000`，见 `docker-compose-local.yml:9` 与 `docker-compose.yml:7`。

`tls_verify` 说明：

- 它同时影响账号刷新和图片生成请求，因为 `services/account_service.py:364` 和 `services/image_service.py:92` 都把它传给了 `curl_cffi.requests.Session`。
