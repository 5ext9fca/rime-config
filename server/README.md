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

数据库及清单路径使用示例中的容器路径。客户端和服务端均读取各自的 `sync-manifest.json`；客户端请求的有效范围必须是服务端允许范围的子集。修改静态范围后同步两端清单并重建容器；动态词典扩展见下文。

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

部署后，在每台客户端将 `remote.json.example` 复制为 Git 忽略的 `remote.json`（保留已有本机文件），配置后执行 `python3 rime.py --init`，输入对应设备令牌。安装 ID 必须与服务端设备条目一致。具体步骤见 [启用多设备云同步](../README.md#3-启用多设备云同步)，冲突处理见 [用户指南](../README.md#处理配置冲突)。

## 设备、令牌与范围维护

设备由维护者手动注册，没有自动注册接口。新增设备使用其自己的 Rime installation_id 和独立令牌；迁移时先确认旧设备身份，撤销旧注册后验证旧令牌返回 401，保留历史快照及其他设备。撤销权限不会擦除已下载数据。

客户端通过 `POST /rime/v1/token/refresh` 轮换令牌。`settings.json` 的初始令牌作为注册根，日常有效令牌哈希保存在 SQLite；删除设备或更换初始令牌会使其派生身份失效。不要用初始令牌覆盖客户端已轮换的私有令牌。宽限与响应丢失恢复约定见 [令牌轮换](../PROJECT.md#令牌轮换与动态词典范围)。

`settings.json` 支持以下策略；旧配置未声明时，动态扩展与自动备份默认关闭：

```json
{
  "auto_expand_dictionaries": true,
  "max_dictionaries": 128,
  "backups": {
    "enabled": true,
    "interval_seconds": 86400,
    "retention_days": 30,
    "keep_minimum": 7
  }
}
```

启用动态扩展后，认证客户端可通过 `POST /rime/v1/scope/dictionaries` 为自身用户追加词典名；增量保存在 SQLite，不修改挂载清单，也不需要重建容器。客户端须重新拉取并确认完整范围后才执行原生全量同步。禁用词典或关闭扩展会阻止新扩展，已有数据保留。

个人配置文件授权仍由 `sync-manifest.json` 静态维护，第三方资源不能借此进入个人同步。客户端远端独有词典首次建库不改变服务端权限；服务端范围不足时不得先全量同步再遗漏上传。

修改设备、初始令牌、静态清单或策略前先生成完整备份并另存待修改文件；修改后执行：

```bash
docker compose config --quiet
docker compose up -d --force-recreate app backup
docker compose ps
```

单文件 bind mount 可能保留旧 inode，不能仅 restart。修改服务代码时使用 `docker compose up -d --build app backup`。两容器分别检查健康，不以 HTTP 健康代替备份服务健康。

## 维护与备份

`backup` 容器独立运行、无网络，与应用共用 `/data` 卷，每 60 秒检查策略；启用时默认每天备份。HTTP 请求和应用健康检查不触发备份。停用时设置 `backups.enabled=false` 并重建两容器，已有备份保留。

```bash
# 手动生成额外完整备份，仍遵守并发锁和保留策略
docker compose exec backup python -m server.backup_worker --once --force
# 检查备份进程心跳；退出码 0 表示健康
docker compose exec backup python -m server.backup_worker --health
docker compose logs --tail=20 backup
```

备份位于 `/data/backups/`。每套由 `auto-<编号>.sqlite3`、`.settings.json`、`.scope.json`、最后发布的 `.manifest.json` 组成。SQLite backup API 保证数据库副本一致性，完整性检查通过后发布；完成清单记录成员 SHA-256。设置含初始令牌，数据库含个人数据及轮换凭据哈希，文件权限均为 0600，不能公开或提交 Git。

只清理完成且成员哈希正确的套件，默认超过 30 天且不在最新 7 套内才删除。手工/升级备份、旧单文件备份及不完整或损坏套件保留。`/data/backup-worker.json` 记录检查及成功时间；中断租约最多 10 分钟后到期重试。备份失败不删除旧套件，不代表 HTTP 服务必然故障。

复制备份到宿主私有目录时，按同一完成清单复制整套文件并复核哈希，不只复制数据库。SQLite 中身份、动态范围、版本和状态必须整体恢复，不能仅恢复 `states` 表。当前不提供异机备份或恢复向导。

### 人工恢复

1. 在隔离目录先验证整套成员哈希、SQLite 完整性，以及对应设置、范围和轮换凭据能否恢复预期用户状态。
2. 停止客户端同步和服务端 app/backup，归档原数据卷及设置。按实际 `settings.json` 的数据库路径恢复，处理旧 WAL/SHM，保持容器 UID/GID 10001 所需权限；同时核对对应设置和范围。
3. 重建 app/backup，分别检查健康，再核对用户版本、配置、词典及认证。客户端发现服务端版本回退时应停止；先核对保留的数据，再归档旧基线并使用新状态目录恢复同步，不直接清空状态绕过保护。

不要在数据库写入时直接复制单独的主文件。`docker compose down` 保留数据卷；`down -v` 会删除个人数据，不用于常规维护。隔离副本恢复通过不能描述为生产灾难切换已经验证。

## 日志与运行检查

Gunicorn 应用日志位于 `/data/logs/rime-日期-编号.log`，每文件约 10 MiB，默认 30 天过期；Docker 外层启动日志限 3×10 MiB。查看最近运行记录：

```bash
docker compose ps
docker compose logs --tail=50 app backup
docker compose exec app sh -c 'tail -n 80 /data/logs/rime-*.log'
```

Gunicorn 使用绝对配置路径 `/app/server/gunicorn.conf.py`，避免工作目录切换前解析失败。自定义代码归档须允许 UID 10001 读取源码，不能把私有设置的 0600 权限规则套用到全部程序文件。运行位置以实际 checkout、Compose 项目及公共 Caddy 配置为准，不沿用历史机器的地址或容器状态。

## 部署验证

- 确认 app/backup 分别健康，公共站点原有路由可用，未认证接口返回 JSON 401 和 `private, no-store`。客户端使用正常 TLS 证书验证，不跳过校验。
- 正式设备同步后，核对 HTTPS 配置与 `config/` 及适用实际文件逐字节一致；null 删除项和仅前端资源分开检查。快照传输、原生合并导出及配置部署分别确认，服务 running 不能代替输入法可用性。
- 冲突、过期 CAS、响应丢失重试、离线恢复、删除传播、重复请求及用户隔离使用独立测试用户和合成数据验证；结束后撤销测试身份并验证 401，清理前备份，不改正式用户数据。
- 生成完整备份，在隔离副本检查恢复后版本、身份与动态词典范围。重建容器后确认数据持久化；不要为验证而删除生产卷。

实现约束及分层验证见 [PROJECT.md](../PROJECT.md#开发与验证)，各平台已有覆盖和未验证边界见 [能力与验证边界](../PROJECT.md#能力与验证边界)。运维结果存入私有记录，不把一次健康状态或历史测试计数写成所有部署的保证。
