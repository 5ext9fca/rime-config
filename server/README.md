# Rime 同步服务部署指南

在公网 VPS 上部署个人配置与词典快照同步服务，通过现有公共 Caddy 提供 HTTPS。需要 Docker Compose 和可用的 HTTPS 站点，Caddy 与本服务共享 Docker 网络。第三方词典由客户端直接刷新。

客户端使用见 [用户指南](../README.md)，架构、协议和开发验证见 [PROJECT.md](../PROJECT.md)。

## VPS 部署

在 VPS checkout 中操作。镜像构建需要访问 Python 镜像及 PyPI；不包含个人配置、词典和令牌。

```bash
cd server
cp settings.example.json settings.json
cp .env.example .env
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
```

将生成的随机令牌填入 `settings.json`，为每台设备配置独立条目：

- `user`：同一用户的所有设备使用相同值，不同用户数据完全分开。
- `device`：该设备 Rime `installation.yaml` 的 `installation_id`，也与客户端私有配置中的 `installation_id` 一致。同一用户内不能重复设备 ID。
- `token`：至少 32 字符的独立随机令牌；示例占位符被拒绝。令牌通过 Authorization 请求头传送，不放在 URL。

数据库及清单路径使用示例中的容器路径。客户端和服务端均读取各自的 `sync-manifest.json`；客户端请求的有效范围必须是服务端允许范围的子集。修改范围后同步两端清单，避免 403 或范围不一致。

应用以 UID/GID 10001 运行。Compose 命名卷持久化 `/data`；设置文件只读挂载：

```bash
sudo chown 10001:10001 settings.json
sudo chmod 600 settings.json
# 如果公共入口尚未创建该网络，仅首次创建；已有网络直接复用。
docker network inspect caddy-public >/dev/null 2>&1 || docker network create caddy-public

docker compose config --quiet
docker compose build app
docker compose run --rm --no-deps app python -c 'from server.app import create_app; create_app(); print("Configuration OK")'
docker compose up -d
docker compose ps
docker compose logs --tail=50 app
```

`.env` 的 `CADDY_NETWORK` 默认 `caddy-public`，必须与公共 Caddy 一致。根文件系统只读；仅 `/data` 和 `/tmp` 可写，移除所有 capabilities。健康检查访问内部 `/healthz` 并读取 SQLite；不访问用户词典或上游。


## 公网 Caddy 路由

把本目录 [`rime.caddy`](rime.caddy) 的内容加入公共 Caddy 的**现有 HTTPS 站点块**，或在站点块中 import 该文件，然后通过公共入口项目既有方式校验并重载：

```caddyfile
handle /rime/* {
    request_body {
        max_size 16MB
    }
    reverse_proxy rime-sync:8080
}
```

保留 `/rime/` 前缀，不使用 `handle_path`。不要新增另一个占用 80/443 的代理容器。网络与转发方式参见 [Docker external network 文档](https://docs.docker.com/reference/compose-file/networks/#external) 和 [Caddy reverse_proxy 文档](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy)。现有公共站点应已经配置有效 TLS 证书；客户端强制 HTTPS、验证证书且拒绝重定向，不使用跳过证书校验的方式。

公网地址：`https://<公网域名或已配置证书的IP>/rime/v1/state`。未带令牌的 GET 应返回 JSON 401，而不是其他业务页面。服务关闭 Gunicorn access log，返回 `Cache-Control: private, no-store`；公共代理不要记录 Authorization 或请求/响应内容，不为该接口启用公共缓存。


## 客户端连接

部署后，在每台客户端配置 `remote.json` 并执行 `python3 client/sync.py --init`，输入对应设备令牌。安装 ID 必须与服务端设备条目一致。具体步骤见 [启用多设备云同步](../README.md#启用多设备云同步)，冲突处理见 [用户指南](../README.md#遇到配置冲突)。

## 维护与备份

修改令牌、清单或设置后执行 `docker compose up -d --force-recreate app`。单文件 bind mount 可能保留旧 inode，不能只 restart。修改服务代码后执行 `docker compose up -d --build`。删除或更换某设备令牌可以撤销该设备后续读写权限，已下载的数据不会被远程擦除。

使用 SQLite backup API 制作一致备份，再复制到 VPS 的私有备份目录：

```bash
docker compose exec app python -c 'import sqlite3; s=sqlite3.connect("/data/rime.sqlite3"); d=sqlite3.connect("/data/backup.sqlite3"); s.backup(d); d.close(); s.close()'
docker compose cp app:/data/backup.sqlite3 ./backup.sqlite3
chmod 600 backup.sqlite3
```

恢复前停止应用并归档整个原卷，将备份数据库恢复到 `/data/rime.sqlite3`，处理旧 WAL/SHM 文件并保持 UID/GID 10001；重新启动后先验证版本及数据。不要在数据库写入中直接复制单独的主文件。`docker compose down` 保留数据卷；不要使用 `down -v` 删除个人数据。数据卷和备份包含个人词条及配置，应使用 VPS 的私有备份设施。


## 部署验证

确认容器健康、无令牌请求返回 JSON 401，再使用客户端执行一次同步并检查另一台设备能否接收。配置应用后需重新部署输入法；个人词典快照接收后需由 Rime 原生同步导入。

2026-11-10 已在 `proxy_jp` 完成真实 Docker/Caddy/HTTPS 部署验收，并接入 Windows 后台客户端。服务地址为 `https://198.13.57.54:8443/rime/v1/state`，未发布应用宿主机端口；Windows 后续已接入原生 `/sync` 自动合并和导出。全量原生模式会补齐客户端词典清单，若出现新名称，应同步更新服务端 `sync-manifest.json` 并重建容器，范围未对齐时客户端停止原生处理与回传。自动测试方法与边界见 [开发与验证](../PROJECT.md#开发与验证)，详细结果见 [公网部署与同步验收](../PROJECT.md#公网部署与同步验收)。

当前实例的维护位置：

- Compose：`/home/hx/rime-config/server`；容器：`rime-config-app-1`；数据卷：`rime-config_data`。
- 公共入口：`/home/hx/MyProxyCaddy/conf/routes/rime.caddy`，由既有 HTTPS 站点导入，网络为 `caddy-public`。
- 私有设置：`server/settings.json`，属主 `10001:10001`、权限 `0600`，仅保留正式设备。
- 验收备份：`server/backups/accepted-20261110.sqlite3`，权限 `0600`；使用 SQLite backup API 生成并通过完整性检查。这是一次性验收备份，尚未配置定期备份任务。

部署时发现并修复 Gunicorn 配置路径问题：`--config` 使用 `/app/server/gunicorn.conf.py`，避免在 `--chdir` 生效前解析相对路径失败。若通过自定义归档部署，请确保镜像内代码可由 UID 10001 读取；不要将私有设置的 `0600` 权限规则套用到全部程序源码。
