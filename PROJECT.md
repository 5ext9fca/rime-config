# 项目技术说明

本文定义实现约束、协议、平台差异与验证要求。日常安装和操作见 [README](README.md)，服务端部署维护见 [服务端指南](server/README.md)，协作规则见 [AGENTS.md](AGENTS.md)。验收记录中的稳定结论归入对应约束；时间、PID、服务端版本、测试计数和临时证据路径不作为长期规范，历史过程可查 Git 历史及各设备私有记录。

阅读入口：[配置与数据边界](#代码与数据边界)、[合并与恢复](#合并删除与恢复)、[原生同步](#原生全量同步)、[平台约束](#原生维护与桌面会话约束)、[输入行为](#配置资源与输入行为约束)、[验证要求](#开发与验证)。

## 能力与验证边界

支持 Windows 原生、macOS 和原生 Linux；不支持 WSL，不实现异机备份、自动新设备注册或恢复向导。已实现按文件三方合并、HTTPS 配置及快照交换、内置原生维护、第三方词典刷新和用户后台服务。实现存在不等于任意前端或设备都已通过验证。

| 平台或组件 | 已有验证覆盖 | 不得据此推导的结论 |
| --- | --- | --- |
| Windows 小狼毫 | 当前用户任务、新入口、HTTPS、原生 `/sync`、自动部署与 IPC 恢复；用户确认 PiliPlus 短按和长按切换正常 | 新入口重新登录触发来源及图标视觉结果尚未单独完成验证；DLL 引擎测试不代替应用 UI |
| macOS 鼠须管 | HTTPS、内置全量合并、自动部署、失败输出隔离与恢复、新入口；用户确认 UI 和登录启动 | 自定义包装器或其他鼠须管版本需独立验证 |
| Ubuntu Fcitx5 | 配置、原生全量维护、HTTPS、systemd 生命周期及真实登录触发；用户确认 UI | 不推广到 IBus 或其他 Linux 前端 |
| Fedora KDE Fcitx5 | 配置、原生全量维护及 HTTPS；启动竞争修复后用户确认中文输入恢复 | 修复后的整机重启、注销再登录与事件式空闲监听恢复尚未验证 |
| 公网服务端 | TLS/鉴权、CAS、隔离客户端合并、响应丢失重试、完整备份与隔离恢复 | 隔离双客户端不等于两台真实设备；隔离恢复不等于生产灾难切换 |

以上边界汇总已有记录，不表示当前机器实时健康，也不表示本次文档整理重新运行了这些验证。新版本更改相关路径时，按[开发与验证](#开发与验证)重新取得对应层次的证据，不沿用旧运行状态。

## 代码与数据边界

| 位置 | 职责 |
| --- | --- |
| `rime.py`、`client/cli.py` | 入口与参数解析；执行交给 application 层 |
| `client/application/runtime.py`、`workflow.py` | 初始化、周期循环与工作流编排 |
| `client/core/configuration.py`、`plans.py` | 配置应用、备份与版本化计划契约 |
| `client/config/paths.py` | 跨平台目录发现与私有路径记忆 |
| `client/services/service.py` | 跨平台服务入口，systemd / launchd 用户服务管理 |
| `client/platforms/windows/windows_service.py`、`client/platforms/windows/windows_service.ps1` | Windows 当前用户计划任务的注册、查询、卸载与恢复 |
| `client/platforms/windows/windows_runner.py` | pythonw 后台入口与 UTF-8 日志 |
| `client/storage/file_lock.py`、`client/platforms/windows/windows_security.py` | 跨进程文件锁及 Windows 私有文件 ACL |
| `client/config/identity.py` | 安装 ID 与设备令牌初始化 |
| `client/core/scope.py` | 个人配置及词典范围校验 |
| `client/application/cloud_sync.py` | 云同步事务、版本提交、响应丢失恢复与冲突留存 |
| `client/core/merge.py`、`client/transport/` | 纯三方比较、HTTPS 传输和协议编解码 |
| `client/application/dictionaries.py` | 原生个人词典快照交换与应用钩子 |
| `client/maintenance/native_sync.py`、`client/platforms/windows/weasel_sync.py` | 跨平台全量范围补齐、完成凭据、Windows 原生 /sync 与恢复检查 |
| `client/providers/third_party.py` | 第三方词典下载、校验与刷新 |
| `server/app.py`、`credentials.py`、`database.py`、`scopes.py` | WSGI 接口、设备鉴权、SQLite 持久化与授权范围 |
| `server/backups.py`、`backup_worker.py` | 完整备份套件、保留策略及独立调度 |
| `tests/` | 临时目录、模拟上游及客户端/服务端集成测试 |

配置流向为：服务端与 `config/` 合并 → 更新 `config/` → 按清单应用到实际目录。实际目录不是配置编辑源。自动学习数据则从 Rime 原生快照采集，经服务端或共享目录交换，再交由 Rime 合并。第三方词典从上游直接更新实际目录，不进入个人数据服务端。

`config/` 中留存的第三方文件不代表它们全部受管理；个人范围以 `sync-manifest.json` 为准，第三方刷新范围以 `third-party.json` 为准。

## 实际配置目录的发现与记忆

首次搜索规则位于 [`paths.json`](paths.json)，本机选择保存在私有 `paths.local.json`（Unix 0600、Windows 受保护 ACL；Git 忽略，不进入镜像或同步）。不需要先配置设备令牌：

```bash
# 发现并记住实际 Rime 目录；不联网、不应用文件、不要求令牌
python3 rime.py --discover-target
# 只预览，不写记忆文件
python3 rime.py --discover-target --dry-run
# 明确选择并记住一个现有目录
python3 rime.py --discover-target --target /实际/Rime/目录
# 忽略旧记忆及 device.local.json 内旧路径，重新按项目候选路径搜索
python3 rime.py --discover-target --rediscover-target
```

目录选择优先级为：`--target` → 当前平台的路径记忆 → `device.local.json` 的 `target` → `paths.json` 候选路径。正常运行和成功初始化也会记住选择，`--dry-run` 始终不写记忆。此后直接运行 `--watch` 即可复用。显式 `--target` 会成为后续默认目标；使用临时目录验证时可同时指定临时 `--paths-state`。

`paths.json` 按 `windows`、`macos`、`linux` 配置候选目录列表；旧三平台配置兼容补入 Windows 默认候选。所有候选都必须是展开后的绝对路径，不递归扫描。模板支持 `{home}`、`{xdg_config_home}`、`{xdg_data_home}` 和 `{windows_appdata}`，也支持 `~`；Windows 直接读取 APPDATA。例如：

```json
{
  "version": 1,
  "required_files": ["installation.yaml"],
  "candidates": {
    "windows": ["{windows_appdata}/Rime"],
    "macos": ["{home}/Library/Rime"],
    "linux": ["{xdg_config_home}/fcitx5/rime", "{xdg_config_home}/ibus/rime"]
  }
}
```

自动发现要求目录存在，并包含 `required_files` 中的所有文件；可调整标记清单，空列表表示只检查目录。WSL 环境明确拒绝运行。多个有效候选不会按顺序盲选，必须用 `--target` 消除歧义；完全没找到时提示修改候选配置。

已记住的目录或身份配置目录失效时直接报错，不悄悄切换到其他输入法，也不自动创建原路径。持续模式每轮重新检查目标目录是否仍存在，但不会运行中切换目标；修改路径后重启服务。显式指定的目标也必须已存在，且所有路径拒绝符号链接。

`--paths-config FILE` 选择另一份发现规则；`--paths-state FILE` 选择另一份私有记忆文件，默认是设备配置同目录的 `paths.local.json`。记忆按平台分别保存，不含令牌，不应放入 `config/` 或实际 Rime 目录。多份设备身份需要独立路径记忆时显式指定不同 `--paths-state`。

## 初始化本机配置

首次使用运行：

```bash
# macOS 通常可直接自动检测
python3 rime.py --init
# Ubuntu 按实际输入法选择目标目录
python3 rime.py --init --target ~/.config/fcitx5/rime
```

初始化读取目标 `installation.yaml` 的 `installation_id`，以隐藏输入方式接收**已在服务端配置的设备令牌**，保存项目根目录的 `device.local.json`：

```json
{
  "version": 1,
  "installation_id": "本机的 Rime 安装 ID",
  "token": "服务端为该设备分配的令牌",
  "target": "/实际/Rime/用户目录"
}
```

该文件已通过 `*.local.json` 加入 Git 忽略规则，也不进入 Docker 构建或个人数据同步。初始化以 Unix `0600` 权限或 Windows 受保护 ACL 原子写入，不输出令牌；不会联网验证令牌、自动注册设备、修改 Rime 的安装 ID 或自动开启 `remote.json`。服务端设备配置中的 ID 和令牌必须与此文件一致。

之后运行 `python3 rime.py --watch` 即可自动读取安装 ID、令牌和目标目录，无需重复传 `--device-id` 或设置令牌环境变量。`--target` 可覆盖目标路径并更新独立路径记忆；路径变化后应重启持续服务。身份文件每轮重新读取，令牌轮换可重新运行 `--init`；交互输入留空保留已有令牌。安装 ID 变化时必须提供新设备的令牌。

没有 Rime 安装文件时可以用 `--init --device-id ID --target PATH` 显式提供；若实际文件中存在不同的 ID 则拒绝初始化。非交互环境支持 `--init --token-stdin` 从标准输入读取一行令牌，例如从私有文件重定向：

```bash
python3 rime.py --init --token-stdin --target /实际/Rime/目录 < /私有路径/device-token
```

不要把真实令牌写入命令参数。可用 `--device-config /path/to/another.local.json` 选择另一份私有配置；不要把它放入 `config/`。手动指定的 `--device-id` 必须与已加载的身份文件一致。旧 `remote.json` 的 `token_env` 仍兼容，在没有私有文件令牌时读取；私有文件中的令牌优先。

## 个人配置与词典的范围配置

[`sync-manifest.json`](sync-manifest.json) 的版本为 `1`，结构如下（文件内为实际完整清单）：

```json
{
  "version": 1,
  "configuration": {
    "enabled": true,
    "files": ["default.custom.yaml", "weasel.custom.yaml", "rime_ice.custom.yaml", "custom_phrase.txt"]
  },
  "dictionaries": {
    "enabled": true,
    "names": ["luna_pinyin", "rime_ice"]
  }
}
```

- `configuration.files`：个人配置、自定义短语和手工词库的明确相对路径，相对于 `config/`，原路径应用到 Rime 目录。
- `dictionaries.names`：自动学习词典的名称，不带 `.userdb` 或 `.userdb.txt` 后缀；只接收、发布这些词典的快照，并只向原生应用命令传递这些名称。`luna_pinyin` 用于现有词典，`rime_ice` 用于雾凇拼音。
- 两部分的 `enabled` 分别控制该类数据是否参与处理；列表为空同样表示不处理。禁用或缩小范围均保留已有目标文件、快照和状态，不主动删除数据。
- 清单每轮重新加载，不需要重启持续服务。使用 `--sync-config /path/to/sync-manifest.json` 可指定其他项目范围文件。路径不支持通配符；重复项、越界路径、数据库路径及不支持的版本会报错。
- 该范围同时约束服务端拉取/合并/回传、本地配置应用、个人词典快照接收/发布与应用命令。服务端也挂载清单，拒绝超出服务端范围的更新。

范围由项目文件决定；`--target`、`--dictionary-store`、`--device-id` 等参数仍用于指定本机目录和连接信息，不能扩大清单。未启用远端同步且未提供交换目录时会明确提示并跳过词典操作。第三方刷新继续由 `third-party.json` 独立控制；即使个人配置暂时禁用，其声明文件也仍受第三方覆盖冲突检查保护。

原生应用命令必须含 `{dictionary}` 占位符，例如：

```bash
python3 rime.py --dictionary-store /path/to/private-store --device-id DEVICE_ID \
  --native-sync-command '["/absolute/path/to/native-sync-wrapper", "--dictionary", "{dictionary}"]'
```

客户端逐个替换名称并执行；包装程序须只合并/导出所指定词典，并等待完成。旧式不带占位符的全量同步命令会被拒绝。客户端无法限制外部程序忽略参数或用户手动执行 Rime 全量同步；包装程序的按词典处理能力需在各端验证。

## 文件、备份与失败处理

- 对全部路径进行预检查，再逐文件原子替换；内容相同则跳过，采用复制而非链接。
- 仅删除此前管理、仍列在 `sync-manifest.json` 中但已从 `config/` 删除的文件。从清单移除路径表示解除管理，保留目标副本，因此升级后不会误删此前管理的第三方依赖。首次应用不删除额外文件；所选源文件全部缺失时拒绝应用。
- 拒绝符号链接、路径类型冲突和源/目标/状态目录重叠；不管理 `build/`、`sync/`、`*.userdb*`、`installation.yaml`、`user.yaml` 和 `.gram` 文件。
- 每次修改前，将所有受影响的已有目标文件备份至 `~/.local/state/rime-config/<目标路径标识>/backups/<会话>/files/`，并写入 `journal.json`。备份包含个人配置；仅符合下文完成凭据及保留策略的备份可自动清理。
- 同一状态目录通过文件锁阻止并发写入；同一目标应始终使用同一状态目录。可用 `--state-dir /绝对路径` 覆盖默认目录，不应删除或跨目标复用管理清单。
- 捕获到应用异常时恢复本次已经完成的文件操作。断电或强制终止不保证整体回滚；保留备份和记录，检查后重新应用即可收敛到仓库配置。回滚失败会报错，备份仍保留。
- 手工恢复时先停止持续同步，将会话 `files/` 内需要的文件复制回目标；若希望长期保留这些内容，应同时修改 `config/`。`journal.json` 中 `create` 项对应此前不存在的文件。
- 配置或个人词典同步遇到错误时退出，由服务管理器重试。第三方下载/校验/应用失败单独记录：持续模式按项目配置的重试间隔重试，不停止正常轮询；单次执行返回非零状态。第三方项目配置本身无效时直接报错退出。

## 合并、删除与恢复

1. 客户端拉取服务端状态及版本。首次同步，单边存在的配置自动复制；双方同名配置内容不同则报告冲突。
2. 后续比较上次成功基线、本地 `config/` 与远端配置。只在一边修改或两边内容相同的文件自动合并；同一文件出现两种修改时保留冲突，不自动拼接 YAML。
3. 在 Rime 同步目录接收其他设备的词典快照；全量入口按独立限频和空闲条件执行一次，未到期记录 deferred 并保留待合并快照。已验证导出的快照可继续传输；原生失败后的输出停止发布，直到重试验证成功。兼容旧逐词典钩子；无原生入口时仅交换快照，仍需手动触发。
4. 将配置增量和**本设备**快照连同 `base_revision` 提交。并发导致版本变化时返回 409，下一轮重新拉取合并；不会盲目覆盖。
5. 提交成功后将配置合并结果备份并写入 `config/`，记录基线，再由现有 apply 流程应用到实际目录。同步途中 `config/` 又被编辑时保留编辑并报错，不覆盖它。

冲突文件保存在 `<state-dir>/remote/conflicts.json`（Base64 保存 base/local/remote 原始内容），不会输出个人内容到日志。检查后可编辑本地配置为选定的远端内容，或显式选择本轮**所有冲突文件**保留哪一侧：

```bash
python3 rime.py --resolve-conflicts local
python3 rime.py --resolve-conflicts remote
```

该选项仅解决配置文件冲突，不强行覆盖词典分叉。若希望合并冲突文件内容，先在 `config/` 手工合并，再使用 `--resolve-conflicts local`。`remote` 选择会备份并覆盖本地冲突文件。保留冲突记录以便追溯。

配置删除用持久化的 `null` 删除标记表达。只有已经同步且仍在范围内的文件被本地删除时才会上传删除；从范围清单移除只是解除管理。原生词典不提供删除接口；取消选择不会清空词典。服务端范围收窄会隐藏原数据，重新启用后仍可读取。

每个设备只能更新自己名下的快照。重复提交相同内容不增加版本，不累加词频。发生同设备 ID 的词典分叉时停止并保留双方，不能将两台机器配置为同一个 ID。服务端有本机快照但本地快照缺失时会恢复到本机同步目录，数据库导入仍须原生合并。

`remote/baseline.json` 记录服务端成功版本、配置合并基线和词典处理模式（`snapshots-only`、兼容逐词典的 `native-command` 或全量 `native-all`）；它不代表 Rime 配置已重新部署。实际配置应用结果由原有 `manifest.json`/备份日志记录。网络中断、版本冲突或上传响应丢失都可重试；本地尚未上传的修改不丢弃。数据库恢复导致服务端版本回退时客户端停止，先核对数据再归档客户端旧基线、使用新状态目录重新同步，不自动重置版本。

## API

全部业务请求使用 `Authorization: Bearer <device-token>`。用户和设备身份由服务端令牌配置决定，不接受请求体伪造身份。

- `GET /rime/v1/state`：返回 `revision`、`user`、`device`、服务端 `scope`、`configuration` 和 `dictionaries`。
- `PATCH /rime/v1/state`：提交 `base_revision`、`configuration` 增量、`dictionaries` 本设备增量。所有更改在一个 SQLite 事务中校验并写入。
- 配置为 `{"相对路径": "Base64 UTF-8 内容或 null"}`，其中 null 为 JSON 值而非字符串。
- PATCH 词典为 `{"词典名": "Base64 原生快照"}`；GET 词典外层再按设备 ID 分组。服务端校验快照词典名称和 `/user_id`，拒绝超范围文件。
- 默认请求上限 16 MiB、每用户总状态上限 64 MiB。需要调整时同时修改服务端设置及 Caddy 请求限制；客户端响应上限为 80 MiB。
- 401：令牌无效；403：超出范围；409：版本冲突；413：超限；503：存储不可用。错误响应不返回词典内容或凭据。

## 连接、状态与服务端运行模型

仓库模板为 `remote.json.example`，保持禁用和占位地址；首次复制为 Git 忽略的本机 `remote.json`。客户端默认路径和已有服务参数仍指向 `remote.json`。Docker 构建上下文只允许模板，测试镜像将模板复制为 `/app/remote.json`，不打包本机连接设置。不得将本机 remote.json 打包为公开模板。

`remote.json` 配置 HTTPS 地址、同步间隔、失败重试及请求超时，每轮重新读取。私有身份令牌优先于兼容的 `token_env` 环境变量。客户端验证证书、拒绝重定向；身份来自 Bearer 令牌，不从请求体接受用户或设备身份。

默认状态目录为 `~/.local/state/rime-config/<目标路径标识>/`，可由 `--state-dir` 指定。同一目标必须保持同一状态目录，避免绕过文件锁和管理历史。状态与备份包含个人数据，不应提交 Git。

| 相对状态目录的路径 | 内容 |
| --- | --- |
| `manifest.json`、`backups/` | 本地配置应用记录和旧文件 |
| `remote/baseline.json` | 成功同步的版本、配置及词典基线 |
| `remote/pending.json` | 上传结果不确定时的待确认提交，用于响应丢失恢复 |
| `remote/conflicts.json` | 配置冲突的 base/local/remote 内容 |
| `dictionaries/backups/` | 被替换的原生词典快照 |
| `third-party/receipt.json`、`schedule.json`、`backups/` | 上游版本、调度与刷新备份 |

启用远端与 `--dictionary-store` 互斥。远端失败或冲突时跳过该轮个人配置应用，第三方刷新按独立周期继续处理。`--sync-now` 和显式冲突选边仅作用于首轮。`--dry-run` 不联网、不执行原生命令、不写状态。

服务端由 Gunicorn 托管标准库 WSGI 应用，SQLite WAL 保存每用户版本、配置与各设备快照，以事务检查提交版本。同用户共享配置，每台设备仅能写自己的快照；重复提交相同内容不增加版本。服务端不自行累加词频。

Compose 使用外部 Caddy 网络，容器别名 `rime-sync`、内部端口 8080，无宿主机端口映射。应用以 UID/GID 10001 运行，根文件系统只读，移除 capabilities，启用 no-new-privileges；仅数据卷和临时目录可写。设置和范围清单只读挂载。内部 `/healthz` 检查数据库可读性。业务响应禁止公共缓存，Gunicorn 不记录 access log。

镜像只包含客户端/服务端代码及运行依赖，不包含个人配置、词典或私有身份。测试阶段额外复制测试和项目规则文件；构建范围由 `.dockerignore` 限制。

## 第三方词典刷新（雾凇拼音）

行为由项目根目录 [`third-party.json`](third-party.json) 决定，持续模式每轮重新读取。默认从 [雾凇拼音官方仓库](https://github.com/iDvel/rime-ice) 的 `main` 刷新 17 个中文、英文、中英混输及拆字词库文件。

| 配置项 | 默认值 | 含义 |
| --- | --- | --- |
| `enabled` | `true` | 总开关；强制刷新也不会绕过禁用设置 |
| `interval_seconds` | `86400` | 成功检查后的刷新间隔，默认每天一次 |
| `retry_seconds` | `900` | 失败后重试间隔，默认 15 分钟 |
| `timeout_seconds` | `30` | 单次网络请求超时秒数 |
| `max_download_bytes` | `134217728` | 本次词典文件总大小上限，默认 128 MiB |
| `source.repository` | `iDvel/rime-ice` | GitHub 上游仓库（owner/repo） |
| `source.ref` | `main` | 分支、标签或完整提交 SHA |
| `source.files` | 显式文件清单 | 上游相对路径，同时也是实际 Rime 目录内的目标路径 |

首次运行立即刷新，后续按持久化计划执行；项目配置变化会立即触发新的检查。仅支持 GitHub 公共仓库，经 HTTPS 下载；沿用 Python 的标准代理环境变量及系统证书校验。API 限流、断网或下载失败进入重试，不要求 Git 或第三方 Python 包。

```bash
# 查看计划；不联网、不创建状态、不写目标
python3 rime.py --third-party-only --dry-run
# 立即刷新，不等待下次周期（仍遵守 enabled）
python3 rime.py --third-party-only --refresh-third-party
# 正常后台运行时，自动按项目配置周期刷新
python3 rime.py --watch
# 可指定另一份项目配置
python3 rime.py --third-party-only --third-party-config /path/to/third-party.json
```

以上命令同样支持 `--target`、`--state-dir`；Ubuntu 的目标目录有歧义时必须指定。`--refresh-third-party` 在持续模式下仅强制首轮，之后恢复配置周期。单次正常执行未到周期时跳过刷新。

刷新先将分支/标签解析为具体提交，从该提交的 Git tree 读取清单、文件大小及 blob SHA，再下载同一提交下的全部指定文件。检查大小、Git blob 哈希、UTF-8 文本及基本词典头格式后，在状态目录暂存；全部成功后才写目标。哈希用来验证与该上游提交的一致性，不等同于发布者签名；词典头检查也不代替 Rime 部署验证。

覆盖前备份旧文件，目标文件逐个原子替换，捕获到文件应用失败时回滚已完成项。记录位于 `<state-dir>/third-party/`：`receipt.json` 保存成功提交与文件 SHA-256，`schedule.json` 保存下次尝试时间，`backups/` 保存旧文件和操作记录。内容相同不会重复覆盖或备份。没有整目录替换、没有删除传播；从刷新清单移除文件表示停止管理，保留目标副本。断电或强制终止不保证整批回滚；备份和记录保留，可检查后强制刷新以重新应用完整版本。

清单只允许 `.dict.yaml` 和词典 `.txt`，拒绝与个人配置清单重叠、个人短语、用户数据库、符号链接及越界路径。默认不刷新 `rime_ice.dict.yaml`、`melt_eng.dict.yaml` 入口文件，以保留其中可能存在的个人 `import_tables`；也不刷新 `.schema.yaml`、Lua、OpenCC 和语言模型。请先在客户端安装完整雾凇方案，并自行维护词典入口与上游的兼容性。第三方词典直接应用到实际目录，不回写 `config/`，不进入个人数据服务端同步。

刷新后必须重新部署才能加载新词典。启用自动部署时，由独立部署阶段按资源指纹、空闲条件和完成凭据执行；禁用时需用户手动部署。下载或哈希校验成功不能代替部署成功。

## 自动学习个人词典

本工具从 Rime 原生生成的 `<sync_dir>/<installation_id>/*.userdb.txt` 中仅交换项目清单内词典，保留词条、词频和元数据。每台设备只发布自己的快照，接收其他设备的快照；不传播文件删除，不直接操作正在使用的 `*.userdb` 数据库。词典合并由 Rime 完成，参见 [Rime 同步说明](https://github.com/rime/home/wiki/UserGuide#同步用戶資料) 和 [原生快照恢复/合并实现](https://github.com/rime/librime/blob/master/src/rime/lever/user_dict_manager.cc)。

启用方法：

1. 查看本机 `installation.yaml` 中的 `installation_id`。每台设备必须唯一，不能克隆同一 ID。本工具不改写该文件。
2. 在 Rime 菜单中执行“同步用户资料”，等待完成，以生成本机快照。
3. 指定私有交换目录和本机 ID，运行服务：

```bash
python3 rime.py --watch --interval 10 \
  --target /实际/Rime/目录 \
  --device-id 本机安装ID \
  --dictionary-store /path/to/private-rime-dictionaries
```

以上为可选的共享目录模式：各端使用同一个共享目录，或由独立云盘同步其内容。公网 VPS 模式请启用 `remote.json`，不要同时传入 `--dictionary-store`。只允许同步快照文件，不同步原生 `sync/` 目录中附带备份的配置或第三方文件。可在仓库内用 `private/dictionaries/` 作为本地暂存目录，`private/` 已被 Git 忽略；不同设备的本地暂存目录不会自动联网互通。

默认原生同步目录为目标下的 `sync/`；若 `installation.yaml` 设置了 `sync_dir`，须用 `--rime-sync-dir` 指向实际目录。`--device-id` 须与本机快照中的 `/user_id` 一致，程序会检查收到的快照设备标识及词典名。

接收远端快照后，再执行 Rime 的“同步用户资料”，由 Rime 合并到本机数据库并导出最新快照；服务下一轮发布它。日常新学习的数据也需先由 Rime 导出，服务不会扫描活动数据库。既未启用远端同步也未提供 `--dictionary-store` 时仅应用配置；未生成快照时会提示，不会声称词典已导入。

新部署采用下节的原生全量入口。旧 `--native-sync-command '["/absolute/path/to/native-sync-wrapper", "--dictionary", "{dictionary}"]'` 保留兼容，仍须只处理指定词典、等待完成后退出，不能把 `/sync` 填入这个逐词典接口。执行顺序仍为接收快照 → 原生合并/导出 → 发布本机快照；失败不发布，dry-run 不执行原生命令。

词典快照在覆盖前备份至状态目录下 `dictionaries/backups/`，写入采用原子替换。交换不作整批回滚，失败可重试，已完成文件保持有效；不会删除快照或清空词条。服务锁仅协调本程序，不能锁住 Rime 或云盘；应等待原生同步完成后交换。修改中的快照会报错，请重试。所有快照和备份均含个人数据，使用私有存储。

按 [用户指南](README.md#5-后台运行) 执行 `--service install` 时传入同样的原生参数，即可启用后台合并与交换。内置入口与自定义包装器的验证范围必须分别记录，不能把独立 dict-manager 验收脚本当作生产同步包装器。

## 原生全量同步

Windows 与 Unix 使用平台原生全量同步语义。新部署可用 `--native-sync-builtin`；显式 Windows 入口为 `--weasel-deployer /绝对路径/WeaselDeployer.exe`，Unix 自定义入口为 `--native-sync-all-command`；各全量入口与兼容的逐词典命令互斥，服务安装器会保留入口及 `--native-sync-config` 参数。全量调用仅在独立维护调度到期后执行一次，不为每个词典或每轮云轮询重复执行 `/sync`。

### 独立维护调度

原生维护不得绑定每轮云同步。由根目录 `native-sync.json` 控制，默认最小维护间隔 900 秒、失败重试间隔 900 秒、空闲阈值 30 秒、兜底导出间隔 3600 秒，每轮重新读取。

- `native-all/schedule.json` 在原生调用前持久化尝试时间和输出隔离标记，成功后保存完成时间及变化指纹。进程重启、云同步失败重试和 `--sync-now` 都不清除限频。旧状态从 `latest.json` 的完成时间迁移，不因升级立即追加维护。
- 指纹包含活跃数据库文件的路径、大小、修改时间以及各设备快照的内容哈希；不读取或复制活动数据库。没变化则跳过。输入法可能尚有内存中的学习数据，因此一小时到期后仍安排导出，但不会绕过最小间隔或空闲门槛。
- Windows 使用 `GetLastInputInfo` 检查当前会话键鼠空闲时间。30 秒是输入活动门槛，不是对应用未提交预编辑内容的检测。Unix 内置入口使用平台 IdleProvider，自定义包装器按传入阈值判断会话空闲；不假定跨桌面通用 API。
- 接收的新快照保存在原生同步目录，变化指纹一直保留待处理信号，直到成功原生处理后更新。等待期间配置同步及既有安全快照传输继续。原生调用失败当轮停止提交；随后限频等待的云轮次可处理配置，但不发布失败/中断留下的词典输出。
- `native-all/application.json` 及远端基线中的 `dictionary_application` 记录 `status`（success/deferred/unchanged/failed）、原因和 `last_success_at`。`latest.json` 保留实际原生调用结果；模式为 `native-all` 本身不能证明本轮已导入。

### 范围与失败处理

- `native_sync.py` 每轮扫描实际目录中的用户数据库名称和原生 `sync/` 下所有设备的 `*.userdb.txt`。校验元数据及路径，拒绝重解析路径、大小写冲突和残留 `.temp.userdb` 等异常数据库。
- 把发现的词典名追加到 `sync-manifest.json`，先备份旧清单；不删除已有名称，不强制开启被禁用的词典同步，dry-run 仅显示计划。清单在扫描期间变化时停止，避免覆盖并发编辑。
- HTTPS 请求先确认服务端允许完整范围，再接收快照和执行原生命令；服务端缺项时报告具体名称并停止，需维护者对齐服务端清单后重建容器。若服务端明确启用按用户动态词典扩展，客户端可按下文 API 申请追加并重新 GET 核对；不能自行扩大静态配置范围。
- 调用前后再次检查范围；运行期间出现新词典时补齐清单并停止本轮上传。内置全量同步须先安全初始化清单内远端独有词典，再执行前端全量同步；自定义包装器未处理的新名称仍报告尚未导入，不把复制成功计为合并成功。
- 调用前保留已有本机快照；Windows 另备份原生会覆盖的同步目录 YAML/TXT 副本。不会复制活动 LevelDB 文件，也不把快照备份描述为全部活动数据库的精确回滚镜像。部分原生合并后失败时保留数据，由原生合并语义支持重试，不手动覆盖数据库。
- 原生命令失败、超时、完成凭据缺失或范围变化时不上传本轮快照，不推进原生成功记录。原生结果单独写入状态目录 `native-all/runs/<本轮ID>/result.json` 和 `native-all/latest.json`；HTTPS 成功版本仍由 `remote/baseline.json` 记录，配置应用由原有配置状态记录。
- `/sync` 附带备份的配置文件留在原生同步目录，不扩大 `configuration.files`，不上传第三方资源。每轮原生快照备份和结果保留在私有状态目录，历史备份仅按下文的完成凭据及保留策略清理。

### Windows 入口与完成判定

`weasel_sync.py` 验证传入目标与小狼毫注册用户目录、安装 ID、原生 `sync_dir` 一致。使用已安装 librime 的只读 YAML 接口读取 `sync_dir`，不改写安装身份。已存在 `WeaselDeployerMutex` 时延后执行，避免与部署程序争用。

运行 `WeaselDeployer.exe /sync`，最多等待 180 秒；小狼毫负责进入维护模式、执行安装检查/配置备份/全量用户词典合并与导出、退出维护。进程退出后必须同时满足：

1. 退出码为 0；本次 PID、时间对应的 INFO 日志唯一。
2. 日志包含 `3 tasks ran: 3 success, 0 failure`，处理词典集合与预检查完全一致，且无 ERROR 行。
3. 所有本机词典快照均已更新且元数据有效。
4. 经 IPC 创建空输入会话、Echo 校验并立即释放成功，确认输入服务可用；不输入文字、不操控 UI。

小狼毫构建可能不记录维护恢复的 INFO 行，恢复必须由独立 IPC 探测确认。失败/超时后先确保本次子进程结束，再尝试有界的恢复维护请求；其他部署程序持有互斥体时不抢占。恢复未确认会记录失败，保留数据重试。已有实机覆盖小狼毫 0.17.4 / librime 1.13.1；其他构建若改变任务或日志格式，会停止并要求适配，不降低成功判据。

### Unix 全量包装器约定

公共同步流程对 Unix 采用相同的范围补齐、先拉取、全量合并导出、再回传规则。平台包装器须通过输入法自身的原生接口处理并发，等待真实完成，不应直接打开输入法正在使用的数据库。不能把仅发出 D-Bus/进程通知的异步命令当作成功包装器；也不假定每个平台都有名为 `/sync` 的相同命令行选项。

执行时通过环境变量提供 `RIME_USER_DIR`、`RIME_SYNC_DIR`、`RIME_INSTALLATION_ID`、`RIME_SYNC_DICTIONARIES`（本机数据库名 JSON 数组）、`RIME_SYNC_IDLE_SECONDS`（空闲阈值）和本轮唯一的 `RIME_SYNC_RECEIPT` 路径。包装器须先检查会话空闲；不满足时不得触发原生命令，写入 `{"status":"deferred"}` 并以 0 退出。完成全部任务后写入 UTF-8 JSON：

```json
{"status": "success", "names": ["luna_pinyin", "rime_ice"]}
```

`names` 必须与本轮全部本机数据库一致；成功凭据应依据原生完成事件或任务结果产生，不能只根据旧快照存在就写成功。包装器非零退出、超过 240 秒或缺少本轮凭据都会停止上传。自定义包装器须独立验证；Fcitx5 与鼠须管内置入口遵守[原生维护与桌面会话约束](#原生维护与桌面会话约束)中的平台完成判据。

## 远端独有词典首次落地

`dictionary_bootstrap.ensure` 仅在内置全量维护已通过空闲判断后执行；Windows 在既有原生调度准许后执行。名称必须来自已验证、已授权且在本轮范围内的快照，已存在数据库不进入初始化。实际目录下创建 `.rime-bootstrap-*` 私有隔离目录，仅写入本机 installation_id 与经过校验的快照副本，不复制活动数据库。Unix 调用原生 rime_dict_manager restore/backup；Windows 在独立 Python 子进程通过已安装 librime 的版本化 levers API 完成相同步骤。先验证导出元数据、关闭原生进程并同步文件，再原子移入不存在的目标路径；Linux renameat2(RENAME_NOREPLACE)、macOS renamex_np(RENAME_EXCL)、Windows 不覆盖的 rename，绝不降级为先检查再覆盖。macOS 标志依据官方 [sys/stdio.h](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/sys/stdio.h)。

初始化凭据只记录名称、输入 SHA-256、已发布名称和状态，不记录词条。失败或中断后，原有 native unsafe/重试机制禁止发布未经确认的快照；已完成的库不重新初始化，下一轮由 Rime 原生合并补齐其余快照。未知或不支持的文件系统原子移动失败时保留源快照，不覆盖目标。硬中断留下的隔离目录不自动删除，避免误删未知恢复材料。

FullNativeSync 对内置入口及 Weasel 将远端独有名称纳入本轮完成范围；初始化后仍须真实前端全量同步成功、范围重新校验及全部本机导出存在才记录 success。仅交换快照模式及自定义原生包装器不自动初始化。范围清单仍是授权边界，服务端有其他名称并不代表客户端自动导入；同名基础方案或资源也不会随此功能安装。

## 令牌轮换与动态词典范围

- `POST /rime/v1/token/refresh` 接收客户端生成的随机令牌；SQLite `credentials` 保存注册初始令牌哈希、当前/前一令牌哈希和 24 小时宽限截止时间。注册配置继续决定有效设备，删除设备或改变初始令牌立即使旧派生身份失效（设置修改需重建容器）。旧令牌过期后不能读写数据，只能携带相同新令牌重试已完成的轮换；旧令牌不能再派生另一令牌。宽限期间拒绝再次轮换，避免丢失响应的客户端被连续轮换锁死。
- 客户端 `token/rotation.json` 在请求前保存候选令牌，以文件锁串行化，服务确认后原子更新私有身份，再清除候选并记录完成时间。响应丢失、身份写入中断均可恢复；候选文件同样按私有凭据保护，不入 Git 或日志。首次启用会轮换一次，随后默认每 30 天。
- `POST /rime/v1/scope/dictionaries` 仅允许认证设备为自身用户追加个人词典名称，验证路径、大小写碰撞及数量上限。服务端 `auto_expand_dictionaries` 默认兼容旧配置为 false，示例开启，部署值以私有设置为准；`max_dictionaries` 默认 128。增量存入 `dictionary_scopes`，GET 返回静态范围与本用户增量的并集；禁用词典时拒绝扩展。客户端扩展成功后重新 GET 校验，再执行原生处理和上传。不会扩展配置文件清单或第三方资源权限。

## 备份与日志保留

受管理专用日志按日及大小分段，默认 30 天过期、10 MiB 换文件，只清理自身命名范围。服务端应用日志位于 `/data/logs/`，Docker 外层日志限制 3×10 MiB。旧版外层文件、系统 journal 和其他应用日志不由此清理；状态、冲突、待确认提交及快照不能按日志策略删除。服务包装器自身 stdout/stderr 的处理见下文，不能与专用日志轮转混同。

客户端 `backup_retention.py` 只处理明确列出的状态子目录，以写入方成功发布的 `.completed/<备份名>.json` 为主要完成凭据，兼容旧配置/第三方 applied 日志及原生 success 结果。配置、远端、快照交换、第三方、主题、原生运行与清单备份分组保留，默认 30 天、每组至少 7 份、每天一次。清理取得对应写入锁后重新观察；busy、路径异常、符号链接/重解析路径及无法确认完成的备份均不删除。远端 pending/error 状态保护相关备份，原生 unsafe/failed/running 状态保护原生组；最新原生运行单独保护。根状态、基线、冲突、凭据及实际/交换目录不在删除范围。状态目录只保存清理报告与下次执行时间；预览不写入。旧策略文件缺少 backups 字段时默认禁用，项目配置显式启用。

服务端 `backup_worker.py` 由独立 Compose `backup` 容器运行（无网络、只读根目录、去除 capabilities）。每 60 秒检查调度；HTTP 状态接口及健康检查不再执行备份。应用与备份容器共享数据卷，注册配置及范围清单只读挂载；修改 bind mount 设置需同时重建两容器。数据库文件锁防止并发备份，SQLite 维护表保存成功时间和 10 分钟中断租约；原生备份过程最长 300 秒。首次切换到完整备份格式会立即生成一套，不被旧数据库单文件备份的间隔阻挡。

每套 `auto-<编号>` 包含 `.sqlite3`、`.settings.json`、`.scope.json` 及最后发布的 `.manifest.json`。数据库通过 SQLite backup API 复制，随后 integrity_check；配置读取前后校验未变，所有成员权限 0600，SHA-256 写入完成清单。只有完成且成员哈希匹配的套件才参与保留计数和删除；默认 30 天且至少最近 7 套。旧单文件自动备份、手工备份、升级归档及不完整/损坏套件保留，不以它们凑足最低可用备份数。备份失败保留旧套件、释放租约并记录独立失败心跳，不影响 HTTP 健康。进程中断后文件锁自动释放，租约到期后恢复。心跳在 `/data/backup-worker.json`，不包含凭据或词条。

隔离测试覆盖年龄＋最低份数、只读预览、写入锁冲突、待确认远端保护、最新/失败原生保护、符号链接拒绝、格式迁移、备份失败重试、并发/中断租约和套件清理。恢复验证只在隔离目录打开副本并通过应用接口核对轮换令牌、用户版本和动态词典范围，不覆盖生产数据库，不构成恢复向导或生产灾难切换演练。

## 自动系统服务注册

入口为 `rime.py --service install|uninstall|status`，实现集中在 `client/services/service.py`。操作用户级服务，不申请系统管理员权限。Windows 原生走当前用户计划任务分支；Ubuntu 走 Linux systemd 分支；macOS 走 launchd 分支。

- Windows：`client/platforms/windows/windows_service.py` 将 JSON 载荷编码后交给 `windows_service.ps1`，通过 ScheduledTasks 注册 `rime-config-<当前用户 SID>`。Interactive 登录类型、Limited 权限、该用户登录触发，无需密码或令牌进入任务定义。采用 IgnoreNew、无执行时限、电池供电继续运行、失败每分钟重试（最多 999 次），并增加每分钟重复触发器，补偿实机中 RestartOnFailure 未触发的情况；运行中忽略新触发。原生 `pythonw.exe` 直接运行 `windows_runner.py`，在同一任务进程运行客户端并捕获 UTF-8 日志，停止任务即停止客户端。安装先离线预检查，更新前导出旧 XML；失败恢复旧定义与原运行状态，新安装失败删除新任务；无管理标记的任务拒绝覆盖及卸载。查询和卸载不依赖项目同步配置。预览不访问任务计划程序。
- Windows 日志为 `%LOCALAPPDATA%\rime-config\logs\service.log`；启动时若超过 10 MiB 保留一个 `.1` 文件，运行中不轮转。计划任务是登录会话内的自动运行机制，不是 SCM 系统服务，用户未登录时不运行。安装成功不等于同步已成功。
- Windows 原生路径通过 `%APPDATA%\Rime` 发现；旧三平台 `paths.json` 兼容补入此默认候选。旧 WSL 路径记忆不再使用。所有客户端 JSON 读取显式使用 UTF-8，清单继续使用 `/` 分隔；拒绝 Windows 设备名、备用数据流、尾随空格/点和目录联接等重解析路径。
- 跨进程锁集中在 `file_lock.py`：Unix 使用 `flock`，Windows 使用 `msvcrt.locking` 非阻塞锁定第 0 字节，文件句柄关闭即释放。四条写入流程均使用此锁。不允许多个不共享锁机制的进程同时管理同一实际目录或状态目录。
- 原子替换的临时文件在写入数据前设置 Windows 受保护 DACL（所有者、SYSTEM、管理员），失败停止写入；Unix 保持 mkstemp 的 0600。Windows `chmod(0600)` 本身不提供等价 ACL 安全性。备份目录等应存放在用户私有目录，未对已有文件做全目录 ACL 迁移。
- systemd：服务名 `rime-config.service`，写入 `$XDG_CONFIG_HOME/systemd/user/`（默认 `~/.config/systemd/user/`）。执行 daemon-reload、enable 和 restart。采用 `Restart=on-failure`、10 秒重试及 `UMask=0077`，禁用启动次数限制以支持长时间离线恢复。
- launchd：标签 `local.rime-config`，写入 `~/Library/LaunchAgents/local.rime-config.plist`。在 `gui/<uid>` 域执行 enable/bootstrap，更新时先 bootout。采用 RunAtLoad、非零退出重启、10 秒节流及私有 umask。日志位于 `~/Library/Logs/rime-config/`，不自动轮转。
- 使用当前 Python 的绝对路径和 `-u`，工作目录固定为项目目录，目标目录固定为安装时解析出的实际目录。只转存明确允许的持续运行参数；初始化、强制刷新及冲突选边等一次性动作不能与服务安装混用。
- 启动参数中的文件路径在安装时转为绝对路径。systemd 参数处理引号、反斜杠、`%` 和 `$` 的转义并拒绝控制字符；launchd 使用 `plistlib` 编码参数数组，不经过 shell。
- 安装先检测用户服务管理器，再用相同启动参数执行客户端 `--dry-run` 做离线预检查。预览注册本身不访问管理器、不执行预检查子进程、不写文件。
- 服务定义带安装器标记；Unix 服务文件以 0600 原子写入并拒绝符号链接，Windows 通过任务计划程序注册。无标记的同名定义拒绝覆盖。重复安装替换本用户的同名服务。卸载、状态查询无需加载设备身份或发现目标目录，因此失效配置不会阻碍卸载。
- 注册失败会尝试恢复原服务文件及启用、运行状态；管理器持续不可用时仍尝试恢复文件，并明确报告未完成的恢复。安装成功仅代表管理器接受启动，不证明远端同步或原生词典导入成功。
- 服务不复制当前 shell 的令牌或代理环境变量。优先使用私有 `device.local.json`；如依赖代理或旧 `token_env`，需在用户服务管理器中另行配置环境。服务固定目标后，修改路径记忆不会改变已安装服务，需重新安装。

系统接口参考：[Microsoft ScheduledTasks](https://learn.microsoft.com/en-us/powershell/module/scheduledtasks/)、[systemd.service](https://freedesktop.org/software/systemd/man/latest/systemd.service.html)、[systemd 参数语法](https://www.freedesktop.org/software/systemd/man/256/systemd.syntax.html)、[Apple LaunchAgent 指南](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/CreatingLaunchdJobs.html)。

## 跨平台计划与执行

- `client/core/plans.py` 只生成、校验纯数据计划；禁止文件、网络和平台副作用。纯合并、HTTP 传输模块不得依赖前端，服务端不得依赖客户端编排，底层模块不得反向导入 CLI。
- 根入口 `rime.py` 经 `client/cli.py`、`application/runtime.py` 和 `workflow.py` 编排；平台副作用由 `platforms/platform_execution.py` 分派。服务迁移须保留设备私有身份、原持续参数、备份和同步基线，不继续引用已移除的 `client/sync.py`。
- 计划顶层固定为 `kind/version/platform/steps`，步骤固定为 `id/action/reason/requires/details`。依赖只引用前置步骤；未知版本、动作、平台或非法依赖必须在执行前拒绝。

| 计划 | 版本与动作 | 约束 |
| --- | --- | --- |
| configuration-plan | v1；create/replace/delete/skip | before/after 为 SHA-256 或 null，动作须与指纹一致 |
| native-plan | v1；execute/defer/skip/observe | 包含 last_success_at；observe 表示待运行时空闲探测 |
| workflow-plan | 支持 v1–v4；evaluate/skip | 固定阶段与依赖；含前端偏好和备份清理的工作流为 v4 |

v4 顺序为远端同步、配置应用、共享目录词典交换、第三方刷新、主题应用、前端偏好、重新部署、日志清理、备份清理。配置应用在启用远端时依赖其成功；部署依赖适用资源阶段成功。第三方刷新及清理有独立调度；备份清理还须检查各组恢复状态。不得用旧版四阶段描述当前完整流程。

`--plan-json` 只观察当前本地状态，不联网、不启动前端、不写路径记忆/状态或扩充清单；不包含令牌或词典正文。保存的计划不能作为执行输入。实际执行必须在远端合并后重新规划，并在备份、写入前复核源与目标指纹；保留锁、备份、CAS 和原生凭据检查。

`workflow-plan.json` 与 `workflow-result.json` 保存本轮计划和结果，结果版本与计划一致；开始时记录 pending，随后记录 success/skipped/deferred/blocked/failed，异常时标出失败及未执行阶段。原生计划保存在 `native-all/plan.json`。禁止沿用上一轮成功记录掩盖本轮中断。

## 原生维护与桌面会话约束

### 通用完成判据

配置应用、快照传输、原生词典合并、前端部署和 UI 可用性必须分别记账。异步命令退出码 0、旧快照存在、服务 active 或基线模式为 native-all，都不能单独证明本轮原生操作完成。

部署与同步共用目标维护锁；运行期间必须匹配本轮进程、开始事件、操作类型、范围与成功结果，拒绝旧日志、截断、并发维护和前端重启。Unix librime 通过版本化 C API 访问时按 `data_size` 校验函数指针；Windows DLL 和鼠须管运行库不可假定导出相同符号。不得打开或复制活动数据库用于验证。

### Linux Fcitx5 与 KDE Wayland

- Fcitx5 的部署/同步经 `/controller` 的 Rime 子配置入口触发。保存调用前 journal 游标及 PID，要求本轮正确操作的 start 后出现 success；失败、重叠维护、超时或 PID 改变均不得发布成功凭据。只留维护事件，不复制按键或词条正文；临时日志级别须在 finally 恢复。
- 桌面会话拥有输入法启动权。后台配置读取使用 `DO_NOT_AUTO_START`；维护与主题重载先查询现有唯一 D-Bus owner，再向唯一名称发送请求。前端不存在或查询后退出时失败重试，禁止回退向公共名称发送可激活请求。否则未连上 Wayland 的后台实例可能抢占名称，阻止 KDE 实例启动。
- KDE Wayland 在虚拟键盘设置中选择 Fcitx5，由 KWin 启动；更改入口前备份，重读配置须发送相应配置变更通知。恢复后检查唯一实例由 KWin 管理、Wayland 原生协议与 XWayland 连接、Rime 加载，再由用户确认输入。不能仅凭进程存在判定恢复。
- 自动维护经 `IdleProvider` 取得 Observation，包含 idle/active/unknown、来源、单调时钟和原因；unknown 不允许维护，外部包装器单独标为 delegated。退出时关闭连接，不落盘复用空闲结果。
- Wayland 绑定 `ext_idle_notifier_v1` v2 的输入空闲通知；全部 seat 均 idled 才允许维护，resumed 清除状态。查询通过 `wl_display.sync` 屏障处理排队事件，单次往返最多 1 秒。断连、接口移除、新增 seat、会话 socket 或阈值变化时重新观察；首次连接必须重新等待阈值。
- 无事件接口或连接失败时可使用锁屏兜底；非 Wayland 保留桌面 D-Bus 空闲查询。准备词典与日志游标后、触发前再次检查空闲。键鼠空闲不保证没有预编辑内容，最后检查与再次输入间仍有竞态窗口；单次进程通常不足以等待阈值，持续服务需要正确的会话环境。

### macOS 鼠须管

鼠须管 `--sync`/`--reload` 是异步请求，必须读取当前 PID、本轮新增 INFO 日志，要求 task start、单组全成功统计、操作及词典范围匹配。仅等待 glog 缓冲期限不能保证空闲进程刷新；不能把之后刷出的旧摘要当作新任务成功。

内置维护在空闲并持有维护锁时检查鼠须管进程环境。需要时正常退出唯一实例，以应用专属 `GLOG_logbufsecs=0` 启动，再绑定新 PID 和新日志偏移；不修改全局环境或应用包。已配置实例不重复重启，未确认旧进程退出时不得启动第二实例。超时后 unsafe 标记、上次尝试时间和退避必须跨服务重启、卸载重装保留，重新取得成功凭据前禁止上传失败输出。

### Windows 小狼毫

同步完成遵守前述 `/sync` 判据。部署与同步日志格式不得混用：`/deploy` 须有唯一且有序的 workspace 开始和方案编译全成功汇总、无 ERROR、进程结束，再独立执行 IPC 空会话探测。构建不输出 `Resuming service` 时不得仅因缺行判失败；若有该行则检查顺序。IPC 失败不得发布成功凭据。

Windows 文件同步使用支持 `fsync` 的可写句柄；测试显式关闭 SQLite 连接，避免目录占用。路径与权限测试须包含真实 junction 防护、受保护 ACL 和锁释放，不能把缺少符号链接创建权限导致的跳过算作通过。

## 自动部署与单次测试接口

部署依据配置及第三方词典实际字节指纹判断，并持久化成功指纹；原生成功后再核对资源未变。失败或中断保留待部署状态及重试期限，不能因源已应用就丢掉任务。只有未完成/失败任务受旧 retry_at 限制；成功后的新资源仍检查空闲，但不沿用旧失败等待。该规则不改变原生词典的独立限频。

`automation.json` 的 `deployment.commands` 使用按平台配置的绝对路径参数数组，优先于内置适配器。包装器读取 `RIME_USER_DIR`、`RIME_DEPLOY_IDLE_SECONDS`，等待真实原生完成后在 `RIME_DEPLOY_RECEIPT` 写入 `{"status":"success"}`；未开始可写 deferred。240 秒超时或缺凭据视为失败。远端主题不得携带本机执行命令。

`--deploy-now` 仅用于显式单次配置应用与部署：保留范围、备份、锁、执行前指纹复核及完成凭据，只跳过部署的 unchanged/retry_at，并给予本次手动空闲许可；不修改共享 IdleProvider 或持久化策略。外部包装器收到零空闲阈值仍须返回完成凭据，deferred/失败返回非零。

该入口不进入云同步、词典交换、第三方下载或词典限频；记录独立 `deployment-test-result.json`，不覆盖完整工作流结果。CLI 拒绝与持续服务、初始化、发现及同步动作混用，服务参数白名单不得保存此开关。dry-run 不创建状态、路径记忆或平台执行器。验证时比较执行前后原生词典调度状态，确保手动部署未绕过词典冷却。

## 配置资源与输入行为约束

### 配置源及构建兼容

- `config/` 是唯一应用来源。修改个人行为优先使用 custom 补丁；Fcitx5 应使用 `fcitx5.custom.yaml`，不得用会被原生部署移走的基础 `fcitx5.yaml` 承载个人设置。测试须连续原生部署两次，检查补丁保留、app_options 编译和资源指纹稳定。
- 已同步文件撤回须用 null 删除标记，必要时暂留清单名称以向其他设备传播删除；缩小范围不等于删除。配置换行冲突须保存双方并逐项核对，不用全局选边掩盖差异；文本检出规则保持 LF。
- 方案内部 `__include` 可能在补丁覆盖前产生循环；修复时可内联有效全拼规则、抽取独立英文规则资源，并保持其余语义。空全局 grammar 默认值不得覆盖方案内的模型设置。比较去除构建元数据后的编译结构，验证候选、模型及有效拼写规则；不能仅以告警消失判成功。
- 方案、Lua、OpenCC、语言模型及运行库插件依赖必须单独准备。下载模型按明确上游校验值验证；第三方词典刷新不会补装这些依赖。第三方重复词条警告与方案依赖循环分开处理。

### 共用偏好与平台差异

雾凇优先、朙月备用；默认简体、每页 9 候选、`- =` 翻页、左右 Shift 不切换。雾凇保留英文混输、Emoji、长词补全及模型，不新增模糊音派生；朙月不承诺具有相同混输能力。

Windows/Linux 的 Ctrl+Space 切换须提交去分隔符拼音，例如 `xi'an hao` → `xianhao`，不能提交候选中文；菜单切英时也处理待提交拼音。按一次物理空格周期只切换一次，抑制重复按下并消费配对释放；Control 先释放也能结束周期，不消费无关释放。

Weasel 下在空格释放前保护本次目标 ascii_mode，抵消外部反向 option 更新；释放后允许外部菜单正常切换，其他普通按下清除丢失释放留下的状态。保护仅用于 Weasel，不能推广至 Linux。真实 DLL 注入外部模式更新可验证逻辑，但应用短按/长按体验仍须用户确认；不得把观察到的外部更新直接归因于某个未经证明的系统组件，也不擅自修改注册表全局热键。

Squirrel 的两个中文方案锁定中文模式，外部 ascii_mode 更新须恢复中文；Ctrl+Space 让给系统切换输入源，不消费或用其提交拼音。不得重新引入旧版 macOS 终端/编辑器默认英文策略。Windows/Linux 可按应用标识设置初始英文，仍允许手动切中文，不跨窗口共享状态；不同系统的应用标识不能互套。

Fcitx5 全局快捷键不得截获交给 Rime 的 Ctrl+Space；前端激活/退出使用 Ctrl+Alt+Space，移除 Shift 临时切换。`fcitx5/input.json` 只管理声明字段，通过实时 API 读取、备份、合并、写入并读回，保留其他快捷键，失败回滚。

标点仅根据当前候选或本会话可见的最近提交字符选择：汉字后中文，ASCII 字母/数字后英文；拼音单引号、候选中括号和翻页键保留原义。导航/快捷键后放弃不可靠上下文，无可靠记录回退中文。不得声称能读取任意应用光标前文本或正确追踪粘贴、鼠标移动。

### 外观与主题资源

三端共享竖排 9 候选、14 号字、明暗黑白底与绿色高亮的偏好，但不能把前端参数名称或阴影算法视为等价。背景 E6 alpha、文字和高亮不透明；不得以整体透明度代替背景透明度。具体参数以对应配置源为准。

- 小狼毫使用 ABGR 配色；窗口圆角 12、候选圆角 7、阴影半径 12、偏移 `(0, 3)`。自定义图标须在方案的 `schema/icon`、`schema/ascii_icon` 引用；已有图标二进制不自动纳入文本配置同步。编译结果含路径不代表桌面图标视觉已验证。
- 鼠须管使用原生毛玻璃与系统窗口阴影；`shadow_size` 是高亮阴影，`border_width/height` 是边距，不能映射为小狼毫阴影或描边。保持整体 alpha 默认 1、默认行距，不用 `surrounding_extra_expansion` 冒充首尾高亮扩展开关；特定版本无此开关时须说明前端绘制限制。通用 build 成功后仍须前端 reload 并检查 `build/squirrel.yaml`，最终视觉由用户确认。
- Fcitx5 使用 hx 明暗主题、Sans 系统回退、九宫格圆角资源，关闭背景模糊及系统强调色覆盖。阴影只在面板外，不能叠加改变背景 alpha；不修改 KWin 全局模糊。Classic UI 主题可能影响所有使用它的输入法。

`config/fcitx5/theme.json` 是固定路径资源的 UTF-8/Base64 包，作为单个配置文件三方合并。仅 Linux 解码应用，普通 Rime 配置应用排除 `fcitx5/`；其他平台只保存。限制路径、尺寸和外观项，拒绝外部图片引用，备份并保留无关 Classic UI 设置；相同内容不重载，范围缩小或包缺失保留已安装主题。

修改主题源后用 `python3 client/platforms/linux/generate_fcitx5_theme.py` 重建资源包，开发环境需要 Pillow，常规使用预生成资源不需要。应用及回滚记录位于私有主题状态目录。

## 同步配置与 Git 边界

`sync-manifest.json` 中的实际个人配置文件由同步服务管理，逐路径 Git 忽略；未入清单的第三方资源维持原跟踪方式。清单、策略与程序继续由 Git 管理。`config.example/` 只作受跟踪参考和固定测试输入，运行时不得回退读取，不能将云端每次变化回灌示例。

新增范围须同步检查 `.gitignore`。示例不得包含身份、令牌或自动学习数据库；删除项不生成占位文件。已有设备从 Git 跟踪迁移时先停服务并备份，更新后恢复本地配置、保留基线，防止 Git 移除被当作用户删除。取消当前跟踪不自动重写历史。

Docker 使用白名单，只打包代码、公开策略和运行依赖；测试阶段按需加入测试文件，不能带入私有连接、身份、个人配置或词典。需要完整配置源的验收在独立工作副本初始化，不在活动配置上补造测试数据。

## 开发与验证

### 分层验证与成功声明

| 层次 | 必须检查 | 不能替代 |
| --- | --- | --- |
| 自动回归 | 临时目录、模拟故障、WSGI/SQLite、平台决策及安全边界 | 真实网络、操作系统服务或 UI |
| 隔离原生运行库 | 两设备合成快照、范围限制、多轮合并词频及 c/d/t 稳定、首次建库不覆盖已有目标 | 活动前端原生完成、真实双设备 |
| 隔离输入引擎 | 中文与英文候选、候选数、拼写规则、按下/重复/释放、平台发行标识 | 应用拦截、系统输入源切换、视觉效果 |
| 活动前端 | 本轮完成事件、进程身份、范围、导出元数据、恢复探测与部署后指纹 | 云端传输成功或用户实际键入 |
| 真实 HTTPS | TLS、身份、CAS、配置与快照完整字节核对、失败重试 | 原生词频合并；故障注入不等于真实断网 |
| 后台与桌面 | 安装更新卸载、失败恢复、单实例、真实重新登录启动、用户 UI 确认 | 服务 running 不等于输入法可用；不能推断启动来源 |

报告记录平台、运行库/前端版本、测试范围、通过/失败/跳过及未验证事项；不把旧计数、历史服务状态或其他平台成功写成当前默认结论。验收证据置于私有目录，日志不展开词条、配置正文和凭据。诊断按键问题时只记录必要事件与模式、限制时长和大小，结束后移除临时诊断及启用标记。

### 必须保留的回归场景

- 配置：首次同名冲突、不同文件并发合并、同文件双方保留、持久 null 删除、缩小范围保留数据、执行中源变化停止、目标漂移修复、原子替换失败回滚、只读预览无副作用。
- 网络与身份：过期 CAS、服务端成功后响应丢失、离线未上传内容恢复、重复请求不推进版本、设备快照分叉、用户隔离、令牌轮换重试/宽限/撤销、动态范围上限及禁用。
- 原生：全量范围补齐、调用前服务端范围不足、运行中新词典、空闲 unknown、间隔/退避跨重启保留、无变化兜底导出、失败输出隔离、旧日志/截断/错误 PID 拒绝、重复合并不累加词频。
- 首次建库：合法远端独有快照、已有库不重复初始化、并发创建或空目标目录均不覆盖、错误元数据/清单外名称不执行、发布前关闭并同步文件、原子移动失败保留材料。
- 前端与会话：隔离 D-Bus 注册带激活标记的服务，确认配置读写、维护、主题重载均不激活缺席前端；owner 消失不回退公共名称。Wayland 多 seat、排队 resumed、断连、会话/阈值变化及锁屏兜底单独验证。
- 第三方与备份：锁定同一提交、坏哈希/中断保留旧文件和成功凭据、恢复重试、个人短语保留；清理只删除完成且不受恢复保护的备份，锁冲突与不完整套件不得删除。
- 服务：从无关工作目录启动仍找到根入口；查询卸载不依赖失效配置；更新失败恢复旧定义与运行状态；凭据及一次性动作不进入服务定义；异常重启和重新登录分别验证。

### 公网部署与恢复约束

复用现有 Caddy 外部网络和入口，不发布应用宿主机端口。变更注册/范围前备份，bind mount 文件修改后重建 app/backup，两者分别检查健康。服务端维护细节见 [服务端指南](server/README.md)。

真实 HTTPS 验证使用独立测试用户/设备与合成数据，覆盖未认证 401、范围越界、伪造快照拒绝、CAS 409、冲突保留、删除传播、响应丢失及重复提交、不同用户隔离和容器重建持久化。完成后撤销测试令牌并验证 401，清理测试数据前备份，不改变正式账号数据。设备迁移确认旧身份后撤销注册，保留历史快照和其他设备，不复用安装 ID。

上线核对服务端配置与 `config/`、适用实际配置逐字节一致，本机快照与 HTTPS 内容逐字节一致；null 删除项、仅前端资源项与实际 Rime 文件分开核对。原生合并幂等性使用隔离数据判断，不能拿活动学习或其他设备写入导致的版本变化作为失败证据。

完整备份恢复只在隔离副本检查 SQLite 完整性、套件哈希、轮换凭据认证、用户版本和动态词典范围，不覆盖生产数据库。生产恢复后若版本回退，客户端必须停止并由维护者核对后重建基线；不得自动清空旧状态规避保护。

### 验证入口与依赖

从仓库根目录执行；Windows 使用 `python`，其他平台使用对应原生解释器：

```bash
python3 -m unittest discover -s tests -v
docker build -f server/Dockerfile --target test -t rime-config-test:local .
docker run --rm --network none --read-only --tmpfs /tmp rime-config-test:local
```

原生专项入口为 `tests/windows_native_acceptance.py`、`tests/macos_native_acceptance.py`、`tests/linux_native_acceptance.py`；输入引擎与配置专项见 `tests/windows_engine_acceptance.py`、`tests/fcitx_preferences_acceptance.py`。参数用各脚本 `--help` 查询，运行库路径按本机安装传入，不硬编码其他设备路径。

验收脚本仅在新建隔离目录使用合成词条，复制方案及构建资源时排除活动数据库；要求隔离标记的 worker 不能用作生产包装器。macOS 测试选择无符号链接的真实临时路径（如 `/private/tmp`），不得放宽路径保护；Lua 测试按已安装鼠须管运行库加载依赖。平台、权限或运行库缺失导致的跳过必须明确列出。
