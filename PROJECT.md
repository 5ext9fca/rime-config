# 项目技术说明

本文面向开发与维护人员，记录实现边界、数据流程和验证方式。日常使用见 [README](README.md)，公网部署与备份见 [服务端指南](server/README.md)，协作约定见 [AGENTS.md](AGENTS.md)。

## 当前交付状态

截至 2026-11-10，Windows 原生客户端及真实 VPS 已完成验收。本机当前用户计划任务单实例运行，每 60 秒通过现有 Caddy HTTPS 同步。6 个个人配置文件、2 份词典快照核对通过；后续已按用户要求接入原生 `/sync` 自动合并、导出及回传，模式为 `native-all`。Windows 和 Unix 共用全量词典范围补齐规则；Unix 原生包装器配置及实机验收不在本轮范围。详细证据见 [Windows 验收总结](#windows-验收总结)、[公网部署与同步验收](#公网部署与同步验收) 和 [原生全量同步](#原生全量同步)。

macOS 已完成配置与快照 HTTPS 端到端、手动原生词典合并及用户 UI 验收；launchd 运行与异常重启通过，登录触发未实测。macOS 后台仍为 `snapshots-only`，无人值守原生包装器未交付。下一阶段由另一台 Ubuntu 进行 Linux 实机验收，见下文交接。

## 代码与数据边界

| 位置 | 职责 |
| --- | --- |
| `client/sync.py` | 命令入口、周期调度、本地配置应用与备份 |
| `client/paths.py` | 跨平台目录发现与私有路径记忆 |
| `client/service.py` | 跨平台服务入口，systemd / launchd 用户服务管理 |
| `client/windows_service.py`、`client/windows_service.ps1` | Windows 当前用户计划任务的注册、查询、卸载与恢复 |
| `client/windows_runner.py` | pythonw 后台入口与 UTF-8 日志 |
| `client/file_lock.py`、`client/windows_security.py` | 跨进程文件锁及 Windows 私有文件 ACL |
| `client/identity.py` | 安装 ID 与设备令牌初始化 |
| `client/scope.py` | 个人配置及词典范围校验 |
| `client/remote.py` | HTTPS 同步、三方比较、版本提交与恢复 |
| `client/dictionaries.py` | 原生个人词典快照交换与应用钩子 |
| `client/native_sync.py`、`client/weasel_sync.py` | 跨平台全量范围补齐、完成凭据、Windows 原生 /sync 与恢复检查 |
| `client/third_party.py` | 第三方词典下载、校验与刷新 |
| `server/app.py` | WSGI 接口、设备鉴权与 SQLite 持久化 |
| `tests/` | 临时目录、模拟上游及客户端/服务端集成测试 |

配置流向为：服务端与 `config/` 合并 → 更新 `config/` → 按清单应用到实际目录。实际目录不是配置编辑源。自动学习数据则从 Rime 原生快照采集，经服务端或共享目录交换，再交由 Rime 合并。第三方词典从上游直接更新实际目录，不进入个人数据服务端。

`config/` 中留存的第三方文件不代表它们全部受管理；个人范围以 `sync-manifest.json` 为准，第三方刷新范围以 `third-party.json` 为准。

## 能力与实现边界

| 职责 | 目标行为 | 当前实现 |
| --- | --- | --- |
| 服务端同步 | 拉取个人配置和词典，合并本地变更，将更新提交回服务端 | 已实现 HTTPS 客户端、设备令牌认证、SQLite 持久化与版本校验 |
| 配置合并 | 使用上次同步基线、本地配置和服务端配置进行三方合并，冲突保留双方内容并报告 | 已实现按文件三方比较、冲突保留及显式解决；不自动拼接 YAML |
| 配置应用 | 合并结果写入 `config/`，按清单应用到实际 Rime 目录 | 已实现本地单向应用、备份和受控删除 |
| 个人词典应用 | 采集本机学习数据，与远端数据合并，通过 Rime 原生机制更新实际用户词典 | Windows 原生 /sync 已接入后台，按全量范围合并导出并验证；Unix 共用全量规则，平台包装器配置及实机联调待完成 |
| 后台自动运行 | 当前用户登录后持续同步，支持失败恢复 | Windows 当前用户计划任务已验收；macOS launchd 运行及异常重启通过，登录触发待验收；Linux systemd 待实机验收 |
| 第三方词典刷新 | 按独立周期拉取指定上游词典，校验后更新本机副本 | 已实现项目配置驱动的 GitHub 词典刷新，默认雾凇拼音 |

`config/` 继续作为本地配置应用的唯一权威来源：服务端同步先合并更新此目录，再向输入法目录应用。配置编辑发生在 `config/`；实际目录中的配置修改不会自动反向采集。自动学习词典从实际输入法产生，使用独立的数据同步流程。

服务端提交必须携带基线版本，避免并发客户端相互覆盖；冲突、离线和上传失败时保留本地未上传内容，重试后再推进成功同步版本。配置合并成功、服务端提交成功、本地应用成功应分别记录，失败后可从对应阶段恢复。不能将本地快照交换成功等同于服务端同步或词典导入完成。

第三方词典采用独立的上游清单、刷新周期和版本记录；在暂存目录下载及校验后更新受管理文件，失败保留旧版本。个人配置、短语和个人词典不受刷新覆盖。该职责不自动包含第三方方案、Lua、OpenCC 或模型升级。公网服务地址与同步周期由 `remote.json` 配置，本机安装 ID 和设备令牌保存在私有 `device.local.json`；第三方上游清单见 `third-party.json`。


## 实际配置目录的发现与记忆

首次搜索规则位于 [`paths.json`](paths.json)，本机选择保存在私有 `paths.local.json`（Unix 0600、Windows 受保护 ACL；Git 忽略，不进入镜像或同步）。不需要先配置设备令牌：

```bash
# 发现并记住实际 Rime 目录；不联网、不应用文件、不要求令牌
python3 client/sync.py --discover-target
# 只预览，不写记忆文件
python3 client/sync.py --discover-target --dry-run
# 明确选择并记住一个现有目录
python3 client/sync.py --discover-target --target /实际/Rime/目录
# 忽略旧记忆及 device.local.json 内旧路径，重新按项目候选路径搜索
python3 client/sync.py --discover-target --rediscover-target
```

目录选择优先级为：`--target` → 当前平台的路径记忆 → `device.local.json` 的 `target` → `paths.json` 候选路径。正常运行和成功初始化也会记住选择，`--dry-run` 始终不写记忆。此后直接运行 `--watch` 即可复用。与此前行为不同，显式 `--target` 会成为后续默认目标；使用临时目录验证时可同时指定临时 `--paths-state`。

`paths.json` 按 `windows`、`wsl`、`macos`、`linux` 配置候选目录列表；旧三平台配置兼容补入 Windows 默认候选。所有候选都必须是展开后的绝对路径，不递归扫描。模板支持 `{home}`、`{xdg_config_home}` 和 `{windows_appdata}`，也支持 `~`；Windows 直接读取 APPDATA，WSL 将 Windows APPDATA 转换为 Linux 路径。例如：

```json
{
  "version": 1,
  "required_files": ["installation.yaml"],
  "candidates": {
    "windows": ["{windows_appdata}/Rime"],
    "wsl": ["{windows_appdata}/Rime", "/mnt/c/Users/hx/AppData/Roaming/Rime"],
    "macos": ["{home}/Library/Rime"],
    "linux": ["{xdg_config_home}/fcitx5/rime", "{xdg_config_home}/ibus/rime"]
  }
}
```

自动发现要求目录存在，并包含 `required_files` 中的所有文件；可调整标记清单，空列表表示只检查目录。WSL 首选通过 Windows APPDATA 检测，互操作不可用时继续检查后续显式候选。多个有效候选不会按顺序盲选，必须用 `--target` 消除歧义；完全没找到时提示修改候选配置。

已记住的目录或身份配置目录失效时直接报错，不悄悄切换到其他输入法，也不自动创建原路径。持续模式每轮重新检查目标目录是否仍存在，但不会运行中切换目标；修改路径后重启服务。显式指定的目标也必须已存在，且所有路径拒绝符号链接。

`--paths-config FILE` 选择另一份发现规则；`--paths-state FILE` 选择另一份私有记忆文件，默认是设备配置同目录的 `paths.local.json`。记忆按平台分别保存，不含令牌，不应放入 `config/` 或实际 Rime 目录。多份设备身份需要独立路径记忆时显式指定不同 `--paths-state`。


## 初始化本机配置

首次使用运行：

```bash
# WSL（自动检测不成功时显式指定 Windows Rime 目录）
python3 client/sync.py --init --target /mnt/c/Users/hx/AppData/Roaming/Rime
# macOS 通常可直接自动检测
python3 client/sync.py --init
# Ubuntu 按实际输入法选择目标目录
python3 client/sync.py --init --target ~/.config/fcitx5/rime
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

之后运行 `python3 client/sync.py --watch` 即可自动读取安装 ID、令牌和目标目录，无需重复传 `--device-id` 或设置令牌环境变量。`--target` 可覆盖目标路径并更新独立路径记忆；路径变化后应重启持续服务。身份文件每轮重新读取，令牌轮换可重新运行 `--init`；交互输入留空保留已有令牌。安装 ID 变化时必须提供新设备的令牌。

没有 Rime 安装文件时可以用 `--init --device-id ID --target PATH` 显式提供；若实际文件中存在不同的 ID 则拒绝初始化。非交互环境支持 `--init --token-stdin` 从标准输入读取一行令牌，例如从私有文件重定向：

```bash
python3 client/sync.py --init --token-stdin --target /实际/Rime/目录 < /私有路径/device-token
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
python3 client/sync.py --dictionary-store /path/to/private-store --device-id DEVICE_ID \
  --native-sync-command '["/absolute/path/to/native-sync-wrapper", "--dictionary", "{dictionary}"]'
```

客户端逐个替换名称并执行；包装程序须只合并/导出所指定词典，并等待完成。旧式不带占位符的全量同步命令会被拒绝。客户端无法限制外部程序忽略参数或用户手动执行 Rime 全量同步；包装程序的按词典处理能力需在各端验证。


## 文件、备份与失败处理

- 对全部路径进行预检查，再逐文件原子替换；内容相同则跳过，采用复制而非链接。
- 仅删除此前管理、仍列在 `sync-manifest.json` 中但已从 `config/` 删除的文件。从清单移除路径表示解除管理，保留目标副本，因此升级后不会误删此前管理的第三方依赖。首次应用不删除额外文件；所选源文件全部缺失时拒绝应用。
- 拒绝符号链接、路径类型冲突和源/目标/状态目录重叠；不管理 `build/`、`sync/`、`*.userdb*`、`installation.yaml`、`user.yaml` 和 `.gram` 文件。
- 每次修改前，将所有受影响的已有目标文件备份至 `~/.local/state/rime-config/<目标路径标识>/backups/<会话>/files/`，并写入 `journal.json`。备份不自动清理，可能包含个人配置，应妥善保管。
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
python3 client/sync.py --resolve-conflicts local
python3 client/sync.py --resolve-conflicts remote
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
python3 client/sync.py --third-party-only --dry-run
# 立即刷新，不等待下次周期（仍遵守 enabled）
python3 client/sync.py --third-party-only --refresh-third-party
# 正常后台运行时，自动按项目配置周期刷新
python3 client/sync.py --watch
# 可指定另一份项目配置
python3 client/sync.py --third-party-only --third-party-config /path/to/third-party.json
```

以上命令同样支持 `--target`、`--state-dir`；Ubuntu 的目标目录有歧义时必须指定。`--refresh-third-party` 在持续模式下仅强制首轮，之后恢复配置周期。单次正常执行未到周期时跳过刷新。

刷新先将分支/标签解析为具体提交，从该提交的 Git tree 读取清单、文件大小及 blob SHA，再下载同一提交下的全部指定文件。检查大小、Git blob 哈希、UTF-8 文本及基本词典头格式后，在状态目录暂存；全部成功后才写目标。哈希用来验证与该上游提交的一致性，不等同于发布者签名；词典头检查也不代替 Rime 部署验证。

覆盖前备份旧文件，目标文件逐个原子替换，捕获到文件应用失败时回滚已完成项。记录位于 `<state-dir>/third-party/`：`receipt.json` 保存成功提交与文件 SHA-256，`schedule.json` 保存下次尝试时间，`backups/` 保存旧文件和操作记录。内容相同不会重复覆盖或备份。没有整目录替换、没有删除传播；从刷新清单移除文件表示停止管理，保留目标副本。断电或强制终止不保证整批回滚；备份和记录保留，可检查后强制刷新以重新应用完整版本。

清单只允许 `.dict.yaml` 和词典 `.txt`，拒绝与个人配置清单重叠、个人短语、用户数据库、符号链接及越界路径。默认不刷新 `rime_ice.dict.yaml`、`melt_eng.dict.yaml` 入口文件，以保留其中可能存在的个人 `import_tables`；也不刷新 `.schema.yaml`、Lua、OpenCC 和语言模型。请先在客户端安装完整雾凇方案，并自行维护词典入口与上游的兼容性。第三方词典直接应用到实际目录，不回写 `config/`，不进入个人数据服务端同步。

刷新后需在 Rime 中重新部署才能加载新词典，本工具会提示但不自动重启或部署输入法。Windows 已完成真实 GitHub 下载校验和本机重新部署验证；模拟上游测试覆盖哈希异常、下载中断、回滚与周期行为。macOS 等其他平台的实机部署效果仍待验证。


## 自动学习个人词典

本工具从 Rime 原生生成的 `<sync_dir>/<installation_id>/*.userdb.txt` 中仅交换项目清单内词典，保留词条、词频和元数据。每台设备只发布自己的快照，接收其他设备的快照；不传播文件删除，不直接操作正在使用的 `*.userdb` 数据库。词典合并由 Rime 完成，参见 [Rime 同步说明](https://github.com/rime/home/wiki/UserGuide#同步用戶資料) 和 [原生快照恢复/合并实现](https://github.com/rime/librime/blob/master/src/rime/lever/user_dict_manager.cc)。

启用方法：

1. 查看本机 `installation.yaml` 中的 `installation_id`。每台设备必须唯一，不能克隆同一 ID。本工具不改写该文件。
2. 在 Rime 菜单中执行“同步用户资料”，等待完成，以生成本机快照。
3. 指定私有交换目录和本机 ID，运行服务：

```bash
python3 client/sync.py --watch --interval 10 \
  --target /mnt/c/Users/hx/AppData/Roaming/Rime \
  --device-id 09ad77e5-8a8d-45b8-97f3-b2893bd56e5b \
  --dictionary-store /path/to/private-rime-dictionaries
```

以上为可选的共享目录模式：各端使用同一个共享目录，或由独立云盘同步其内容。公网 VPS 模式请启用 `remote.json`，不要同时传入 `--dictionary-store`。只允许同步快照文件，不同步原生 `sync/` 目录中附带备份的配置或第三方文件。可在仓库内用 `private/dictionaries/` 作为本地暂存目录，`private/` 已被 Git 忽略；不同设备的本地暂存目录不会自动联网互通。

默认原生同步目录为目标下的 `sync/`；若 `installation.yaml` 设置了 `sync_dir`，须用 `--rime-sync-dir` 指向实际目录（WSL 使用转换后的 Linux 路径）。`--device-id` 须与本机快照中的 `/user_id` 一致，程序会检查收到的快照设备标识及词典名。

接收远端快照后，再执行 Rime 的“同步用户资料”，由 Rime 合并到本机数据库并导出最新快照；服务下一轮发布它。日常新学习的数据也需先由 Rime 导出，服务不会扫描活动数据库。既未启用远端同步也未提供 `--dictionary-store` 时仅应用配置；未生成快照时会提示，不会声称词典已导入。

新部署采用下节的原生全量入口。旧 `--native-sync-command '["/absolute/path/to/native-sync-wrapper", "--dictionary", "{dictionary}"]'` 保留兼容，仍须只处理指定词典、等待完成后退出，不能把 `/sync` 填入这个逐词典接口。执行顺序仍为接收快照 → 原生合并/导出 → 发布本机快照；失败不发布，dry-run 不执行原生命令。

词典快照在覆盖前备份至状态目录下 `dictionaries/backups/`，写入采用原子替换。交换不作整批回滚，失败可重试，已完成文件保持有效；不会删除快照或清空词条。服务锁仅协调本程序，不能锁住 Rime 或云盘；应等待原生同步完成后交换。修改中的快照会报错，请重试。所有快照和备份均含个人数据，使用私有存储。

按 [用户指南](README.md#后台运行) 执行 `--service install` 时传入同样的原生参数，即可启用后台合并与交换。Windows 已分别完成隔离原生合并及生产 `/sync` 验收；其他平台原生命令需另行配置并实机验收。


## 原生全量同步

按用户最终选择，Windows 与 Unix 使用平台原生全量同步语义。Windows 入口为 `--weasel-deployer /绝对路径/WeaselDeployer.exe`，Unix 入口为 `--native-sync-all-command`；二者与兼容的逐词典命令互斥，服务安装器会保留入口及 `--native-sync-config` 参数。全量调用仅在独立维护调度到期后执行一次，不为每个词典或每轮云轮询重复执行 `/sync`。

### 独立维护调度

此前每 60 秒云同步都会调用 `/sync`，实机记录约每 61～66 秒进入一次维护；只有一个后台进程，原因是缺少独立原生调度。现由根目录 `native-sync.json` 控制，默认最小维护间隔 900 秒、失败重试间隔 900 秒、空闲阈值 30 秒、兜底导出间隔 3600 秒，每轮重新读取。

- `native-all/schedule.json` 在原生调用前持久化尝试时间和输出隔离标记，成功后保存完成时间及变化指纹。进程重启、云同步失败重试和 `--sync-now` 都不清除限频。旧状态从 `latest.json` 的完成时间迁移，不因升级立即追加维护。
- 指纹包含活跃数据库文件的路径、大小、修改时间以及各设备快照的内容哈希；不读取或复制活动数据库。没变化则跳过。输入法可能尚有内存中的学习数据，因此一小时到期后仍安排导出，但不会绕过最小间隔或空闲门槛。
- Windows 使用 `GetLastInputInfo` 检查当前会话键鼠空闲时间。30 秒是输入活动门槛，不是对应用未提交预编辑内容的检测。Unix 由前端包装器判断其会话空闲状态；公共层传入阈值，不假定跨桌面通用 API。
- 接收的新快照保存在原生同步目录，变化指纹一直保留待处理信号，直到成功原生处理后更新。等待期间配置同步及既有安全快照传输继续。原生调用失败当轮停止提交；随后限频等待的云轮次可处理配置，但不发布失败/中断留下的词典输出。
- `native-all/application.json` 及远端基线中的 `dictionary_application` 记录 `status`（success/deferred/unchanged/failed）、原因和 `last_success_at`。`latest.json` 保留实际原生调用结果；模式为 `native-all` 本身不能证明本轮已导入。

实机连续强制两轮云同步均成功，新增原生维护次数为 0，基线明确为 deferred/interval，后台已加载新策略。证据为 `private/native-schedule-result.json`。本轮 Windows 回归 99 项：92 通过、7 项跳过；调度测试覆盖变化、空闲、冷却、无变化兜底、跨进程重建、旧状态迁移、失败输出隔离，以及延后维护期间继续云配置和快照接收。回归日志为 `private/native-schedule-tests.log`。

### 范围与失败处理

- `native_sync.py` 每轮扫描实际目录中的用户数据库名称和原生 `sync/` 下所有设备的 `*.userdb.txt`。校验元数据及路径，拒绝重解析路径、大小写冲突和残留 `.temp.userdb` 等异常数据库。
- 把发现的词典名追加到 `sync-manifest.json`，先备份旧清单；不删除已有名称，不强制开启被禁用的词典同步，dry-run 仅显示计划。清单在扫描期间变化时停止，避免覆盖并发编辑。
- HTTPS 请求先确认服务端允许完整范围，再接收快照和执行原生命令；服务端缺项时报告具体名称并停止，需维护者对齐服务端清单后重建容器。客户端不自行修改服务端授权范围。
- 调用前后再次检查范围；运行期间出现新词典时补齐清单并停止本轮上传。原生全量同步只处理已经存在本机数据库的词典；仅有远端快照而尚无本机数据库的名称会明确报告“尚未导入”，不把复制成功计为合并成功。
- 调用前保留已有本机快照；Windows 另备份原生会覆盖的同步目录 YAML/TXT 副本。不会复制活动 LevelDB 文件，也不把快照备份描述为全部活动数据库的精确回滚镜像。部分原生合并后失败时保留数据，由原生合并语义支持重试，不手动覆盖数据库。
- 原生命令失败、超时、完成凭据缺失或范围变化时不上传本轮快照，不推进原生成功记录。原生结果单独写入状态目录 `native-all/runs/<本轮ID>/result.json` 和 `native-all/latest.json`；HTTPS 成功版本仍由 `remote/baseline.json` 记录，配置应用由原有配置状态记录。
- `/sync` 附带备份的配置文件留在原生同步目录，不扩大 `configuration.files`，不上传第三方资源。每轮原生快照备份和结果保留在私有状态目录，当前不自动清理历史备份。

### Windows 入口与完成判定

`weasel_sync.py` 验证传入目标与小狼毫注册用户目录、安装 ID、原生 `sync_dir` 一致。使用已安装 librime 的只读 YAML 接口读取 `sync_dir`，不改写安装身份。已存在 `WeaselDeployerMutex` 时延后执行，避免与部署程序争用。

运行 `WeaselDeployer.exe /sync`，最多等待 180 秒；小狼毫负责进入维护模式、执行安装检查/配置备份/全量用户词典合并与导出、退出维护。进程退出后必须同时满足：

1. 退出码为 0；本次 PID、时间对应的 INFO 日志唯一。
2. 日志包含 `3 tasks ran: 3 success, 0 failure`，处理词典集合与预检查完全一致，且无 ERROR 行。
3. 所有本机词典快照均已更新且元数据有效。
4. 经 IPC 创建空输入会话、Echo 校验并立即释放成功，确认输入服务可用；不输入文字、不操控 UI。

此版本小狼毫未记录维护恢复的 INFO 行，因此不以该行判定恢复。失败/超时后先确保本次子进程结束，再尝试有界的恢复维护请求；其他部署程序持有互斥体时不抢占。恢复未确认会记录失败，保留数据重试。当前实机适配小狼毫 0.17.4 / librime 1.13.1；其他构建若改变任务或日志格式，会停止并要求适配，不降低成功判据。

### Unix 全量包装器约定

公共同步流程对 Unix 采用相同的范围补齐、先拉取、全量合并导出、再回传规则。平台包装器须通过输入法自身的原生接口处理并发，等待真实完成，不应直接打开输入法正在使用的数据库。不能把仅发出 D-Bus/进程通知的异步命令当作成功包装器；也不假定每个平台都有名为 `/sync` 的相同命令行选项。

执行时通过环境变量提供 `RIME_USER_DIR`、`RIME_SYNC_DIR`、`RIME_INSTALLATION_ID`、`RIME_SYNC_DICTIONARIES`（本机数据库名 JSON 数组）、`RIME_SYNC_IDLE_SECONDS`（空闲阈值）和本轮唯一的 `RIME_SYNC_RECEIPT` 路径。包装器须先检查会话空闲；不满足时不得触发原生命令，写入 `{"status":"deferred"}` 并以 0 退出。完成全部任务后写入 UTF-8 JSON：

```json
{"status": "success", "names": ["luna_pinyin", "rime_ice"]}
```

`names` 必须与本轮全部本机数据库一致；成功凭据应依据原生完成事件或任务结果产生，不能只根据旧快照存在就写成功。包装器非零退出、超过 240 秒或缺少本轮凭据都会停止上传。此公共约定和模拟 Unix 命令回归已通过；本轮未交付具体 Unix 输入法包装器、未进行 Unix 实机验收。

### 本轮 Windows 验收

2026-11-10 已完成生产 `/sync` 实机执行：`luna_pinyin`、`rime_ice` 两个原生词典全部成功，3 个原生任务均成功，导出和 IPC 恢复探测通过，HTTPS 上传成功，基线切换为 `native-all`（接入时服务端版本 3）。现有任务已更新并确认后台执行成功，后续周期保持相同服务端版本；没有新建真实第二台设备，也未进行登录触发审计或修改既有方案警告。

首次原生全量接入回归共 93 项：Windows 86 通过、7 项因符号链接权限跳过；远端隔离 Linux 容器 87 通过、6 项因平台条件跳过。新增测试覆盖范围自动补齐与只读预览、禁用保留、快照元数据、运行中新增词典、全量命令只执行一次、Unix 凭据缺失、无本机数据库时拒绝宣称导入成功、原生日志失败判定，以及服务端范围检查和原生失败阻止提交。快照数据库名称改为与 librime 相同的最后一个 `.userdb` 后缀规则，避免声明范围与实际原生数据库不一致；修正已同步部署到服务端。测试现使用隔离的禁用远端配置及私有身份路径，不读取正式凭据。

复现入口见 README。私有回归记录为 `private/native-all-tests.log`；最终生产核对摘要为 `private/native-all-final-result.json`，确认后台参数含原生入口、单实例、6 个配置和 2 份快照与服务端一致。原生证据位于当前用户状态目录的 `native-all/`，完成日志路径保存在结果中。原生实现依据 [Weasel SyncUserData](https://github.com/rime/weasel/blob/0.17.4/WeaselDeployer/Configurator.cpp)、[librime 全量同步](https://github.com/rime/librime/blob/1.13.1/src/rime/lever/user_dict_manager.cc) 及 [Weasel IPC](https://github.com/rime/weasel/blob/0.17.4/include/WeaselIPC.h)。

## 个人输入偏好（Windows 小狼毫）

根据确认的偏好维护以下个人文件，均已加入 `sync-manifest.json`：

| 文件 | 内容 |
| --- | --- |
| `config/default.custom.yaml` | 雾凇优先、朙月备用、9 候选、禁用左右 Shift 切换、`- =` 翻页 |
| `config/rime_ice.custom.yaml` | 默认简体、Emoji、长词补全、个人处理器，保留万象模型设置 |
| `config/luna_quanpin.custom.yaml` | 备用方案简体、9 候选及个人处理器 |
| `config/weasel.custom.yaml` | 竖排候选列表、14 号字、明暗配色、程序初始英文名单 |
| `config/lua/hx_preferences.lua` | 中英文切换时提交去分隔符拼音，以及基于可见上下文的自动标点 |

- **中英文切换**：`Ctrl+Space` 切换。左右 Shift 不切换，CapsLock 保留大写功能。切换时将 `xi'an hao` 这样的输入提交为 `xianhao`，不提交候选中文；前端菜单切到英文时也处理未提交拼音。外部程序若拦截 Ctrl+Space，需调整其快捷键。
- **状态**：`global_ascii: false`，不跨窗口共享中英文状态。终端和编辑器通过 `app_options` 设置初始英文，允许在其中切到中文；不会每次按键强制英文。
- **默认英文程序**：Windows Terminal、CMD、PowerShell、WSL、Git Bash/mintty、WezTerm、Alacritty、Tabby、PuTTY、MobaXterm；VS Code/Insiders、Cursor、Windsurf、VSCodium、Sublime Text、Notepad++、Neovim-Qt、GVim、Emacs、Visual Studio，以及常见 JetBrains IDE。精确进程名清单位于 `weasel.custom.yaml`，浏览器、聊天软件和普通记事本不在名单内。
- **外观**：竖排列表、每页 9 候选，候选、序号、注释字号均为 14。跟随 Windows 明暗模式：浅色白底黑字，深色黑底白字，绿色圆角高亮。窗口圆角 12、候选圆角 7（同时设置正式字段 `hilited_corner_radius` 和兼容别名 `round_corner`），阴影半径 12、偏移 `(0, 3)`。配色显式采用 ABGR，背景 alpha 为 `E6`（约 90% 不透明），普通候选及编码背景透明，文字与选中背景保持不透明；浅色/深色阴影分别为 `0x28000000` / `0x50000000`。这些值由用户确认的现有部署样式合并回 `config/weasel.custom.yaml`，以配置源长期维护，不直接编辑生成文件。
- **输入能力**：默认简体，沿用当前雾凇的拼写纠错、英文及中英混输翻译器；模糊音规则在原方案中保持注释，不新增模糊音派生。启用 Emoji 与长词补全。备用朙月不具备完整雾凇混输和 Emoji 功能。
- **标点**：中文模式下，根据当前候选或本会话最近已提交字符选择：汉字后中文标点，ASCII 字母/数字后英文标点。中文引号等交由原生标点器处理；拼音串内的单引号仍是分隔符，中括号有候选时仍用于以词定字，`- =` 保留翻页。英文模式保持英文标点。
- **上下文限制**：此功能无法读取应用任意光标前文本。粘贴、鼠标移动、应用切换等情况下不能保证跟随真实上一个字符；能识别到的导航/快捷键后会放弃旧记录，无可靠记录时回退中文标点。这不是微信输入法偏好的直接导入，而是依据用户回答编写的 Rime 配置。

上述偏好写入项目配置后，仍需应用并重新部署小狼毫。Lua 已使用小狼毫自带运行时验证切换、去分隔符、标点、导航回退及翻页让行，实际 Rime 引擎的候选和快捷键测试通过；桌面 UI 验收由用户负责，本轮已由用户确认接受。Windows 配色和应用选项仅针对小狼毫；macOS 外观适配见下文，Ubuntu 前端需另行配置。

### macOS 外观适配

**UI 验收结论（2026-11-10）：用户确认通过。** 最终版本为竖排 9 候选、14 号字、系统毛玻璃与 E6 明暗底色、窗口圆角 12、高亮圆角 7、高亮阴影 12；撤销行距 18，继承默认行距 5。首尾候选的额外扩展保留鼠须管原生行为。此结论仅覆盖 UI，不改变无人值守原生包装器、登录启动等未完成项。以下历史阶段记录保留原时间点状态。

`config/squirrel.custom.yaml` 已按当前 Windows `weasel.custom.yaml` 重新生成（2026-11-10）：竖排候选列表 `candidate_list_layout: stacked`，文字方向保持 horizontal；候选、序号、注释字号均为 14，候选数量沿用通用配置的 9 个。窗口圆角 12、高亮圆角 7；明暗背景沿用 ABGR 的 `0xe6ffffff` / `0xe6000000`，约 90% 不透明，文字与绿色高亮保持不透明。颜色使用 sRGB，标签高亮字段映射为 `hilited_candidate_label_color`，普通候选及预编辑背景透明。

鼠须管 `shadow_size: 12` 表示候选高亮阴影，不能与 Windows 窗口阴影半径、偏移和阴影色逐项等价；不添加前端不支持的 Windows 字段。`translucency: true` 启用系统毛玻璃，保留 E6 alpha 明暗底色及不透明文字。旧补丁已备份到私有 `private/macos-acceptance/squirrel-before-*`。实际目录已应用，`Squirrel --reload` 后检查生成的 `build/squirrel.yaml` 确认竖排、圆角、阴影和背景 alpha 正确，UI 已于 2026-11-10 由用户确认验收通过。通用 `rime_deployer --build` 成功并不代表前端 `squirrel.yaml` 已重编译，应在前端 reload 后检查。

首尾候选扩展：用户已要求撤销 `line_spacing: 18`，补丁不再覆盖行距，当前继承默认值 5。鼠须管 1.1.2 在竖排高亮路径中直接为首尾追加边距，并将边界扩展到外框，没有 YAML 开关可单独禁用。`surrounding_extra_expansion` 调整的是非选中候选背景相对大小，不是首尾扩展开关。配置只能通过调整圆角、边距、行距间接平衡；要在保留当前其他尺寸的同时真正取消此行为，需要修改前端绘制代码并重新构建。此次仅回滚行距、开启原生毛玻璃，保留其他几何参数；首尾差异可能恢复。

原生效果（鼠须管 1.1.2）：背景色 alpha 支持普通透明；`translucency: true` 使用 AppKit `NSVisualEffectView`（behindWindow / hudWindow）实现系统毛玻璃，当前已开启；`style/alpha` 会影响整个面板，当前保持默认 1。窗口本身通过 `NSPanel.hasShadow = true` 使用系统阴影；`shadow_size` 则是另外的 Core Animation 高亮阴影，黑色、不透明度 0.2，偏移随尺寸推导，不能由 YAML 独立指定 Windows 的阴影色和偏移。依据 [SquirrelPanel](https://github.com/rime/squirrel/blob/1.1.2/sources/SquirrelPanel.swift) 和 [SquirrelView](https://github.com/rime/squirrel/blob/1.1.2/sources/SquirrelView.swift)。

鼠须管 `border_width`、`border_height` 控制边距，不能等同小狼毫描边宽度；当前均为 1。字体设为空以使用系统回退；当前 UI 已获用户验收，不保证两端逐像素一致。保留原来的行内预编辑与应用选项；Windows `.exe` 名单不属于本次外观迁移。

2026-11-10 已应用到实际目录，通过鼠须管原生部署器编译并检查生成的 `build/squirrel.yaml`，随后执行官方 `Squirrel --reload` 请求前端重新部署。原目录无 `squirrel.custom.yaml`，本次新增补丁，不覆盖基础 `squirrel.yaml`。实际 UI 验收由用户完成。首次迁移时未上传；后续已扩展真实 VPS 清单并完成 HTTPS 同步，见公网续验记录。

字段参考：[鼠须管官方配置](https://github.com/rime/squirrel/blob/master/data/squirrel.yaml)。


## 自动系统服务注册

入口为 `client/sync.py --service install|uninstall|status`，实现集中在 `client/service.py`。操作用户级服务，不申请系统管理员权限。Windows 原生走当前用户计划任务分支；WSL 和 Ubuntu 走 Linux systemd 分支；macOS 走 launchd 分支。

- Windows：`client/windows_service.py` 将 JSON 载荷编码后交给 `windows_service.ps1`，通过 ScheduledTasks 注册 `rime-config-<当前用户 SID>`。Interactive 登录类型、Limited 权限、该用户登录触发，无需密码或令牌进入任务定义。采用 IgnoreNew、无执行时限、电池供电继续运行、失败每分钟重试（最多 999 次），并增加每分钟重复触发器，补偿实机中 RestartOnFailure 未触发的情况；运行中忽略新触发。原生 `pythonw.exe` 直接运行 `windows_runner.py`，在同一任务进程运行客户端并捕获 UTF-8 日志，停止任务即停止客户端。安装先离线预检查，更新前导出旧 XML；失败恢复旧定义与原运行状态，新安装失败删除新任务；无管理标记的任务拒绝覆盖及卸载。查询和卸载不依赖项目同步配置。预览不访问任务计划程序。
- Windows 日志为 `%LOCALAPPDATA%\rime-config\logs\service.log`；启动时若超过 10 MiB 保留一个 `.1` 文件，运行中不轮转。计划任务是登录会话内的自动运行机制，不是 SCM 系统服务，用户未登录时不运行。安装成功不等于同步已成功。
- Windows 原生路径通过 `%APPDATA%\Rime` 发现；旧三平台 `paths.json` 兼容补入此默认候选。Windows 与 WSL 使用各自的路径记忆键。所有客户端 JSON 读取显式使用 UTF-8，清单继续使用 `/` 分隔；拒绝 Windows 设备名、备用数据流、尾随空格/点和目录联接等重解析路径。
- 跨进程锁集中在 `file_lock.py`：Unix 使用 `flock`，Windows 使用 `msvcrt.locking` 非阻塞锁定第 0 字节，文件句柄关闭即释放。四条写入流程均使用此锁。Windows 的锁不保证与 WSL `flock` 互斥，不应让 Windows 和 WSL 同时管理同一实际目录或状态目录。
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

自动测试覆盖三类服务的安装、更新、卸载、注册失败恢复、参数处理和只读预览；Windows 另完成真实任务生命周期及故障恢复测试。systemd / launchd 的实机运行仍需在对应平台验收。

## 开发与验证

### Ubuntu / Linux 验收交接

下一阶段由另一台 Ubuntu 实机继续；本次 macOS UI 已由用户确认通过，不将其结果视为 Linux 已验收。

1. 拉取本次提交，先确认实际使用的前端是 IBus Rime、Fcitx5 Rime 或其他实现，再发现实际目录；多个候选必须明确选择，不沿用 Mac 私有路径文件。
2. 运行 `python3 -m unittest discover -s tests -v`、`--dry-run`、`--plan-json`，记录真实平台、版本、通过与跳过项。原生验收脚本必须适配 Linux 已安装运行时，不能直接套用 Windows DLL 或 macOS 应用路径。
3. 备份后应用清单内配置并通过 Linux 前端部署；核对完整雾凇、Lua、OpenCC 和模型依赖。第三方刷新只覆盖配置中指定的词典，单独验收下载、哈希及失败保留旧版本。
4. 为 Ubuntu 使用其自身 Rime installation_id 和独立服务端令牌，沿用同一用户 hx；不要复制 Windows/Mac 凭据或设备 ID。私有云配置可使用 `remote.local.json`，显式传给单次运行及服务安装。当前服务端范围包含 7 个配置（含 squirrel 补丁）及 luna_pinyin、rime_ice；新增范围先对齐服务端。
5. 验收真实 HTTPS 拉取、三方冲突保留、回传、网络恢复及重复请求；配置始终先合并到 `config/`。保留所有设备现有数据，不用整份选边掩盖冲突。
6. 先在隔离目录验证原生快照合并与重复词频，再验收实际 Linux 前端的全量原生入口。如实现无人值守包装器，遵守前述空闲、限频、真实完成凭据及失败禁止上传约定；不能把异步通知退出码 0 当成功，不直接操作活动数据库。
7. 验收 systemd 用户服务的安装、更新、卸载、单实例、异常重启及实际登录启动；最后一次配置部署后由用户确认 Linux UI 和输入体验。Windows/macOS 外观补丁不能替代 Linux 前端外观配置。

交接时分开报告配置应用、快照传输、原生导入、后台运行与 UI。更新本文验证记录和 README 使用方式；服务端有变更时同步维护 server/README。Mac 尚未交付无人值守原生包装器、未实测登录启动；VPS 定期备份也仍未配置，这些不应被 Linux 验收默认为已完成。


### macOS 公网与原生合并续验（2026-11-10）

网络恢复后，本机使用独立设备身份完成 VPS 接入；此前 SSH 超时阻塞已解除。服务端保留 Windows 设备，备份设置后添加 Mac，并将 `squirrel.custom.yaml` 加入配置范围；重建容器加载新设置，最终健康检查通过。凭据仅在私有 `device.local.json`，云配置为私有 `remote.local.json`，两者权限 0600 且被 Git 忽略；仓库示例 `remote.json` 继续默认禁用。

- HTTPS 证书校验成功；未认证请求返回 401，Mac 认证返回其自身设备身份。首次核对版本 15，6 个共享配置仅存在 LF/CRLF 差异，备份后按远端字节对齐；鼠须管补丁为新增文件。首次提交版本 16，后续 Windows 与 Mac 交换后的最终核对版本为 18。
- 通过鼠须管自身 `Squirrel --sync` 合并接收的 Windows 快照，再请求重新部署。专属本轮日志包含两个词典的同步及 `3 tasks ran: 3 success, 0 failure`；两个本机快照均新生成且通过元数据校验。不直接打开或复制活动数据库。
- 最终 7 个配置在 `config/`、实际目录及 HTTPS 返回值间逐字节一致；本机 `luna_pinyin`、`rime_ice` 快照与服务器一致，导出词条覆盖 Windows 快照词条。随后重复 HTTPS 同步保持版本 18。多次原生合并词频不变的验证仍以隔离验收脚本为证据，不把线上有其他设备写入时的版本变化解释为幂等失败。
- LaunchAgent 已安装并运行，参数显式使用 `--remote-config /Users/hx/rime-config/remote.local.json`，每 60 秒检查云同步、失败后 30 秒重试；本地轮询间隔 5 秒。正式设备身份与令牌不放进服务参数。
- 本轮完成的是 **Mac/VPS 配置与快照端到端 + 手动触发的真实原生合并**。后台模式仍为 `snapshots-only`，未安装无人值守 macOS 原生包装器；新学习数据导出和接收快照导入仍需触发“同步用户资料”。UI 已在最后一次应用与重新部署后由用户确认通过（2026-11-10）；注销登录自动启动仍未实测。

私有证据在 `private/macos-acceptance/result.json`、`native-remote-merge.log`，源配置备份在同目录 `config-before-*`，实际目录备份由客户端状态目录保存。服务端设置和清单备份后缀为 `.macos-backup-*`。这些证据及备份不提交 Git。原生入口参考 [Squirrel 命令入口](https://github.com/rime/squirrel/blob/master/sources/Main.swift) 和 [同步调用实现](https://github.com/rime/squirrel/blob/master/sources/SquirrelApplicationDelegate.swift)；`--sync` 本身是异步通知，不能仅以退出码 0 判定导入成功。

### 合并远端后的 macOS 复验（2026-11-10）

已将 `origin/main` 的 4 个提交快进合并至 `7cbbe68`，保留本地鼠须管补丁、同步清单及此前验收记录。Windows 使用远端新增的竖排圆角样式，macOS 继续保留此前横排矩形样式，不自动跨前端迁移外观。

- 回归 106 项：101 项通过，5 项 Windows PowerShell 专用测试跳过。通过鼠须管 Frameworks 下的 librime 和 Lua 插件加载实际 Lua 测试，未跳过该项。日志：`/private/tmp/rime-macos-merged-tests.log`。
- 新增 `tests/macos_native_acceptance.py`：调用鼠须管 `rime_dict_manager`，仅在新建隔离目录验证两个词典的快照恢复、双设备合并、范围限制和多次重复合并词频不变。全部通过，未访问活动数据库。Windows 的 ctypes 验收脚本依赖 `RimeSetup` 导出符号，不能直接用于本机鼠须管动态库；本轮不将其计为 macOS 引擎验收通过。
- `--dry-run`、`--plan-json`、launchd 安装预览通过。实际重新安装并启动新版 LaunchAgent 后状态为 running，`workflow-result.json` 记录 macOS 配置应用与第三方检查成功；云同步和词典交换因尚未配置而跳过。
- 最后一次应用后，7 个清单内配置逐字节匹配实际目录；`rime_deployer --build` 与 `Squirrel --reload` 均返回 0，生成配置中的横排及明暗主题存在。UI 按用户要求留待其在此后验收；注销登录自动启动未复验。
- 已获用户授权为 Mac 注册独立 VPS 凭据并启用同步。首次 SSH 查询显示生产容器 healthy；随后 SSH 密钥交换超时，HTTPS 请求也超时，注册命令未完成。本地仅生成了私有候选凭据，未写入正式 `device.local.json`，`remote.json` 保持禁用；不能声称 Mac 已接入公网。已停止本轮滞留 SSH 请求。网络恢复后需先核对服务端设备及范围，再继续注册和同步。
- 实际学习词典的在线原生导入、无人值守 macOS 包装器及 Mac/VPS 端到端仍未完成，隔离快照测试不替代这些验收。

复现隔离原生验证：

```bash
python3 tests/macos_native_acceptance.py \
  --manager '/Library/Input Methods/Squirrel.app/Contents/MacOS/rime_dict_manager' \
  --workspace /private/tmp
```

### macOS 实机验收进度（2026-11-10）

本轮在 macOS 27.2、Python 3.9.6 上完成以下检查；尚未完成全量验收：

- 使用 `TMPDIR=/private/tmp` 运行 76 项测试，全部通过。Lua 测试需先用 `ctypes.CDLL` 全局加载鼠须管 `Contents/Frameworks/librime.1.dylib`，再将测试库发现指向 `rime-plugins/librime-lua.dylib`；普通 unittest 命令仍可能跳过该项。系统默认临时路径包含 `/var` 符号链接，会被当前路径安全检查拒绝；测试使用真实目录，不放宽符号链接保护。本轮完整测试日志保存在 `/private/tmp/rime-macos-full-tests.log`（临时文件）。
- 自动发现 `~/Library/Rime`，个人配置应用成功并保留修改前备份；实际目录原有万象模型配置由项目内对应配置接管。
- 真实 GitHub 检查及词典校验成功，上游提交为 `99662ba01e3affa6a0f009174ca530b887bac3b6`，目标词典已是该版本。本轮未验证真实下载失败后的恢复。
- 用户级 `local.rime-config` LaunchAgent 的安装、更新、卸载、重装通过。模拟 SIGKILL 后自动重启，启动次数由 1 增至 2，最终为 running，后台错误日志为空；尚未验证注销登录自动启动。
- 鼠须管自带 `rime_deployer --build` 返回 0；生成配置包含 9 候选、`hx_preferences` 处理器及万象模型设置。这不代表真实输入体验已验收。
- 用户已启用并切换到鼠须管，确认能输入中文；实际 UI 验收由用户负责。自动按键未触发候选，不据此判定输入法故障；快捷键、外观等不计为终端验收通过项。
- 使用鼠须管自带 `rime_dict_manager` 在 `/private/tmp` 隔离目录中完成测试词典导入、导出和原生快照恢复。`luna_pinyin`、`rime_ice` 均验证保留两个模拟设备的词条，重复恢复后的导出内容（含词频）一致；原生快照通过客户端格式校验，双设备目录交换及重复交换通过。未操作实际活动数据库，未安装无人值守原生同步包装程序，实际学习数据导入仍未验收。
- `remote.json` 仍禁用且地址为占位符，真实 VPS、TLS、设备鉴权和跨设备词典合并尚未验证，需要实际服务地址及设备凭据。

随后按用户要求通过 `ssh proxy_jp` 只读提取真实 VPS 同步数据库中用户 `hx` 的 revision 3 配置，并备份后覆盖本地 `config/` 的 6 个范围内文件，再应用到 `~/Library/Rime`。两处文件均逐字节匹配远端快照；差异仅为远端 CRLF 换行。原生部署通过，同步服务已恢复 running。源文件备份及远端版本记录保存在私有 `private/remote-overwrite/backup-20261110-050912/`，实际目录旧文件由客户端另行备份。本次 SSH 单次覆盖没有注册设备、启用 HTTPS 同步或修改远端数据，不能据此认定公网 API 和词典端到端验收通过。

以下命令均从仓库根目录执行：

```bash
# 无第三方 Python 依赖的应用/协议/客户端测试
python3 -m unittest discover -s tests -v
# 从仓库根目录构建测试镜像；运行时不需要网络或真实令牌
docker build -f server/Dockerfile --target test -t rime-config-test:local .
docker run --rm --network none --read-only --tmpfs /tmp rime-config-test:local
```

上述自动测试通过 WSGI 应用真实走鉴权、SQLite、版本校验，再驱动两个客户端进行配置拉取/合并/回传和词典快照交换；不连接真实 VPS 或 Rime 数据库。远端部署时 Debian/Python 3.13 测试镜像完成 85 项：79 通过、6 项跳过；后续加入全量原生流程后，Windows 调度改进后的最新回归共 99 项：92 通过、7 项因符号链接权限跳过。真实公网及 Windows 原生 /sync 验收另见下文；其他平台实机验收仍待完成。


测试使用临时目录，覆盖配置备份、幂等性、目标漂移修复、受控删除、旧管理范围迁移、只读计划、符号链接与路径校验、失败回滚、平台路径检测，以及个人词典快照的双向交换、元数据校验、备份和原生同步钩子顺序。不会修改真实输入法配置。

## Windows 验收总结

**结论：本轮 Windows 原生支持验收完成，用户已确认接受。** 验收环境为 Python 3.14.0、小狼毫 0.17.4、librime 1.13.1，日期为 2026-11-10。终端测试由自动化执行，实机 UI 由用户手动负责；公网 VPS 不在本轮范围。

### 已验证能力

| 项目 | 结果与证据 |
| --- | --- |
| 目录与路径 | 自动发现当前用户 Rime 目录；UTF-8、中文路径、Windows 非法名称及范围校验通过 |
| 文件与并发安全 | 原子写入 ACL、跨进程锁争用和释放通过；真实 junction 穿越被拒绝，目标文件未变化 |
| 配置应用与恢复 | 清单内 6 个文件应用后逐字节匹配 config；测试前备份、应用备份和恢复验证通过，测试收尾时 23 个受管理文件 SHA-256 与原件一致 |
| Windows 任务生命周期 | 真实安装、更新、查询、卸载通过；无效目标及身份参数不影响卸载；注册后注入失败能恢复旧 XML 和原运行状态 |
| 自动恢复与单实例 | 实机发现仅设置 RestartOnFailure 未能恢复，已补每分钟重复触发器；再次故障注入后自动拉起，IgnoreNew 保持单实例 |
| 第三方词典 | 从 GitHub 同一提交 `99662ba01e3affa6a0f009174ca530b887bac3b6` 下载并校验 17 个文件，与本机已有版本一致 |
| 原生同步与快照交换 | 小狼毫原生同步成功，日志确认快照合并及导出；两份真实快照发布、接收内容一致，重复传输无变更 |
| 隔离原生合并 | 本机 DLL 在新建目录执行真实 Levers restore/backup；逐词典范围、两个模拟设备合并及多轮重复导入通过，记录和 c/d/t 字段稳定，不接触活动数据库 |
| Lua 与输入引擎 | 使用本机 DLL 的 Lua API 验证偏好处理器；隔离引擎的雾凇/朙月中文候选、9 候选页、英文候选、Ctrl+Space 去分隔符提交及切换通过 |
| 自动测试回归 | 共 85 项：78 通过，7 因 Windows 符号链接创建权限不足跳过；真实目录联接防护另有测试通过 |

### 最终运行状态

测试阶段已恢复原文件并移除临时任务。随后用户自行安装服务并报告已重新启动；最后一次只读检查确认：

- 当前用户任务为 `Running`，只有 1 个 `pythonw.exe` 同步进程。
- 进程创建时间为 04:11:07，日志持续更新至 04:12:46；第三方词典检查成功，已是当前版本。
- 登录触发器和每分钟恢复触发器均已启用。
- 此次 Windows 验收结束时尚未配置服务端，日志明确跳过个人词典交换；随后已完成下文公网部署，当前后台已启用远端同步。

任务历史日志未启用，因此未通过事件记录独立证明本次进程由登录触发器启动。用户基于重启后的运行检查确认本轮验收完成；此结论不将触发来源描述为已审计，也不把之前“测试任务已卸载”的状态当作最终安装状态。

### 已知限制与后续工作

- 部署仍有 melt_eng / radical_pinyin 循环依赖及全局 grammar.yaml 缺失警告。有效拼写规则能够生成候选，日志确认 wanxiang-lts-zh-hans 模型加载成功，隔离引擎无 ERROR 日志；本轮接受该已知状态，未修改清单外方案来消除警告。
- 活动输入期间的快照变化不能用于判断原生合并幂等性；该项结论来自隔离词典、多设备快照和重复导入测试。
- `windows_native_acceptance.py --worker` 仅为隔离验收钩子，不是生产逐词典同步包装器。小狼毫 0.17.4 的 `/sync` 是全量原生同步，不能直接充当 `{dictionary}` 钩子。
- Windows 生产原生 /sync 已在后续工作中完成；macOS、Ubuntu、WSL 原生入口配置及实机验收仍待进行。真实 VPS 的 Caddy/TLS/鉴权联调已完成；Windows 本轮完成不等于全平台云同步已端到端交付。

### 复现与证据

在仓库根目录执行，DLL 路径按实际安装位置调整：

```powershell
$env:RIME_TEST_DLL = 'C:\Program Files\Rime\weasel-0.17.4\rime.dll'
python -X utf8 -m unittest discover -s tests -v
python -X utf8 tests/windows_native_acceptance.py --dll "$env:RIME_TEST_DLL" --workspace private
python -X utf8 tests/windows_engine_acceptance.py --dll "$env:RIME_TEST_DLL" --source "$env:APPDATA\Rime" --workspace private
python client/sync.py --service status
```

两个独立验收脚本在 workspace 下创建新目录：原生测试使用合成词条，引擎测试复制方案、资源与构建产物，不复制活动数据库。结果写入各目录的 result.json。测试钩子拒绝没有隔离测试标记的目录。

| 私有证据位置 | 内容 |
| --- | --- |
| `private/live-native/` | 实机测试前备份、状态及快照交换记录 |
| `private/native-acceptance-qq3vr6eb/result.json` | 隔离原生合并及词频幂等性结果 |
| `private/engine-acceptance-c7uvb59b/result.json` | 真实输入引擎结果；同目录 logs 保存模型加载证据 |
| `private/live-test/terminal-final-tests.log` | 85 项自动测试结果 |
| `%LOCALAPPDATA%/rime-config/logs/service.log` | 当前已安装服务的运行日志 |

私有证据不入 Git，不在文档或日志中展开个人词条及凭据。原生 API 依据 [librime Levers API](https://github.com/rime/librime/blob/1.13.1/src/rime_levers_api.h)；小狼毫原生同步行为见 [0.17.4 Configurator](https://github.com/rime/weasel/blob/0.17.4/WeaselDeployer/Configurator.cpp)。

## 跨平台计划与执行

2026-11-10，参考 WSL `~/dotfiles` 的共享计划、平台执行器及执行前复核模式，拆分 Rime 客户端的决策与平台副作用。配置仍从 `config/` 复制应用，未引入 dotfiles 的硬链接管理方式。

- `client/plans.py`：纯数据决策，生成配置文件、原生维护、工作流计划；校验版本、动作与依赖，并分派固定工作流阶段。
- `client/sync.py`：观察配置与目标，生成指纹计划；远端合并后重新规划，备份前及写入前复核源与目标指纹，发现变化停止。原有锁、备份及恢复机制保留。
- `client/native_sync.py`：采集元数据、快照指纹与持久化调度状态，调用公共计划判断限频、无变化、重试和空闲条件；仍负责范围约束、完成校验及失败快照隔离。
- `client/platform_execution.py`：Windows 调用小狼毫、输入空闲探测及计划任务；Unix 调用原生包装器及完成凭据约定，分派 systemd 或 launchd。`client/unix_service.py` 保存从公共服务入口提取的 Unix 安装与恢复逻辑；`client/service.py` 保留公共参数和模板规则。

计划 JSON 顶层字段固定为 `kind/version/platform/steps`，版本为整数 `1`，平台为 `windows/wsl/linux/macos`。每步固定为 `id/action/reason/requires/details`，依赖只能引用前置步骤。契约由 `plans.validate()` 校验，未知类型、版本、动作及非法依赖在分派前拒绝。

| kind | 动作 | details |
| --- | --- | --- |
| configuration-plan | create / replace / delete / skip | before、after 为 SHA-256 或 null，动作必须与指纹一致 |
| native-plan | execute / defer / skip / observe | last_success_at；observe 表示尚待运行时空闲探测 |
| workflow-plan | evaluate / skip | 后端选择、只读本地预览及远端合并后重建提示 |

工作流顺序固定为远端同步、本地配置应用、共享目录词典交换、第三方刷新。启用远端时配置应用依赖其成功；第三方刷新独立调度。原生维护延后不阻止安全的配置同步。调度器只调用代码注册的固定处理器，不读取并执行磁盘上的计划，也不从计划解析 shell 命令。

`--plan-json` 是独立只读操作，不联网、不启动原生入口、不写状态或路径记忆；发现的新词典仅用于预览，不回写清单。配置预览只描述当前本地观察，远端 CAS、网络重试和真实空闲判定仍由执行阶段完成。实际运行保存 `workflow-plan.json` 和版本 1 的 `workflow-result.json`，结果状态包括 pending、success、skipped、deferred、blocked、failed；开始执行先写 pending，异常中止记录失败及未执行阶段，避免沿用旧成功记录。原生计划保存于 `native-all/plan.json`，配置计划随备份事务日志保存。

本轮回归共 106 项：Windows 99 通过、7 跳过；WSL 101 通过、5 跳过。新增验证涵盖四平台决策一致性、非法契约拒绝、依赖失败传播、异常结果记录、平台服务分派、执行前指纹变化保护及 JSON 预览只读性。证据分别为 `private/plan-refactor-tests.log` 与 WSL `/tmp/rime-plan-tests.log`。这些测试不代表已完成 macOS 或 Unix 真实输入法包装器验收。

Windows 已重新安装并启动当前用户后台任务，新版 `workflow-result.json` 确认配置检查成功，日志确认真实云同步完成至版本 13；原生维护因 interval 延后，未因重启绕过冷却策略。

## 公网部署与同步验收

2026-11-10，按用户授权通过 SSH `proxy_jp` 部署到 Debian 13。服务位于 `/home/hx/rime-config/server`，容器 `rime-config-app-1` 健康运行，以 UID/GID 10001、只读根文件系统、移除全部 capabilities 运行，重启策略为 `unless-stopped`。复用 `caddy-public` 网络及现有 Caddy，增加 `/rime/*` 路由；没有发布应用宿主机端口，没有新建公网代理。实际接口为 `https://198.13.57.54:8443/rime/v1/state`，客户端使用默认 CA 证书验证，没有跳过 TLS 校验。

部署修复包括 Gunicorn 的绝对配置路径，以及 Docker 构建上下文允许 Windows 服务 PowerShell 脚本进入镜像，以便跨平台测试读取。代码归档最初保留了过严权限，已调整源码读取权限，私有设置仍为 `0600`。测试镜像在无网络、只读根目录下完成 85 项测试：79 通过、6 项跳过；运行镜像另通过真实启动、健康检查及容器重建验证。

### 真实 HTTPS 验收结果

两个隔离客户端使用合成配置和词条，通过 Windows 发起真实 HTTPS 请求；第三个测试设备属于另一用户。以下 14 项检查通过：

1. 默认 TLS 验证及原有站点根路径返回 200。
2. 无效令牌返回 401；收尾另确认无令牌请求返回 JSON 401 和 `private, no-store`。
3. 第三方文件超出个人范围被拒绝（403）。
4. 伪造其他设备的词典快照被拒绝（400）。
5. 两客户端配置拉取及逐词典快照双向交换成功。
6. 不同文件的并行修改三方合并，不丢失任一修改。
7. 同文件冲突保留双方内容并停止提交；仅对合成测试数据显式选择后收敛。
8. 过期服务端版本被 CAS 拒绝（409）。
9. 实际 PATCH 已成功后注入响应丢失，待确认提交保留，重试不重复推进版本。
10. 注入客户端离线错误，未上传修改保留，恢复真实 HTTPS 请求后同步成功。
11. 持久化删除标记传播到另一客户端。
12. 重复同步保持版本与快照内容不变。
13. 不同用户数据隔离。
14. 容器强制重建后数据及版本保持不变。

私有结果文件共记录 14 个 PASS。故障注入不等于实际切断 VPS 网络；快照字节幂等性也不等于原生数据库词频合并验收。未使用第二台真实输入法设备，跨设备场景为两个隔离客户端目录。

### 生产接入与收尾

- 服务端仅保留 Windows 正式设备。设备令牌经 SSH 在进程内传递，通过 `--token-stdin` 初始化到 Git 忽略的 `device.local.json`，未写入服务参数、URL 或日志。
- 初始化期间暂时禁用并停止 Windows 任务，完成后启用并启动。`remote.json` 已启用，周期 60 秒、失败重试 30 秒；当前任务 `Running`，单个 `pythonw.exe`，服务日志确认版本 1 同步成功。
- 服务端版本 1 包含清单内 6 个个人配置文件及 `luna_pinyin`、`rime_ice` 两份本设备快照；服务端配置与 `config/`、实际 Rime 目标逐字节一致，服务端快照与本机已导出快照逐字节一致。第三方资源未进入个人服务端。
- 三个测试令牌均已撤销并实测返回 401；两个合成测试用户的数据库状态已清除，正式用户数据前后保持一致。
- SQLite backup API 生成一致备份，`integrity_check` 返回 `ok`。卷内 `/data/backups/accepted-20261110.sqlite3` 和 VPS `server/backups/accepted-20261110.sqlite3` 保留私有副本；未配置周期备份或执行破坏性恢复演练。
- 此次公网部署验收阶段为 `snapshots-only`；后续已接入下文的 Windows 原生全量同步，当前模式为 `native-all`。

私有证据：`private/https-acceptance-lqz64pff/result.json`（HTTPS 测试），`private/deploy/production-result.json`（真实文件及快照核对），`private/deploy/final-result.json`（撤销、清理及安全检查）。部署与验收脚本位于 `private/deploy/`，不入 Git；其中初始化脚本要求空远端状态，不能直接在已运行的生产账号上重复执行。远端单元测试记录位于 `/tmp/rime-tests.log`，临时目录日志不作为长期备份。
