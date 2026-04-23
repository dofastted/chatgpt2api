# local-run

本地起服务优先用 `docker-compose-local.yml`，因为这个文件会本地构建当前代码，而不是拉远端镜像，定义见 `docker-compose-local.yml:3`。

最短路径：

1. 以 `config.example.json:2` 到 `config.example.json:4` 为样例，在仓库根目录准备 `config.json`。
2. 至少设置一把普通密钥；如果要进号池管理，再单独设置管理员密钥，读取规则见 `services/config.py:49` 到 `services/config.py:55`。
3. 启动 `docker compose -f docker-compose-local.yml up -d --build`。
4. 打开 `http://127.0.0.1:3002/login`。

运行后会得到：

- 前端静态站点由同一个 FastAPI 进程提供，见 `services/api.py:278`。
- 账号数据写到宿主机 `./data/accounts.json`，见 `docker-compose-local.yml:10` 和 `services/config.py:72`。
- 本地容器会带 `restart: unless-stopped`，也就是 Docker daemon 自己恢复后会自动拉起当前服务，定义见 `docker-compose-local.yml:3`。

检查点：

- 普通密钥登录后应该进入 `/image`，规则见 `web/src/app/login/page.tsx:30`。
- 管理员密钥登录后应该进入 `/accounts`，规则也在 `web/src/app/login/page.tsx:30`。
- 普通密钥访问号池管理页时应被挡回 `/image`，见 `web/src/app/accounts/page.tsx:269`。
- 如果要确认当前实例已经带上自启动，可在宿主机执行 `docker inspect chatgpt2api --format '{{.HostConfig.RestartPolicy.Name}}'`，期望值是 `unless-stopped`。
