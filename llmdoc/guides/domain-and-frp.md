# domain-and-frp

这个仓库外还有一条已知访问线路：

- 域名入口是 `img.fkcodex.com`。
- 远端服务器是 Nginx 接收 HTTPS 请求，再转给 FRP 服务端。
- 本机 FRP 客户端把流量送到本地 `docker-compose-local.yml:9` 暴露的 `3002`。

仓库里没有 Nginx 和 FRP 配置文件，所以改这条线路时要分开看：

- 仓库内：确认本机服务是否真的在 `3002` 正常响应。
- 服务器侧：确认域名证书、Nginx 反代、FRPS 端口都还指向本机 FRPC。

最小检查方法：

1. 本机先确认登录页和画图页能打开，入口来自 `services/api.py:278`。
2. 用普通密钥请求 `/auth/login`，预期角色是 `user`，接口在 `services/api.py:166`。
3. 用管理员密钥请求 `/auth/login`，预期角色是 `admin`。
4. 普通密钥访问 `/api/accounts` 应返回 `403`，限制在 `services/api.py:83` 和 `services/api.py:180`。
5. 普通密钥访问 `/api/quota` 应正常，位置在 `services/api.py:214`。
