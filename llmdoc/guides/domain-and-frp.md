# domain-and-frp

`img.fkcodex.com` 当前主访问线路已经迁到 VPS 直部署：

- 域名入口是 `img.fkcodex.com`。
- 远端服务器宿主机 Nginx 接收 HTTPS 请求，并反代到 `127.0.0.1:3306`（配置在 `/etc/nginx/sites-available/img.fkcodex.com`，切流量只改这一行 `proxy_pass` 端口后 `nginx -t && nginx -s reload`）。
- 当前 live 容器是 `chatgpt2api-green-7188696`，镜像标签是 `chatgpt2api:7188696`（整 HEAD 构建，含账号统计口径修复 + 恢复账号池管理表格：查看/编辑/删除/批量），端口只绑定 `127.0.0.1:3306:80`。
- 回滚链（端口均保留、容器都在 `apps-interconnect`）：一级 `chatgpt2api-green-92129ec`（`chatgpt2api:92129ec`）在 `127.0.0.1:3305`；二级 `chatgpt2api-green-ecbb260`（`chatgpt2api:ecbb260`）在 `127.0.0.1:3304`；三级 `chatgpt2api`（`chatgpt2api:vps-20260614`）在 `127.0.0.1:3303`。
- 同一台 VPS 的 `apps-interconnect` Docker 内网里，live 容器 `chatgpt2api-green-7188696` 已加网络别名 `img`（且别名唯一）；同网容器（例如 `newapi-app`）应使用 `http://img` 访问站点，不走公网，也不加 `:3003`。
- 容器挂载 `/opt/chatgpt2api/data` 到 `/app/data`，只读挂载 `/opt/chatgpt2api/config.json` 到 `/app/config.json`。
- 生成图 URL 仍依赖 `CHATGPT2API_PUBLIC_BASE_URL=https://img.fkcodex.com`。

回滚路径：

- 首选回滚：把远端 Nginx upstream 从 `127.0.0.1:3304` 改回旧容器 `127.0.0.1:3303`，旧容器仍保留。
- 旧 FRP 链路仍保留为二级回滚路径。本机 FRP 配置在 WSL 路径 `/home/mci777/.config/chatgpt2api/frp/frpc.toml`，不要再使用旧 Windows 路径 `/mnt/x/rbg-frp`。
- 当前 `frpc` 容器挂载 `/home/mci777/.config/chatgpt2api/frp` 到 `/config`，命令是 `/frp/frpc -c /config/frpc.toml`。
- `frpc.toml` 的 `[img]` 把本机 `host.docker.internal:3003` 映射到远端 `23.80.83.15:3202`。
- 如需回滚公开入口到 FRP，把远端 Nginx upstream 改成 `127.0.0.1:3003`；远端 `127.0.0.1:3003` 当前由 socat 转到 FRPS `3202`。
- `frpc.toml` 的 `[clash_proxy]` 把本机 `host.docker.internal:10808` 映射到远端 `23.80.83.15:3208`；VPS 容器内代理记录使用 `172.20.0.1:3208` 访问这条 Clash 出口。

仓库里没有远端 Nginx、FRPS 和 VPS compose 的正式配置文件，所以改这条线路时要分开看：

- 仓库内：确认当前镜像是否包含已验证代码，必要时重新发布 `ghcr.io/dofastted/chatgpt2api:latest`。
- 服务器侧：确认域名证书、Nginx 反代、VPS 容器、Docker 网络和回滚 FRP 端口。

最小检查方法：

1. 本机先确认登录页和画图页能打开，入口来自 `services/api.py:278`。
2. 用普通密钥请求 `/auth/login`，预期角色是 `user`，接口在 `services/api.py:166`。
3. 用管理员密钥请求 `/auth/login`，预期角色是 `admin`。
4. 普通密钥访问 `/api/accounts` 应返回 `403`，限制在 `services/api.py:83` 和 `services/api.py:180`。
5. 普通密钥访问 `/api/quota` 应正常，位置在 `services/api.py:214`。
