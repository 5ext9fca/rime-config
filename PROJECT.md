# 项目技术说明

本文面向开发与维护人员，记录实现边界、数据流程和验证方式。日常使用见 [README](README.md)，公网部署与备份见 [服务端指南](server/README.md)，协作约定见 [AGENTS.md](AGENTS.md)。

## 代码与数据边界

| 位置 | 职责 |
| --- | --- |
| `client/sync.py` | 命令入口、周期调度、本地配置应用与备份 |
| `client/paths.py` | 跨平台目录发现与私有路径记忆 |
| `client/service.py` | systemd / launchd 用户服务的注册、查询和卸载 |
| `client/identity.py` | 安装 ID 与设备令牌初始化 |
| `client/scope.py` | 个人配置及词典范围校验 |
| `client/remote.py` | HTTPS 同步、三方比较、版本提交与恢复 |
| `client/dictionaries.py` | 原生个人词典快照交换与应用钩子 |
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
| 个人词典应用 | 采集本机学习数据，与远端数据合并，通过 Rime 原生机制更新实际用户词典 | 已实现快照目录交换和原生同步命令钩子，尚未完成三端原生导入联调 |
| 第三方词典刷新 | 按独立周期拉取指定上游词典，校验后更新本机副本 | 已实现项目配置驱动的 GitHub 词典刷新，默认雾凇拼音 |

`config/` 继续作为本地配置应用的唯一权威来源：服务端同步先合并更新此目录，再向输入法目录应用。配置编辑发生在 `config/`；实际目录中的配置修改不会自动反向采集。自动学习词典从实际输入法产生，使用独立的数据同步流程。

服务端提交必须携带基线版本，避免并发客户端相互覆盖；冲突、离线和上传失败时保留本地未上传内容，重试后再推进成功同步版本。配置合并成功、服务端提交成功、本地应用成功应分别记录，失败后可从对应阶段恢复。不能将本地快照交换成功等同于服务端同步或词典导入完成。

第三方词典采用独立的上游清单、刷新周期和版本记录；在暂存目录下载及校验后更新受管理文件，失败保留旧版本。个人配置、短语和个人词典不受刷新覆盖。该职责不自动包含第三方方案、Lua、OpenCC 或模型升级。公网服务地址与同步周期由 `remote.json` 配置，本机安装 ID 和设备令牌保存在私有 `device.local.json`；第三方上游清单见 `third-party.json`。


## 实际配置目录的发现与记忆

首次搜索规则位于 [`paths.json`](paths.json)，本机选择保存在私有 `paths.local.json`（0600、Git 忽略、不进入镜像或同步）。不需要先配置设备令牌：

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

`paths.json` 按 `wsl`、`macos`、`linux` 配置候选目录列表；所有候选都必须是展开后的绝对路径，不递归扫描。模板支持 `{home}`、`{xdg_config_home}` 和 WSL 专用 `{windows_appdata}`，也支持 `~`。例如：

```json
{
  "version": 1,
  "required_files": ["installation.yaml"],
  "candidates": {
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

该文件已通过 `*.local.json` 加入 Git 忽略规则，也不进入 Docker 构建或个人数据同步。初始化以 `0600` 权限原子写入，不输出令牌；不会联网验证令牌、自动注册设备、修改 Rime 的安装 ID 或自动开启 `remote.json`。服务端设备配置中的 ID 和令牌必须与此文件一致。

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
3. 在 Rime 同步目录接收其他设备的选定词典快照；有原生包装命令时按 `{dictionary}` 逐词典合并/导出，否则仅交换快照，仍需用户触发原生同步。
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

`remote/baseline.json` 记录服务端成功版本、配置合并基线和词典处理模式（`snapshots-only` 或 `native-command`）；它不代表 Rime 已重新部署。实际配置应用结果由原有 `manifest.json`/备份日志记录。网络中断、版本冲突或上传响应丢失都可重试；本地尚未上传的修改不丢弃。数据库恢复导致服务端版本回退时客户端停止，先核对数据再归档客户端旧基线、使用新状态目录重新同步，不自动重置版本。


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

刷新后需在 Rime 中重新部署才能加载新词典，本工具会提示但不自动重启或部署输入法。当前环境的真实 GitHub 下载验证受 DNS/网络限制未完成；测试通过模拟上游覆盖成功、哈希异常、下载中断、回滚与周期行为，尚未在 macOS/Windows 客户端验证重新部署效果。


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

如需无人值守，可提供 `--native-sync-command '["/absolute/path/to/native-sync-wrapper", "--dictionary", "{dictionary}"]'`。该参数为 JSON 参数数组，无 shell 解释；包装程序必须仅处理传入名称对应的词典，并**等待合并与导出实际完成**后以 0 退出。执行顺序为接收快照 → 原生合并/导出 → 发布本机快照。超时（300 秒）或失败会停止本轮发布并返回错误。仅发出异步请求立即退出的命令不符合约定；未配置此选项时需手动触发原生同步。`--dry-run` 不执行该命令。

词典快照在覆盖前备份至状态目录下 `dictionaries/backups/`，写入采用原子替换。交换不作整批回滚，失败可重试，已完成文件保持有效；不会删除快照或清空词条。服务锁仅协调本程序，不能锁住 Rime 或云盘；应等待原生同步完成后交换。修改中的快照会报错，请重试。所有快照和备份均含个人数据，使用私有存储。

按 [用户指南](README.md#后台运行) 执行 `--service install` 时传入同样的词典参数，即可启用后台交换。真实 Rime 合并尚未实机联调；测试使用保留元数据的模拟快照验证交换流程。


## 个人输入偏好（Windows 小狼毫）

根据确认的偏好维护以下个人文件，均已加入 `sync-manifest.json`：

| 文件 | 内容 |
| --- | --- |
| `config/default.custom.yaml` | 雾凇优先、朙月备用、9 候选、禁用左右 Shift 切换、`- =` 翻页 |
| `config/rime_ice.custom.yaml` | 默认简体、Emoji、长词补全、个人处理器，保留万象模型设置 |
| `config/luna_quanpin.custom.yaml` | 备用方案简体、9 候选及个人处理器 |
| `config/weasel.custom.yaml` | 横排、14 号字、明暗配色、程序初始英文名单 |
| `config/lua/hx_preferences.lua` | 中英文切换时提交去分隔符拼音，以及基于可见上下文的自动标点 |

- **中英文切换**：`Ctrl+Space` 切换。左右 Shift 不切换，CapsLock 保留大写功能。切换时将 `xi'an hao` 这样的输入提交为 `xianhao`，不提交候选中文；前端菜单切到英文时也处理未提交拼音。外部程序若拦截 Ctrl+Space，需调整其快捷键。
- **状态**：`global_ascii: false`，不跨窗口共享中英文状态。终端和编辑器通过 `app_options` 设置初始英文，允许在其中切到中文；不会每次按键强制英文。
- **默认英文程序**：Windows Terminal、CMD、PowerShell、WSL、Git Bash/mintty、WezTerm、Alacritty、Tabby、PuTTY、MobaXterm；VS Code/Insiders、Cursor、Windsurf、VSCodium、Sublime Text、Notepad++、Neovim-Qt、GVim、Emacs、Visual Studio，以及常见 JetBrains IDE。精确进程名清单位于 `weasel.custom.yaml`，浏览器、聊天软件和普通记事本不在名单内。
- **外观**：横排 9 候选，候选、序号、注释字号均为 14。跟随 Windows 明暗模式：浅色白底黑字，深色黑底白字；选中项为绿色矩形，序号和文字随主题使用黑/白色。窗口和候选高亮均无圆角。
- **输入能力**：默认简体，沿用当前雾凇的拼写纠错、英文及中英混输翻译器；模糊音规则在原方案中保持注释，不新增模糊音派生。启用 Emoji 与长词补全。备用朙月不具备完整雾凇混输和 Emoji 功能。
- **标点**：中文模式下，根据当前候选或本会话最近已提交字符选择：汉字后中文标点，ASCII 字母/数字后英文标点。中文引号等交由原生标点器处理；拼音串内的单引号仍是分隔符，中括号有候选时仍用于以词定字，`- =` 保留翻页。英文模式保持英文标点。
- **上下文限制**：此功能无法读取应用任意光标前文本。粘贴、鼠标移动、应用切换等情况下不能保证跟随真实上一个字符；能识别到的导航/快捷键后会放弃旧记录，无可靠记录时回退中文标点。这不是微信输入法偏好的直接导入，而是依据用户回答编写的 Rime 配置。

上述偏好写入项目配置后，仍需应用并重新部署小狼毫。Lua 已用模拟 Rime 上下文验证切换、去分隔符、标点、导航回退及翻页让行，主题、应用识别和真实输入体验仍需 Windows 验证。配色和应用选项仅针对小狼毫，macOS/Ubuntu 前端需要各自的外观配置。


## 自动系统服务注册

入口为 `client/sync.py --service install|uninstall|status`，实现集中在 `client/service.py`。操作用户级服务，不申请系统管理员权限。WSL 和 Ubuntu 走 Linux systemd 分支；macOS 走 launchd 分支。

- systemd：服务名 `rime-config.service`，写入 `$XDG_CONFIG_HOME/systemd/user/`（默认 `~/.config/systemd/user/`）。执行 daemon-reload、enable 和 restart。采用 `Restart=on-failure`、10 秒重试及 `UMask=0077`，禁用启动次数限制以支持长时间离线恢复。
- launchd：标签 `local.rime-config`，写入 `~/Library/LaunchAgents/local.rime-config.plist`。在 `gui/<uid>` 域执行 enable/bootstrap，更新时先 bootout。采用 RunAtLoad、非零退出重启、10 秒节流及私有 umask。日志位于 `~/Library/Logs/rime-config/`，不自动轮转。
- 使用当前 Python 的绝对路径和 `-u`，工作目录固定为项目目录，目标目录固定为安装时解析出的实际目录。只转存明确允许的持续运行参数；初始化、强制刷新及冲突选边等一次性动作不能与服务安装混用。
- 启动参数中的文件路径在安装时转为绝对路径。systemd 参数处理引号、反斜杠、`%` 和 `$` 的转义并拒绝控制字符；launchd 使用 `plistlib` 编码参数数组，不经过 shell。
- 安装先检测用户服务管理器，再用相同启动参数执行客户端 `--dry-run` 做离线预检查。预览注册本身不访问管理器、不执行预检查子进程、不写文件。
- 服务定义带安装器标记，以 0600 原子写入；拒绝符号链接和无标记的同名文件。重复安装替换本用户的同名服务。卸载、状态查询无需加载设备身份或发现目标目录，因此失效配置不会阻碍卸载。
- 注册失败会尝试恢复原服务文件及启用、运行状态；管理器持续不可用时仍尝试恢复文件，并明确报告未完成的恢复。安装成功仅代表管理器接受启动，不证明远端同步或原生词典导入成功。
- 服务不复制当前 shell 的令牌或代理环境变量。优先使用私有 `device.local.json`；如依赖代理或旧 `token_env`，需在用户服务管理器中另行配置环境。服务固定目标后，修改路径记忆不会改变已安装服务，需重新安装。

系统接口参考：[systemd.service](https://freedesktop.org/software/systemd/man/latest/systemd.service.html)、[systemd 参数语法](https://www.freedesktop.org/software/systemd/man/256/systemd.syntax.html)、[Apple LaunchAgent 指南](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/CreatingLaunchdJobs.html)。

测试使用模拟管理器覆盖两类服务的安装、更新、卸载、不可用管理器、注册失败恢复、参数转义和只读预览。当前执行环境未运行 systemd 用户管理器，也不是 macOS；真实登录自动启动与进程重启需在各平台验收。

## 开发与验证

以下命令均从仓库根目录执行：

```bash
# 无第三方 Python 依赖的应用/协议/客户端测试
python3 -m unittest discover -s tests -v
# 从仓库根目录构建测试镜像；运行时不需要网络或真实令牌
docker build -f server/Dockerfile --target test -t rime-config-test:local .
docker run --rm --network none --read-only --tmpfs /tmp rime-config-test:local
```

测试通过 WSGI 应用真实走鉴权、SQLite、版本校验，再驱动两个客户端进行配置拉取/合并/回传和词典快照交换；不连接真实 VPS 或 Rime 数据库。当前执行环境 Docker daemon 不可访问，因此容器构建、公共 Caddy 路由、TLS 及三端原生词典导入仍需在部署环境验收。


测试使用临时目录，覆盖配置备份、幂等性、目标漂移修复、受控删除、旧管理范围迁移、只读计划、符号链接与路径校验、失败回滚、平台路径检测，以及个人词典快照的双向交换、元数据校验、备份和原生同步钩子顺序。不会修改真实输入法配置。
