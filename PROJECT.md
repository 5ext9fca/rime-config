# 项目技术说明

本文面向开发与维护人员，记录实现边界、数据流程和验证方式。日常使用见 [README](README.md)，公网部署与备份见 [服务端指南](server/README.md)，协作约定见 [AGENTS.md](AGENTS.md)。

## 当前交付状态

截至 2026-11-10，Windows 原生客户端及真实 VPS 已完成验收。本机当前用户计划任务单实例运行，每 60 秒通过现有 Caddy HTTPS 同步。6 个个人配置文件、2 份词典快照核对通过；后续已按用户要求接入原生 `/sync` 自动合并、导出及回传，模式为 `native-all`。Windows 和 Unix 共用全量词典范围补齐规则；Unix 原生包装器配置及实机验收不在本轮范围。详细证据见 [Windows 验收总结](#windows-验收总结)、[公网部署与同步验收](#公网部署与同步验收) 和 [原生全量同步](#原生全量同步)。

macOS 已完成配置与快照 HTTPS 端到端、内置无人值守原生合并及失败恢复；UI 和登录启动此前已由用户确认。新入口及本轮证据见 [macOS 新入口与内置维护续验](#macos-新入口与内置维护续验2026-11-10)。Ubuntu 已完成真实锁屏触发的内置全量同步、重新部署及 HTTPS 回传，后台为 native-all。当前仅支持 Windows 原生、macOS、原生 Linux，WSL 已移除；不实现异机备份。

## 代码与数据边界

| 位置 | 职责 |
| --- | --- |
| `rime.py` | 命令入口、周期调度、本地配置应用与备份 |
| `client/config/paths.py` | 跨平台目录发现与私有路径记忆 |
| `client/services/service.py` | 跨平台服务入口，systemd / launchd 用户服务管理 |
| `client/platforms/windows/windows_service.py`、`client/windows_service.ps1` | Windows 当前用户计划任务的注册、查询、卸载与恢复 |
| `client/platforms/windows/windows_runner.py` | pythonw 后台入口与 UTF-8 日志 |
| `client/storage/file_lock.py`、`client/platforms/windows/windows_security.py` | 跨进程文件锁及 Windows 私有文件 ACL |
| `client/config/identity.py` | 安装 ID 与设备令牌初始化 |
| `client/core/scope.py` | 个人配置及词典范围校验 |
| `client/remote.py` | HTTPS 同步、三方比较、版本提交与恢复 |
| `client/application/dictionaries.py` | 原生个人词典快照交换与应用钩子 |
| `client/maintenance/native_sync.py`、`client/platforms/windows/weasel_sync.py` | 跨平台全量范围补齐、完成凭据、Windows 原生 /sync 与恢复检查 |
| `client/providers/third_party.py` | 第三方词典下载、校验与刷新 |
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
| 个人词典应用 | 采集本机学习数据，与远端数据合并，通过 Rime 原生机制更新实际用户词典 | Windows 原生 /sync 已接入后台，按全量范围合并导出并验证；Ubuntu 和 macOS 已启用内置全量同步并完成实机合并、导出及 HTTPS 回传 |
| 后台自动运行 | 当前用户登录后持续同步，支持失败恢复 | Windows 当前用户计划任务已验收；macOS launchd 运行、异常重启及注销后登录启动验收完成（登录项由用户确认）；Linux systemd 生命周期及真实登录触发已验收 |
| 第三方词典刷新 | 按独立周期拉取指定上游词典，校验后更新本机副本 | 已实现项目配置驱动的 GitHub 词典刷新，默认雾凇拼音 |

`config/` 继续作为本地配置应用的唯一权威来源：服务端同步先合并更新此目录，再向输入法目录应用。配置编辑发生在 `config/`；实际目录中的配置修改不会自动反向采集。自动学习词典从实际输入法产生，使用独立的数据同步流程。

服务端提交必须携带基线版本，避免并发客户端相互覆盖；冲突、离线和上传失败时保留本地未上传内容，重试后再推进成功同步版本。配置合并成功、服务端提交成功、本地应用成功应分别记录，失败后可从对应阶段恢复。不能将本地快照交换成功等同于服务端同步或词典导入完成。

第三方词典采用独立的上游清单、刷新周期和版本记录；在暂存目录下载及校验后更新受管理文件，失败保留旧版本。个人配置、短语和个人词典不受刷新覆盖。该职责不自动包含第三方方案、Lua、OpenCC 或模型升级。公网服务地址与同步周期由 `remote.json` 配置，本机安装 ID 和设备令牌保存在私有 `device.local.json`；第三方上游清单见 `third-party.json`。


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

目录选择优先级为：`--target` → 当前平台的路径记忆 → `device.local.json` 的 `target` → `paths.json` 候选路径。正常运行和成功初始化也会记住选择，`--dry-run` 始终不写记忆。此后直接运行 `--watch` 即可复用。与此前行为不同，显式 `--target` 会成为后续默认目标；使用临时目录验证时可同时指定临时 `--paths-state`。

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

刷新后需在 Rime 中重新部署才能加载新词典，本工具会提示但不自动重启或部署输入法。Windows 已完成真实 GitHub 下载校验和本机重新部署验证；模拟上游测试覆盖哈希异常、下载中断、回滚与周期行为。macOS 等其他平台的实机部署效果仍待验证。


## 自动学习个人词典

本工具从 Rime 原生生成的 `<sync_dir>/<installation_id>/*.userdb.txt` 中仅交换项目清单内词典，保留词条、词频和元数据。每台设备只发布自己的快照，接收其他设备的快照；不传播文件删除，不直接操作正在使用的 `*.userdb` 数据库。词典合并由 Rime 完成，参见 [Rime 同步说明](https://github.com/rime/home/wiki/UserGuide#同步用戶資料) 和 [原生快照恢复/合并实现](https://github.com/rime/librime/blob/master/src/rime/lever/user_dict_manager.cc)。

启用方法：

1. 查看本机 `installation.yaml` 中的 `installation_id`。每台设备必须唯一，不能克隆同一 ID。本工具不改写该文件。
2. 在 Rime 菜单中执行“同步用户资料”，等待完成，以生成本机快照。
3. 指定私有交换目录和本机 ID，运行服务：

```bash
python3 rime.py --watch --interval 10 \
  --target /mnt/c/Users/hx/AppData/Roaming/Rime \
  --device-id 09ad77e5-8a8d-45b8-97f3-b2893bd56e5b \
  --dictionary-store /path/to/private-rime-dictionaries
```

以上为可选的共享目录模式：各端使用同一个共享目录，或由独立云盘同步其内容。公网 VPS 模式请启用 `remote.json`，不要同时传入 `--dictionary-store`。只允许同步快照文件，不同步原生 `sync/` 目录中附带备份的配置或第三方文件。可在仓库内用 `private/dictionaries/` 作为本地暂存目录，`private/` 已被 Git 忽略；不同设备的本地暂存目录不会自动联网互通。

默认原生同步目录为目标下的 `sync/`；若 `installation.yaml` 设置了 `sync_dir`，须用 `--rime-sync-dir` 指向实际目录。`--device-id` 须与本机快照中的 `/user_id` 一致，程序会检查收到的快照设备标识及词典名。

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
- 调用前后再次检查范围；运行期间出现新词典时补齐清单并停止本轮上传。内置全量同步现在会先安全初始化清单内远端独有词典，再执行前端全量同步；自定义包装器未处理的新名称仍报告尚未导入，不把复制成功计为合并成功。
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

**UI 验收结论（2026-11-10）：用户确认通过。** 最终版本为竖排 9 候选、14 号字、系统毛玻璃与 E6 明暗底色、窗口圆角 12、高亮圆角 7、高亮阴影 12；撤销行距 18，继承默认行距 5。首尾候选的额外扩展保留鼠须管原生行为。此结论仅覆盖 UI，不改变无人值守原生包装器等未完成项；登录启动后续已由用户确认完成。以下历史阶段记录保留原时间点状态。

`config/squirrel.custom.yaml` 已按当前 Windows `weasel.custom.yaml` 重新生成（2026-11-10）：竖排候选列表 `candidate_list_layout: stacked`，文字方向保持 horizontal；候选、序号、注释字号均为 14，候选数量沿用通用配置的 9 个。窗口圆角 12、高亮圆角 7；明暗背景沿用 ABGR 的 `0xe6ffffff` / `0xe6000000`，约 90% 不透明，文字与绿色高亮保持不透明。颜色使用 sRGB，标签高亮字段映射为 `hilited_candidate_label_color`，普通候选及预编辑背景透明。

鼠须管 `shadow_size: 12` 表示候选高亮阴影，不能与 Windows 窗口阴影半径、偏移和阴影色逐项等价；不添加前端不支持的 Windows 字段。`translucency: true` 启用系统毛玻璃，保留 E6 alpha 明暗底色及不透明文字。旧补丁已备份到私有 `private/macos-acceptance/squirrel-before-*`。实际目录已应用，`Squirrel --reload` 后检查生成的 `build/squirrel.yaml` 确认竖排、圆角、阴影和背景 alpha 正确，UI 已于 2026-11-10 由用户确认验收通过。通用 `rime_deployer --build` 成功并不代表前端 `squirrel.yaml` 已重编译，应在前端 reload 后检查。

首尾候选扩展：用户已要求撤销 `line_spacing: 18`，补丁不再覆盖行距，当前继承默认值 5。鼠须管 1.1.2 在竖排高亮路径中直接为首尾追加边距，并将边界扩展到外框，没有 YAML 开关可单独禁用。`surrounding_extra_expansion` 调整的是非选中候选背景相对大小，不是首尾扩展开关。配置只能通过调整圆角、边距、行距间接平衡；要在保留当前其他尺寸的同时真正取消此行为，需要修改前端绘制代码并重新构建。此次仅回滚行距、开启原生毛玻璃，保留其他几何参数；首尾差异可能恢复。

原生效果（鼠须管 1.1.2）：背景色 alpha 支持普通透明；`translucency: true` 使用 AppKit `NSVisualEffectView`（behindWindow / hudWindow）实现系统毛玻璃，当前已开启；`style/alpha` 会影响整个面板，当前保持默认 1。窗口本身通过 `NSPanel.hasShadow = true` 使用系统阴影；`shadow_size` 则是另外的 Core Animation 高亮阴影，黑色、不透明度 0.2，偏移随尺寸推导，不能由 YAML 独立指定 Windows 的阴影色和偏移。依据 [SquirrelPanel](https://github.com/rime/squirrel/blob/1.1.2/sources/SquirrelPanel.swift) 和 [SquirrelView](https://github.com/rime/squirrel/blob/1.1.2/sources/SquirrelView.swift)。

鼠须管 `border_width`、`border_height` 控制边距，不能等同小狼毫描边宽度；当前均为 1。字体设为空以使用系统回退；当前 UI 已获用户验收，不保证两端逐像素一致。保留原来的行内预编辑与应用选项；Windows `.exe` 名单不属于本次外观迁移。

2026-11-10 已应用到实际目录，通过鼠须管原生部署器编译并检查生成的 `build/squirrel.yaml`，随后执行官方 `Squirrel --reload` 请求前端重新部署。原目录无 `squirrel.custom.yaml`，本次新增补丁，不覆盖基础 `squirrel.yaml`。实际 UI 验收由用户完成。首次迁移时未上传；后续已扩展真实 VPS 清单并完成 HTTPS 同步，见公网续验记录。

字段参考：[鼠须管官方配置](https://github.com/rime/squirrel/blob/master/data/squirrel.yaml)。


### 明确不实现的功能

按用户决定，不实现自动新设备注册和恢复向导，也不将二者列为待办。设备继续由维护者在服务端配置独立身份与令牌，客户端 `--init` 只保存本机身份。服务端恢复后的数据核对及客户端基线重建继续采用文档化的人工流程；保留现有版本回退检测、备份与安全重试保护。

## 自动系统服务注册

入口为 `rime.py --service install|uninstall|status`，实现集中在 `client/services/service.py`。操作用户级服务，不申请系统管理员权限。Windows 原生走当前用户计划任务分支；Ubuntu 走 Linux systemd 分支；macOS 走 launchd 分支。

- Windows：`client/platforms/windows/windows_service.py` 将 JSON 载荷编码后交给 `windows_service.ps1`，通过 ScheduledTasks 注册 `rime-config-<当前用户 SID>`。Interactive 登录类型、Limited 权限、该用户登录触发，无需密码或令牌进入任务定义。采用 IgnoreNew、无执行时限、电池供电继续运行、失败每分钟重试（最多 999 次），并增加每分钟重复触发器，补偿实机中 RestartOnFailure 未触发的情况；运行中忽略新触发。原生 `pythonw.exe` 直接运行 `windows_runner.py`，在同一任务进程运行客户端并捕获 UTF-8 日志，停止任务即停止客户端。安装先离线预检查，更新前导出旧 XML；失败恢复旧定义与原运行状态，新安装失败删除新任务；无管理标记的任务拒绝覆盖及卸载。查询和卸载不依赖项目同步配置。预览不访问任务计划程序。
- Windows 日志为 `%LOCALAPPDATA%\rime-config\logs\service.log`；启动时若超过 10 MiB 保留一个 `.1` 文件，运行中不轮转。计划任务是登录会话内的自动运行机制，不是 SCM 系统服务，用户未登录时不运行。安装成功不等于同步已成功。
- Windows 原生路径通过 `%APPDATA%\Rime` 发现；旧三平台 `paths.json` 兼容补入此默认候选。旧 WSL 路径记忆不再使用。所有客户端 JSON 读取显式使用 UTF-8，清单继续使用 `/` 分隔；拒绝 Windows 设备名、备用数据流、尾随空格/点和目录联接等重解析路径。
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

自动测试覆盖三类服务的安装、更新、卸载、注册失败恢复、参数处理和只读预览；Windows 另完成真实任务生命周期及故障恢复测试。Ubuntu systemd 实机运行及登录触发已验收；macOS launchd 运行、异常重启已验收，注销后登录启动由用户确认完成。

## 开发与验证

### Ubuntu / Linux 实机验收（2026-11-10）

环境：Ubuntu 26.04.1 LTS（原生 Linux 7.0.0-43-generic，KDE Wayland）、Python 3.14.4、Fcitx5 5.1.19、fcitx5-rime 5.1.13、librime 1.16.1。实际目录为 `~/.local/share/fcitx5/rime`。首次发现暴露候选目录遗漏，已增加 `{xdg_data_home}/fcitx5/rime` 与 `XDG_DATA_HOME` 模板支持，保留既有候选及多目录显式选择规则。

- 自动回归 107 项：102 通过、5 项平台条件跳过。只读 `--dry-run`、`--plan-json` 和服务安装预览通过。新增 XDG 数据目录环境变量及默认值测试。
- 配置应用：7 个范围内文件在 `config/`、实际目录和 HTTPS 返回值间逐字节一致。首次接入的 6 个文件仅 CRLF/LF 不同，逐一验证内容等价并备份后对齐服务端字节，没有整份冲突选边。实际目录旧文件由客户端备份；未修改无关个人补丁。
- 原生部署：通过 Fcitx5 D-Bus `SetConfig` 的 `fcitx://config/addon/rime/deploy` 入口部署；构建结果包含 9 候选、`hx_preferences` 和万象模型。雾凇方案、Lua、OpenCC、模型及 librime Lua/octagram 插件存在。用户反馈“输入正常，UI为默认”，未配置 Linux 专属外观。
- 第三方词典：真实下载并按 Git blob 校验，锁定提交 `99662ba01e3affa6a0f009174ca530b887bac3b6`，17 个受管理文件最终哈希一致。隔离目录另验证真实下载、离线失败及损坏下载保留旧文件/成功凭据、恢复重试和个人短语保留。
- HTTPS：沿用用户 hx，注册 Ubuntu 自身 installation_id 的独立令牌，私有配置为 `device.local.json` 与 `remote.local.json`。已备份服务端设置并重建应用容器。7 个配置、2 份本机快照与真实服务核对通过，本轮最终核对 revision 23；其他在线设备后续可继续推进版本。
- 真实 HTTPS 隔离测试通过双设备交换、不同文件三方合并、同文件冲突保留、客户端离线恢复、提交成功后丢失响应重试、重复请求幂等及过期 CAS 拒绝。故障由客户端注入，未切断 VPS 网络。合成数据使用独立测试用户；临时令牌已撤销并验证 401，清理测试记录前使用 SQLite backup API 备份。
- 原生导入：`tests/linux_native_acceptance.py` 使用本机 `/usr/bin/rime_dict_manager`，在新建隔离目录验证双词典范围、双设备合并和多轮词频不变。随后备份实际原生快照，通过 Fcitx5 的 `fcitx://config/addon/rime/sync` 全量入口执行实际导入/导出；私有日志记录本轮 `Rime Sync user data`、`deploy start`、`deploy success`，之后回传本机两份快照。异步 D-Bus 返回 0 本身不作为成功依据。
- 后台：systemd 用户服务安装、更新、卸载重装、单实例及 SIGKILL 后自动重启通过，最终 enabled/running，显式使用 `remote.local.json`。当前模式仍为 **snapshots-only**，本轮原生同步为单独触发；未交付无人值守 Fcitx5 原生包装器。服务端轮询不会自动导入活动数据库。

**本轮 Ubuntu 实机验收完成（快照后台同步＋手动原生合并范围）。** 用户注销并重新登录后，SDDM Wayland 会话 7 于 17:13:42 CST 建立；旧用户管理器停止服务，新用户管理器在同一时间自动启动服务，PID 12401，enabled/active/running，NRestarts=0，单实例。17:14:24 HTTPS 同步成功，revision 24。本次检查未手动启动或重启服务，Linger=no。登录证据为 `login-service.log` 与 `login-journal.log`。无人值守原生包装器属于后续能力；VPS 定期备份也未配置。证据与私有验收脚本保存在 `private/ubuntu-acceptance/`（不入 Git），关键记录为 `unit-tests.log`、`linux-native.log`、`frontend-sync.log`、`production-result.json`、`service-result.json`、`https-check.log` 及各隔离目录的 `result.json`。

Fcitx5 原生入口依据 [fcitx5-rime 源码](https://github.com/fcitx/fcitx5-rime/blob/5.1.13/src/rimeengine.cpp) 中 `setSubConfig`、`deploy` 与 `sync`；本轮没有把独立 dict-manager 验收脚本作为后台全量包装器。

### Linux 外观适配（2026-11-10）

**UI 验收结论：用户确认通过。** 最终外观为竖排 9 候选、14 号字、明暗黑白底色、绿色高亮、窗口圆角 12、高亮圆角 7；背景 alpha E6（约 10% 透明），背景模糊关闭。以下调试记录保留各阶段状态，最终以此结论为准。

已从 Windows/macOS hx 样式生成 `config/fcitx5/themes/hx-light` 和 `hx-dark`，通过独立 `client/platforms/linux/apply_fcitx5_theme.py` 备份、合并并应用。Fcitx5 字体使用 Sans 14 系统回退，序号与注释缩放为 100%；竖排 9 候选，浅色绿色为 `#00b050`（原 ABGR `0x50b000`），深色为 `#008000`。PNG 九宫格保留窗口 12、高亮 7 圆角，面板底色 alpha CC（80% 不透明），窗口阴影向下偏移 3；阴影为视觉近似，不声称与小狼毫半径算法一致。

主题最初启用 KWin 模糊及圆角遮罩，后按用户要求关闭背景模糊，保留半透明；配置依据 [Fcitx5 5.1.19 主题定义](https://github.com/fcitx/fcitx5/blob/5.1.19/src/ui/classic/theme.h)。关闭系统强调色覆盖以保留绿色，自动跟随系统明暗。不会迁移 Windows 程序名单。Classic UI 主题作用于所有使用该 UI 的输入法。

已通过 INI/PNG 校验，并通过当前 Fcitx5 D-Bus 回读确认竖排、字体、明暗主题选择及两主题圆角资源、注释字号和模糊配置被识别。重复应用验证通过；原始文件与配置证据在 `private/fcitx5-theme/`。用户反馈首版透明感不明显；检查发现底色与阴影叠加使实际 alpha 升至 234/238。现将阴影限制在面板外，Linux 底色调整为 CC，已验证源文件及安装图片中心 alpha 均为 204，文字/绿色高亮保持不透明。KWin D-Bus 确认 blur 效果已加载；该阶段重新加载成功；后续最终样式已由用户确认通过，见本节开头。先前“输入正常、UI 默认”不作为新主题验收。资源未进入 Rime 同步清单，应用始终从 `config/fcitx5/` 读取。

### Ubuntu / Linux 验收交接

以下保留原交接清单；本机 Ubuntu 执行结果及能力边界见上方实机验收记录。其他 Linux 前端和设备需独立验收。

1. 拉取本次提交，先确认实际使用的前端是 IBus Rime、Fcitx5 Rime 或其他实现，再发现实际目录；多个候选必须明确选择，不沿用 Mac 私有路径文件。
2. 运行 `python3 -m unittest discover -s tests -v`、`--dry-run`、`--plan-json`，记录真实平台、版本、通过与跳过项。原生验收脚本必须适配 Linux 已安装运行时，不能直接套用 Windows DLL 或 macOS 应用路径。
3. 备份后应用清单内配置并通过 Linux 前端部署；核对完整雾凇、Lua、OpenCC 和模型依赖。第三方刷新只覆盖配置中指定的词典，单独验收下载、哈希及失败保留旧版本。
4. 为 Ubuntu 使用其自身 Rime installation_id 和独立服务端令牌，沿用同一用户 hx；不要复制 Windows/Mac 凭据或设备 ID。私有云配置可使用 `remote.local.json`，显式传给单次运行及服务安装。当前服务端范围包含 7 个配置（含 squirrel 补丁）及 luna_pinyin、rime_ice；新增范围先对齐服务端。
5. 验收真实 HTTPS 拉取、三方冲突保留、回传、网络恢复及重复请求；配置始终先合并到 `config/`。保留所有设备现有数据，不用整份选边掩盖冲突。
6. 先在隔离目录验证原生快照合并与重复词频，再验收实际 Linux 前端的全量原生入口。如实现无人值守包装器，遵守前述空闲、限频、真实完成凭据及失败禁止上传约定；不能把异步通知退出码 0 当成功，不直接操作活动数据库。
7. 验收 systemd 用户服务的安装、更新、卸载、单实例、异常重启及实际登录启动；最后一次配置部署后由用户确认 Linux UI 和输入体验。Windows/macOS 外观补丁不能替代 Linux 前端外观配置。

交接时分开报告配置应用、快照传输、原生导入、后台运行与 UI。更新本文验证记录和 README 使用方式；服务端有变更时同步维护 server/README。Mac 尚未交付无人值守原生包装器，注销后登录启动已由用户确认完成；VPS 定期备份也仍未配置，这些不应被 Linux 验收默认为已完成。


### macOS 中文模式锁定（2026-11-10）

用户在非 UI 验收后明确要求并接受：macOS 的 Ctrl+Space 由系统处理，鼠须管固定中文，英文使用系统输入源。`squirrel.custom.yaml` 的终端/编辑器应用选项统一为 `ascii_mode: false`；`hx_preferences.lua` 依据 librime-lua 的 `get_distribution_code_name() == "Squirrel"` 识别鼠须管，初始化时恢复中文，收到菜单或应用选项设置英文时立即恢复中文，不提交或清空当前拼音；即使收到 Ctrl+Space 也不再执行内部切换。其他前端仍使用原有切换与去分隔符提交行为。此规则适用于已装载个人处理器的雾凇、朙月方案；不改变系统输入源快捷键，也不限制中文方案的英文候选/混输。

此前“macOS 终端/编辑器默认英文”和引擎内部 Ctrl+Space 切换的记录是旧配置验收结果，以本节为准。测试覆盖初始英文恢复、外部英文选项回退、拼音保留、Ctrl+Space 让行及其他前端兼容；真实引擎验收使用 `--distribution-code-name Squirrel`，验证两个中文方案无法保持英文状态。另修复成功部署后的新配置被旧 `retry_at` 延后问题：仅未完成/失败任务受重试期限限制，成功后的新指纹仍先检查真实空闲；失败重试和原生词典的独立限频保持不变。最终回归 168 项：161 通过、7 项其他平台测试跳过。已备份并应用到实际目录，鼠须管原生部署取得 3/3/0 成功凭据；编译的应用选项为中文，3 个修改配置与 HTTPS revision 42 逐字节一致，后台 running。证据在私有 `private/macos-chinese-lock/`。

### macOS 新入口与内置维护续验（2026-11-10）

本轮按用户要求合并远端并验收 UI 以外能力。`main` 从 `fe10455` 快进至 `1e30035`，3 个提交合并无冲突；合并前备份本地配置，原本未提交的鼠须管应用初始英文设置与远端一致。UI 不在本轮复验范围，先前用户确认的 UI、注销登录启动结论保留。

- 回归 167 项：160 通过、7 项跳过。使用鼠须管自带 librime/Lua 运行库补验 Lua；首次建库和客户端/WSGI 回传测试已扩展到 macOS，实际执行 `renamex_np(RENAME_EXCL)`、原生恢复与导出。跳过项为 5 项 Windows 原生测试、Linux levers 工作者测试和 Fcitx5 专用配置测试。
- 隔离原生验收覆盖两个词典、双设备合并、限定范围和重复词频不变；隔离引擎验收覆盖雾凇/朙月中文候选、英文候选、9 候选、Ctrl+Space 提交及切换、melt_eng 与 radical_pinyin 有效代数。未读取或复制活动用户数据库，测试词条不注入生产账号。12 个范围内 YAML 由 librime 解析通过，鼠须管编译结果包含终端/编辑器初始英文选项；这不代替应用中的 UI/按键验收。
- 已迁移 LaunchAgent 到 `rime.py --native-sync-builtin`，完成安装预览、更新、卸载、缺失状态查询、恢复安装、异常退出后自动重启和单实例检查。身份文件权限为 0600；凭据、路径记忆、结果与备份保持 Git 忽略。此前登录触发已由用户确认，本轮没有注销用户会话。
- 真实第三方刷新锁定 `iDvel/rime-ice@99662ba01e3affa6a0f009174ca530b887bac3b6`，17 个文件全部下载、Git blob 校验通过，实际文件 SHA-256 与刷新凭据一致，结果为当前版本，无需替换。哈希失败、中断和回滚路径由回归测试覆盖。

实机发现并修复鼠须管日志缓冲问题：正常空闲触发 `--sync` 后，末尾完成摘要滞留于 INFO 缓冲，180 秒超时；随后部署时延迟刷出的上一轮日志也会污染本轮完成判断。依据 [glog 写入/刷新实现](https://github.com/google/glog/blob/v0.7.1/src/logging.cc)，仅等待 `logbufsecs` 秒不保证空闲进程刷新。用户明确同意配置无缓冲日志并重启输入法。内置适配器现于空闲且取得维护锁后检查进程环境；必要时正常退出唯一鼠须管实例，以 `open --env GLOG_logbufsecs=0` 重新启动，再绑定新 PID 和重新采集的日志偏移。变量仅作用于该应用，不修改全局环境或应用包；下次系统启动未配置的实例时也会在空闲维护前处理。已配置实例不重复重启，无法确认退出时不启动第二个实例。

实际失败恢复证据：首次失败后 `unsafe=true`，新导出与云端不一致但没有上传，云端保持已确认 revision 38；服务异常重启及卸载/恢复安装后 `last_attempt` 不变，继续 `retry-wait`，没有清空状态或绕过 900 秒重试。23:32:33 原生重试成功，同一鼠须管 PID 67274 确认两个词典和 `3 tasks ran: 3 success, 0 failure`，`unsafe=false`；23:35:09 自动部署重试成功，同样取得 3/3/0 凭据，资源指纹复查一致。最终 17 个配置范围项（16 个文件、1 个 null 删除标记）与服务端一致，其中 14 个适用于实际 Rime 目录的文件逐字节相同；2 份本机快照与 HTTPS revision 40 一致。重复 `--sync-now` 保持 revision 40，原生记录 deferred/interval，后续部署 unchanged，工作流无 failed/blocked，服务 running。本轮 macOS 非 UI 验收完成；UI 未复验。

私有证据集中在 `private/macos-followup/`：`tests-final.log`、`native-acceptance-*/result.json`、`engine-acceptance-*/result.json`、`server-integration.log`、`service-lifecycle.json`、`service-recovery.json`、`third-party-result.json`、`failure-quarantine.json`、`result.json`、`repeat-sync.log`、`service-final.txt`。该目录及合并前配置备份不提交 Git。

### macOS 公网与原生合并续验（2026-11-10）

网络恢复后，本机使用独立设备身份完成 VPS 接入；此前 SSH 超时阻塞已解除。服务端保留 Windows 设备，备份设置后添加 Mac，并将 `squirrel.custom.yaml` 加入配置范围；重建容器加载新设置，最终健康检查通过。凭据仅在私有 `device.local.json`，云配置为私有 `remote.local.json`，两者权限 0600 且被 Git 忽略；仓库示例 `remote.json` 继续默认禁用。

- HTTPS 证书校验成功；未认证请求返回 401，Mac 认证返回其自身设备身份。首次核对版本 15，6 个共享配置仅存在 LF/CRLF 差异，备份后按远端字节对齐；鼠须管补丁为新增文件。首次提交版本 16，后续 Windows 与 Mac 交换后的最终核对版本为 18。
- 通过鼠须管自身 `Squirrel --sync` 合并接收的 Windows 快照，再请求重新部署。专属本轮日志包含两个词典的同步及 `3 tasks ran: 3 success, 0 failure`；两个本机快照均新生成且通过元数据校验。不直接打开或复制活动数据库。
- 最终 7 个配置在 `config/`、实际目录及 HTTPS 返回值间逐字节一致；本机 `luna_pinyin`、`rime_ice` 快照与服务器一致，导出词条覆盖 Windows 快照词条。随后重复 HTTPS 同步保持版本 18。多次原生合并词频不变的验证仍以隔离验收脚本为证据，不把线上有其他设备写入时的版本变化解释为幂等失败。
- LaunchAgent 已安装并运行，参数显式使用 `--remote-config /Users/hx/rime-config/remote.local.json`，每 60 秒检查云同步、失败后 30 秒重试；本地轮询间隔 5 秒。正式设备身份与令牌不放进服务参数。
- 本轮完成的是 **Mac/VPS 配置与快照端到端 + 手动触发的真实原生合并**。后台模式仍为 `snapshots-only`，未安装无人值守 macOS 原生包装器；新学习数据导出和接收快照导入仍需触发“同步用户资料”。UI 已在最后一次应用与重新部署后由用户确认通过（2026-11-10）；注销后登录自动启动验收已由用户确认完成（本次仅更新记录，未新增终端日志取证）。

私有证据在 `private/macos-acceptance/result.json`、`native-remote-merge.log`，源配置备份在同目录 `config-before-*`，实际目录备份由客户端状态目录保存。服务端设置和清单备份后缀为 `.macos-backup-*`。这些证据及备份不提交 Git。原生入口参考 [Squirrel 命令入口](https://github.com/rime/squirrel/blob/master/sources/Main.swift) 和 [同步调用实现](https://github.com/rime/squirrel/blob/master/sources/SquirrelApplicationDelegate.swift)；`--sync` 本身是异步通知，不能仅以退出码 0 判定导入成功。

### 合并远端后的 macOS 复验（2026-11-10）

已将 `origin/main` 的 4 个提交快进合并至 `7cbbe68`，保留本地鼠须管补丁、同步清单及此前验收记录。Windows 使用远端新增的竖排圆角样式，macOS 继续保留此前横排矩形样式，不自动跨前端迁移外观。

- 回归 106 项：101 项通过，5 项 Windows PowerShell 专用测试跳过。通过鼠须管 Frameworks 下的 librime 和 Lua 插件加载实际 Lua 测试，未跳过该项。日志：`/private/tmp/rime-macos-merged-tests.log`。
- 新增 `tests/macos_native_acceptance.py`：调用鼠须管 `rime_dict_manager`，仅在新建隔离目录验证两个词典的快照恢复、双设备合并、范围限制和多次重复合并词频不变。全部通过，未访问活动数据库。Windows 的 ctypes 验收脚本依赖 `RimeSetup` 导出符号，不能直接用于本机鼠须管动态库；本轮不将其计为 macOS 引擎验收通过。
- `--dry-run`、`--plan-json`、launchd 安装预览通过。实际重新安装并启动新版 LaunchAgent 后状态为 running，`workflow-result.json` 记录 macOS 配置应用与第三方检查成功；云同步和词典交换因尚未配置而跳过。
- 最后一次应用后，7 个清单内配置逐字节匹配实际目录；`rime_deployer --build` 与 `Squirrel --reload` 均返回 0，生成配置中的横排及明暗主题存在。UI 按用户要求留待其在此后验收；该阶段注销登录自动启动未复验，后续用户已确认验收完成。
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
- 用户级 `local.rime-config` LaunchAgent 的安装、更新、卸载、重装通过。模拟 SIGKILL 后自动重启，启动次数由 1 增至 2，最终为 running，后台错误日志为空；该阶段尚未验证注销登录自动启动，后续用户已确认验收完成。
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
python rime.py --service status
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

- `client/core/plans.py`：纯数据决策，生成配置文件、原生维护、工作流计划；校验版本、动作与依赖，并分派固定工作流阶段。
- `rime.py`：观察配置与目标，生成指纹计划；远端合并后重新规划，备份前及写入前复核源与目标指纹，发现变化停止。原有锁、备份及恢复机制保留。
- `client/maintenance/native_sync.py`：采集元数据、快照指纹与持久化调度状态，调用公共计划判断限频、无变化、重试和空闲条件；仍负责范围约束、完成校验及失败快照隔离。
- `client/platforms/platform_execution.py`：Windows 调用小狼毫、输入空闲探测及计划任务；Unix 调用原生包装器及完成凭据约定，分派 systemd 或 launchd。`client/services/unix_service.py` 保存从公共服务入口提取的 Unix 安装与恢复逻辑；`client/services/service.py` 保留公共参数和模板规则。

计划 JSON 顶层字段固定为 `kind/version/platform/steps`，版本为整数 `1`，平台为 `windows/linux/macos`。每步固定为 `id/action/reason/requires/details`，依赖只能引用前置步骤。契约由 `plans.validate()` 校验，未知类型、版本、动作及非法依赖在分派前拒绝。

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

2026-11-10 Linux 外观续调：用户确认不采用 KWin 广范围模糊，已将明暗主题及生成器的 `EnableBlur` 设为 `False`，保留底色 alpha CC（80% 不透明）、文字与绿色高亮不透明。仅关闭候选框的模糊请求，不修改桌面全局模糊设置。

2026-11-10 Linux 外观最终调整：按用户要求，明暗底色改为 alpha E6（230/255，约 90% 不透明、10% 透明），继续关闭背景模糊，阴影不叠加到面板内部；文字与绿色高亮保持不透明。此设置替代此前 CC 底色。

## 自动维护扩展（2026-11-10）

本轮新增自动令牌轮换、按用户服务端词典范围扩展、Linux 主题云同步和应用、变更后重新部署、受管理日志过期清理、服务端定期备份及保留策略。此前“不自动部署”“主题不云同步”“未配置周期备份”的记录是历史状态，当前以本节为准。自动新设备注册和恢复向导仍不实现。

### 协议与安全重试

- `POST /rime/v1/token/refresh` 接收客户端生成的随机令牌；SQLite `credentials` 保存注册初始令牌哈希、当前/前一令牌哈希和 24 小时宽限截止时间。注册配置继续决定有效设备，删除设备或改变初始令牌立即使旧派生身份失效（设置修改需重建容器）。旧令牌过期后不能读写数据，只能携带相同新令牌重试已完成的轮换；旧令牌不能再派生另一令牌。宽限期间拒绝再次轮换，避免丢失响应的客户端被连续轮换锁死。
- 客户端 `token/rotation.json` 在请求前保存候选令牌，以文件锁串行化，服务确认后原子更新私有身份，再清除候选并记录完成时间。响应丢失、身份写入中断均可恢复；候选文件同样按私有凭据保护，不入 Git 或日志。首次启用会轮换一次，随后默认每 30 天。
- `POST /rime/v1/scope/dictionaries` 仅允许认证设备为自身用户追加个人词典名称，验证路径、大小写碰撞及数量上限。服务端 `auto_expand_dictionaries` 默认兼容旧配置为 false，示例及本机部署开启；`max_dictionaries` 默认 128。增量存入 `dictionary_scopes`，GET 返回静态范围与本用户增量的并集；禁用词典时拒绝扩展。客户端扩展成功后重新 GET 校验，再执行原生处理和上传。不会扩展配置文件清单或第三方资源权限。

### 主题、部署与计划

`fcitx5/theme.json` 是 UTF-8 文本资源包，内含固定路径资源的 Base64；因此无需放宽原状态协议的文本约束。它在 `configuration.files` 中按文件三方合并，源仍为 `config/`。普通配置应用排除 `fcitx5/`，仅 Linux 的主题阶段解码、校验、备份并应用到 Fcitx5；保留其他 Classic UI 设置。只允许固定 hx 明暗主题文件和外观项，拒绝外部图片路径、异常尺寸与路径逃逸。重复相同内容不重载，范围缩小/资源包缺失时保留已安装主题。

工作流使用 version=2，保留原四阶段，追加 `theme-apply`、`frontend-deploy`、`log-cleanup`；version=1 仍能校验和执行原四阶段。配置文件计划、原生同步计划保持 version=1。预览只读、无联网或原生调用，不接受保存的计划作为执行输入。

部署依配置和第三方词典的实际字节指纹判断，成功指纹持久化；失败或进程中断保留重试时间，不因源文件已经应用而丢失待部署任务。本机 Fcitx5 内置适配器核对目标目录、检查空闲/锁屏，通过前端发起部署，使用本次 journal 游标及进程 ID 过滤事件，要求开始后的成功事件，并拒绝失败或并发同步。只保存维护事件，不将按键/词条正文复制到项目日志。诊断期间临时启用 rime 调试日志并在 finally 恢复信息级别；系统 journal 可能包含该短时诊断输出。180 秒未完成视为失败，默认 900 秒后重试。KDE Wayland 不支持传统空闲查询时，安全退化为等待锁屏。Windows/macOS/WSL 通过命令＋本轮凭据契约接入，本轮未交付其内置部署适配器或实机验收。自动部署未扩大为无人值守原生词典合并。

### 日志与备份保留

后台进程使用按日及大小分段的专用日志，默认 30 天过期、10 MiB 换文件；仅匹配自身命名规则的日志会被清理，不删除状态、冲突、待确认提交、快照或备份。服务端 Gunicorn 应用日志同样保存在 `/data/logs/` 并按 30 天清理；Docker 外层日志限制 3×10 MiB。旧版外层文件及宿主 journal 不做跨应用清理。

服务端健康检查/状态请求驱动每日备份（运行中的 Compose 健康检查每 30 秒触发检查），SQLite 事务占用调度槽以避免多 worker 重复创建；SQLite backup API 创建临时副本，完整性检查通过后原子发布，权限 0600。失败不清理旧备份并释放调度槽。只清理 `/data/backups/auto-*.sqlite3` 中超出 30 天且不属于最新 7 份的文件；历史手工备份、升级归档、设置备份及宿主 `server/backups/` 不自动删除。该策略不代表异机备份或已完成恢复演练。

### 验证边界

新增回归覆盖轮换重试/撤销/宽限失效、身份隔离、范围扩展及上限、主题回滚与只读预览、部署失败重试和并发资源变化、日志过期及保护非日志、备份完整性及最少保留数。Ubuntu 已验证真实 Fcitx5 重新部署；真实 VPS 验证轮换响应丢失重试、范围扩展幂等及用户隔离、撤销派生令牌和主题字节一致性。测试身份已撤销，测试记录已删除；证据保存在 `private/automation-acceptance/`。其他平台的部署和日志实际运行仍需各端验收。

自动维护收尾：Ubuntu 回归 117 项（112 通过、5 项 Windows 专属跳过）；VPS 隔离容器此前回归 116 项（110 通过、6 项平台条件跳过）。新增日志配置回归用于防止 Gunicorn 默认根日志器引用被替换的处理器；修正后容器健康，真实 HTTPS、新令牌、8 个配置及自动备份完整性复核通过。当前 Ubuntu 后台已恢复运行，自动部署默认仍等待空闲/锁屏。

## 客户端备份保留与独立服务端备份（2026-11-10）

本节取代前述“客户端备份不自动清理”以及“服务端备份由健康检查驱动”的现状描述；历史验收记录保留。自动新设备注册及恢复向导仍不实现。

客户端 `backup_retention.py` 只处理明确列出的状态子目录，以写入方成功发布的 `.completed/<备份名>.json` 为主要完成凭据，兼容旧配置/第三方 applied 日志及原生 success 结果。配置、远端、快照交换、第三方、主题、原生运行与清单备份分组保留，默认 30 天、每组至少 7 份、每天一次。清理取得对应写入锁后重新观察；busy、路径异常、符号链接/重解析路径及无法确认完成的备份均不删除。远端 pending/error 状态保护相关备份，原生 unsafe/failed/running 状态保护原生组；最新原生运行单独保护。根状态、基线、冲突、凭据及实际/交换目录不在删除范围。状态目录只保存清理报告与下次执行时间；预览不写入。旧策略文件缺少 backups 字段时默认禁用，项目配置显式启用。

工作流升级为 version=3，在 version=2 的七阶段后追加独立 `backup-cleanup`；仍能校验和执行 v1/v2，文件和原生计划仍为 v1。备份清理与云端成功无依赖，依据各组恢复状态单独决定保留，不能因为网络失败删除待恢复备份。

服务端 `backup_worker.py` 由独立 Compose `backup` 容器运行（无网络、只读根目录、去除 capabilities）。每 60 秒检查调度；HTTP 状态接口及健康检查不再执行备份。应用与备份容器共享数据卷，注册配置及范围清单只读挂载；修改 bind mount 设置需同时重建两容器。数据库文件锁防止并发备份，SQLite 维护表保存成功时间和 10 分钟中断租约；原生备份过程最长 300 秒。首次切换到完整备份格式会立即生成一套，不被旧数据库单文件备份的间隔阻挡。

每套 `auto-<编号>` 包含 `.sqlite3`、`.settings.json`、`.scope.json` 及最后发布的 `.manifest.json`。数据库通过 SQLite backup API 复制，随后 integrity_check；配置读取前后校验未变，所有成员权限 0600，SHA-256 写入完成清单。只有完成且成员哈希匹配的套件才参与保留计数和删除；默认 30 天且至少最近 7 套。旧单文件自动备份、手工备份、升级归档及不完整/损坏套件保留，不以它们凑足最低可用备份数。备份失败保留旧套件、释放租约并记录独立失败心跳，不影响 HTTP 健康。进程中断后文件锁自动释放，租约到期后恢复。心跳在 `/data/backup-worker.json`，不包含凭据或词条。

隔离测试覆盖年龄＋最低份数、只读预览、写入锁冲突、待确认远端保护、最新/失败原生保护、符号链接拒绝、格式迁移、备份失败重试、并发/中断租约和套件清理。恢复验证只在隔离目录打开副本并通过应用接口核对轮换令牌、用户版本和动态词典范围，不覆盖生产数据库，不构成恢复向导或生产灾难切换演练。

本轮实机验收：Ubuntu 回归 126 项（121 通过、5 项平台跳过），VPS 无网络只读测试容器回归 126 项（120 通过、6 项平台跳过）。Ubuntu 用户服务已实际写入备份清理成功记录，当前无到期候选。VPS app/backup 两容器均 healthy，独立进程首次自动生成完整套件（无需 API 触发）；重复调度返回 not-due。将该套件复制到无网络容器临时目录，SQLite 完整性检查通过，轮换后的 Ubuntu 令牌可认证；恢复出的 revision=27、8 个配置文件及 3 个设备的词典状态与实时 HTTPS 返回完整一致，成员权限均为 0600。验证前后线上用户状态一致。私有证据位于 `private/backup-acceptance/`，未在生产卷执行恢复。

## 内置原生维护与方案警告修复进展（2026-11-10）

用户目标为上一轮清单第 1、2、7 项：macOS/Ubuntu 无人值守全量词典维护，Windows/macOS/WSL 内置重新部署，melt_eng/radical_pinyin 循环依赖及全局 grammar 缺失警告修复。目标尚未宣告完成。

新增 `--native-sync-builtin`，服务参数允许持久化。FullNativeSync 仍承担范围、锁、限频及禁止失败输出回传；旧 command/deployer 调度绑定保持原结构，避免升级绕过或破坏既有限频。内置 Unix 分派位于 platform_execution，部署亦经原适配器分派；计划仍为 workflow v3，只增加 native_backend=builtin 取值。`fcitx_maintenance` 共用部署/同步观测逻辑和按目标命名的用户锁，任务成功后再次检查前端 PID。`squirrel_maintenance` 读取当前 PID 的新增 INFO 日志，要求本轮 task start、单组全成功统计和操作范围匹配。Windows 部署经注册表定位，使用独立子进程日志及原 IPC probe；WSL 经参数数组调用 Windows Python 执行同一实现。`rime_api` 兼容仅导出版本化 C API 的 Unix librime，按 data_size 检查函数指针，不打开活动数据库。

官方源码依据：<https://github.com/fcitx/fcitx5-rime/blob/master/src/rimeengine.cpp>、<https://github.com/rime/squirrel/blob/master/sources/SquirrelApplicationDelegate.swift>、<https://github.com/rime/weasel/blob/master/WeaselDeployer/Configurator.cpp>、<https://github.com/rime/librime/blob/master/src/rime/deployer.cc>。原生 CLI 返回不能证明异步完成。

警告定位：本机原始方案无对应 custom 文件时未出现循环；新增补丁后，即便把 speller/algebra 覆盖为纯列表，原方案内部 __include 仍在补丁解析前造成循环。已用隔离目录复现，随后将当前全拼规则内联、英文公共规则移至独立 hx_english_algebra 资源，保留原方案其他内容和用户偏好；新增空全局 grammar 默认值，具体模型参数仍在 rime_ice.custom 中。两份最终编译方案去除构建元数据后与修复前结构完整相等，隔离编译无 circular/blocking-node/ERROR；真实 librime 引擎的双方案中文、英文、Ctrl+Space 及有效拼写规则检查通过，未接触活动数据库。第三方词典内容重复词条警告不在本项范围内。

当前回归 136 项：131 通过、5 项 Windows 条件跳过。新增覆盖旧调度兼容、内置分派、服务参数、并发维护/失败/前端重启、鼠须管缺失开始事件/范围不齐、小狼毫缺失任务或恢复证据、WSL 参数数组及缺失新快照拒绝。证据在 private/native-maintenance，proposed-sync-manifest.json 为待批准的 14 文件清单，正式清单仍 8 文件。用户确认 Windows/macOS 暂不可访问，其实机验收待完成；Ubuntu 内置同步的生产切换也尚未执行。

自动审批拒绝了扩大 VPS 配置范围并重建 app/backup 的生产变更，理由为生产授权证据不足且同步范围会改变。拒绝后未绕过执行，新增兼容文件仅保留在 config/ 与隔离验证目录，生产清单保持原范围。下一步需审批已明确列出的六文件范围扩展、Ubuntu 后台启用内置同步及上线验证；不涉及新设备注册或恢复向导。

续审修正：小狼毫 `/deploy` 调用同步 `RimeDeployWorkspace`，不保证输出异步 Deployer::Run 的 tasks-ran 汇总。部署校验改为本次独立进程中唯一 workspace 开始、唯一 finished-updating-schemas 全成功汇总、随后 Resuming-service，再做 IPC probe；存在额外失败任务或 ERROR 仍拒绝。鼠须管新增实际文件偏移模拟测试，确认旧成功日志及截断不能被当作本轮完成。当前回归 139 项（134 通过、5 跳过）。生产批准仍未收到，清单核对为 8 文件；待扩展的六文件及 SHA-256、生产操作顺序记录在 private/native-maintenance/production-change.json。

生产批准与上线续验：用户明确允许修改 VPS 并启用本机同步。先由独立备份进程强制生成完整套件，再备份并扩展 VPS 配置清单，保留所有设备和旧范围，重建 app/backup；两容器均 healthy。Ubuntu 服务安装器已保存 --native-sync-builtin，正式清单扩展至 14 文件；真实 HTTPS revision=29，全部文件与 config/ 字节一致，适用文件也与实际目录一致。原生入口当前因尚未锁屏记录 deferred/input-active；未将 deferred 当作词典导入或部署成功。先前生产审批阻塞已解除，Windows/macOS/WSL 新适配器的实机验收边界仍保留。

Ubuntu 内置维护实机验收完成：用户确认锁屏。21:48:01 发起 Fcitx5 部署，21:48:05 收到 success；21:48:21 发起原生同步并收到 start/success，同一 frontend PID=12606。FullNativeSync latest=success、unsafe=false，luna_pinyin/rime_ice 两份新导出与真实 HTTPS 完整字节一致，revision=30；远端基线记录 native-all。后续原生计划 defer/interval，未绕过 900 秒最小间隔。用户服务 active/running、NRestarts=0。真实部署窗口日志中 circular-dependencies 与 missing-grammar 警告均为 0；生产配置 14 文件一致。上线后另生成完整服务端备份，app/backup healthy。最终回归 139 项（134 通过、5 平台跳过），事件、HTTPS、限频、警告检查和备份证据在 private/native-maintenance。此前 VPS/本机生产批准阻塞已解除并完成操作；目标剩余边界为 Windows/macOS/WSL 新适配器实机验收，用户已说明对应设备暂不可访问，不将模拟测试视为这些平台端到端完成。

## 远端独有词典首次落地、移除 WSL（当前范围）

用户明确不实现异机备份，并要求移除 WSL。当前支持平台仅 Windows 原生、macOS、原生 Linux；此前 WSL 设计/测试记录仅为历史，不构成支持承诺。删除 WSL 路径发现及 cmd.exe/wslpath 桥接、平台计划枚举和执行器、自动部署桥接及服务提示；WSL 内核/环境变量检测用于明确拒绝运行。旧 paths.json 的 wsl 字段只做丢弃迁移，路径记忆及设备数据不删除。AGENTS 与用户文档已同步调整。异机备份从待办中排除，不影响同机自动备份和恢复验证。

`dictionary_bootstrap.ensure` 仅在内置全量维护已通过空闲判断后执行；Windows 在既有原生调度准许后执行。名称必须来自已验证、已授权且在本轮范围内的快照，已存在数据库不进入初始化。实际目录下创建 `.rime-bootstrap-*` 私有隔离目录，仅写入本机 installation_id 与经过校验的快照副本，不复制活动数据库。Unix 调用原生 rime_dict_manager restore/backup；Windows 在独立 Python 子进程通过已安装 librime 的版本化 levers API 完成相同步骤。先验证导出元数据、关闭原生进程并同步文件，再原子移入不存在的目标路径；Linux renameat2(RENAME_NOREPLACE)、macOS renamex_np(RENAME_EXCL)、Windows 不覆盖的 rename，绝不降级为先检查再覆盖。macOS 标志依据官方 [sys/stdio.h](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/sys/stdio.h)。

初始化凭据只记录名称、输入 SHA-256、已发布名称和状态，不记录词条。失败或中断后，原有 native unsafe/重试机制禁止发布未经确认的快照；已完成的库不重新初始化，下一轮由 Rime 原生合并补齐其余快照。未知或不支持的文件系统原子移动失败时保留源快照，不覆盖目标。硬中断留下的隔离目录不自动删除，避免误删未知恢复材料。

FullNativeSync 对内置入口及 Weasel 将远端独有名称纳入本轮完成范围；初始化后仍须真实前端全量同步成功、范围重新校验及全部本机导出存在才记录 success。仅交换快照模式及自定义原生包装器不自动初始化。范围清单仍是授权边界，服务端有其他名称并不代表客户端自动导入；同名基础方案或资源也不会随此功能安装。

本轮验证：本机安装的 librime 原生工具在临时目录中完成远端独有词典初始化、双设备合并、三轮重复同步词频不变；levers 隔离子进程也在 Linux 共享库上执行成功。完整客户端＋WSGI/SQLite 服务端测试覆盖首次下载、扩大本轮完成范围、原生建库与同步、快照回传、下一轮限频及版本不重复增长；另覆盖原生失败不发布、并发新建不覆盖、空目标目录也拒绝覆盖、错误元数据不执行、清单外名称不导入及旧库不重新初始化。本机服务已重新加载代码，active/running、NRestarts=0，工作流无 failed/blocked。未在生产账号注入测试词典；新建库验证使用隔离目录，Windows/macOS 的对应系统原子移动及实际输入法联调仍待各端验收。证据保存于 private/dictionary-bootstrap-acceptance。

最终回归为 147 项（142 通过、5 项 Windows 条件跳过）；原子发布前同步数据库文件及目录，发布后同步目标父目录，测试通过后本机服务已加载最终版本。

## KDE Wayland 事件式输入空闲检测（2026-11-10）

`client/platforms/linux/wayland_idle.py` 以 Python 标准库 Unix socket 实现最小 Wayland 客户端，绑定 `ext_idle_notifier_v1` 版本 2 的 `get_input_idle_notification`，不采集按键内容，无新增安装依赖。监听当前全部 wl_seat，只有全部收到 idled 才允许维护，resumed 清除对应状态。连接在客户端进程中复用；维护查询通过 wl_display.sync 往返屏障处理此前排队的恢复事件，不持久化空闲结论。单次往返最多等待 1 秒，异常、全局接口移除、新增席位、会话 socket 替换或阈值变化时关闭旧连接并重新观察。首次连接默认不空闲，需要重新经过阈值。

自动部署与内置原生全量同步共用 `deployment.linux_idle`。Wayland 优先使用事件式通知，无接口或连接失败时保留锁屏兜底；非 Wayland 会话保留原 D-Bus 时长查询。准备词典和日志游标之后、实际触发原生操作之前再次检查空闲；既有前端互斥、维护限频、失败恢复保持有效。空闲门槛不等同于预编辑内容检测，最后检查与用户重新输入之间仍存在时间窗口。单轮进程通常无法等待完整阈值，应使用持续后台服务；服务需要当前 WAYLAND_DISPLAY/XDG_RUNTIME_DIR。

本机 KWin 实测提供版本 2；只读 3 秒阈值监听观察到 False → True → False，确认真实空闲和恢复活动事件。完整回归 152 项，147 通过、5 项平台条件跳过；模拟器覆盖协议请求、多席位、排队恢复、连接断开、会话/阈值变化、锁屏兜底和维护前复查。日志：`private/wayland-idle-acceptance/tests.log`。后台用户服务已重启加载新版。真实注销/重登录后的监听恢复及常规空闲触发的完整维护链路尚未单独验收，不与协议事件实测混同。

协议依据：[ext-idle-notify-v1](https://gitlab.freedesktop.org/wayland/wayland-protocols/-/blob/main/staging/ext-idle-notify/ext-idle-notify-v1.xml)。

## 三端输入偏好修正与六项重构（2026-11-10）

Ubuntu 的 Ctrl+Space 原先被 Fcitx5 全局快捷键拦截，Rime 前端的默认 `Commit commit preview` 将候选中文提交。已在 `config/fcitx5/input.json` 声明受管理偏好，移除该拦截及 Shift 临时切换，改用 Ctrl+Alt+Space 激活/退出前端，取消全局共享输入状态；Ctrl+Space 进入三端共用 Lua 逻辑，提交去分隔符拼音。通过 Gio 读取现有设置、私有备份、合并受管理字段、写入并读回验证，保留其他输入法快捷键；失败回滚。用户已实测确认行为符合预期。配置工作流 version=4 单独记录 frontend-preferences，与原生重新部署分别记账；前端备份纳入既有清理策略。

三端共用方案及 Lua；Linux 新增 `fcitx5.custom.yaml` 应用初始英文名单，macOS 的 `squirrel.custom.yaml` 补齐常见终端与编辑器 app_options，Windows 原有名单保留。操作系统应用标识不同，不将同一进程名硬套三端；未识别的应用沿用默认。Windows/macOS 当前不可访问，新增应用选项及新入口后台任务尚待其设备实机验证，不声称远端设备已升级。

六项重构的交付位置：

| 项目 | 实现 |
|---|---|
| 公共文件工具 | `client/storage/filesystem.py`、`config_paths.py`、`file_lock.py`；配置限制与词典快照路径分别校验。服务端不再导入 CLI。 |
| 空闲接口 | `client/maintenance/idle.py` 返回 Observation（idle/active/unknown、来源、单调时钟、原因）；外部包装器明确 delegated。Wayland Provider 拥有连接，CLI 退出关闭执行器，不落盘缓存空闲结果。 |
| 前端维护边界 | `client/maintenance/` 保留持久化调度、部署指纹、首次落地和共用前端锁；`client/platforms/{linux,macos,windows}/` 负责平台触发及真实完成凭据。空闲检测不再由 deployment 模块提供，公共 librime 配置读取不再寄存在 Windows 模块。 |
| 新入口与运行循环 | 根目录 `rime.py` → `client/cli.py` → `application/runtime.py` → `application/workflow.py`；配置应用位于 `core/configuration.py`。移除旧 client/sync.py，无兼容入口；三端服务生成器均使用根目录工作位置。 |
| 云同步分层 | `transport/http_transport.py` 管理 HTTPS；`transport/wire.py` 编解码；`core/merge.py` 为纯三方比较与 MergeConflict；`application/cloud_sync.py` 保留 CAS、响应丢失恢复、冲突留存和原生上传许可的事务顺序。词典格式验证与快照存储也从交换编排分离。 |
| 目录与服务端职责 | 客户端分 application/core/config/maintenance/platforms/providers/services/storage/transport；服务端拆为 app、credentials、database、scopes、backups、backup_worker。Docker 构建白名单支持子包，只打包代码与公开策略。 |

验证：本机完整回归 163 项（158 通过、5 项 Windows 条件跳过）；VPS 隔离无网络镜像回归 162 项（149 通过、13 项平台/运行库/个人配置条件跳过）。架构测试约束纯合并和 HTTP 模块不依赖前端、服务端不依赖应用编排、模块不反向导入 CLI，并覆盖 unknown 空闲阻止维护、连接关闭。真实 Ubuntu 隔离 librime 引擎通过雾凇/朙月中文、9 候选、英文候选、Ctrl+Space 拼音提交及切换、英文/拆字方案检查，没有访问活动 userdb。

Ubuntu 用户服务已通过安装器更新并启用新入口，version=4 实际工作流运行、前端偏好读回 unchanged，NRestarts=0。VPS API 与备份容器已重建并健康；HTTPS 核对版本 33、16 个配置，新增两份 Fcitx5 配置均已回传。源码/镜像发布前有备份，数据库与凭据格式未迁移。验收记录存放于 `private/refactor-acceptance/`；原生维护仍等待既定空闲/间隔，未将 deferred 记作完成。


实机回归补充：最初新增的基础文件 `fcitx5.yaml` 被原生部署移走，客户端资源指纹复查正确判失败。已改成 `fcitx5.custom.yaml`，隔离原生连续部署两次均保留补丁且编译出 app_options；该真实引擎检查已纳入本机回归。误加基础文件通过服务端 null 删除标记撤回，清单暂保留该名称以便其他设备收到删除；缩小清单不代替删除。部署运行记录现分别保留原生 receipt、请求指纹、运行 ID 和失败阶段/异常类型，不保存原始异常内容或配置正文。失败重试时间保持不变。


最终 Ubuntu 实机收尾：用户提供正常键鼠空闲窗口后，自动重新部署于 2026-11-10 23:03:48 完成（Fcitx5 PID 12606，运行 c65244cfb1304c7bb326cff4c3d924f4）。原生凭据成功、资源指纹复查通过、后续工作流为 unchanged，fcitx5.custom.yaml 保持原样且 app_options 已编译。HTTPS 版本 35 的 17 个范围项与 config/ 逐项字节一致，其中旧 fcitx5.yaml 是 null 删除标记。VPS 最终 API/备份容器均健康，真实强制备份成功生成 auto-1794322945098239356.manifest.json。六项代码重构完成；Windows/macOS 新入口后台任务迁移、前端应用选项和实机一致性尚未验收（设备此前不可访问）。


续检补充：Windows 后台 runner 的新入口导入及参数转发可在 Linux 实测，已新增从无关临时工作目录启动 runner → rime.py 的只读检查；确认不写目标、同步状态或路径记忆。Windows 测试组 10 项：5 通过、5 项依赖真实 PowerShell/Windows 而跳过。此项补足包迁移覆盖，不替代 Windows Task Scheduler/pythonw 实机验收。真实 Windows/macOS 设备访问仍是剩余验收条件。


### Windows/macOS 验收交接

用户确认两端暂不可访问，由用户自行实机验收。六项重构和本轮可执行验证已完成，以下为交接项，不记作已通过：

1. 更新完整工作副本后，沿用该设备原有持续参数，执行 `python rime.py --service install`（macOS 使用 `python3`），再查询 `--service status`。确认任务/launchd 指向根目录 rime.py；旧 client/sync.py 已移除，不能继续使用旧任务入口。保留设备自己的私有身份、令牌、目标目录和原生适配器参数，不复制其他设备的 device.local.json。
2. 中文模式输入 `nihao` 后按 Ctrl+Space，确认提交 `nihao` 并进入英文，再按一次回中文；输入 `xi'an` 切英应提交 `xian`。左右 Shift 不切换，9 候选与 -/= 翻页保持一致。检查终端/编辑器初始英文且允许手动切中文；应用标识不匹配时在对应前端补丁中修正。
3. 检查配置应用、云快照传输、原生合并/导出分别记录；空闲或间隔未满足时 deferred 为正常，不能当作合并成功。确认新入口后台任务在重新登录后启动，原有备份与基线仍可读取。

Windows/macOS 现场结果由用户另行确认；本轮没有声称已替用户完成两端的迁移或 UI 验收。
