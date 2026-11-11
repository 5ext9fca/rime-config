# Rime 配置与同步用户指南

管理 Windows 原生、macOS 和 Ubuntu 上的 Rime 个人配置、自定义短语及自动学习词典，支持自建 HTTPS 云同步和独立刷新雾凇拼音词典。

**日常修改请编辑 `config/`。** 云同步先合并到该目录，再应用到输入法实际目录。直接修改实际目录中的受管理配置会被下次应用覆盖。

开发架构、协议与验收记录见 [PROJECT.md](PROJECT.md)；VPS 安装、备份与恢复见 [服务端部署指南](server/README.md)。

## 1. 安装与首次运行

先下载或克隆本项目，在项目根目录执行命令。需要 Python 3.9 或更新版本，Windows 建议 3.12 或更新版本。客户端核心无需额外 Python 包。

请先安装对应平台的 Rime 输入法、完整雾凇拼音方案及配置依赖的万象模型。本工具只刷新指定词典，不安装或升级完整方案、Lua、OpenCC 和模型。

| 平台 | 使用前准备 | 默认发现位置 |
| --- | --- | --- |
| Windows | 小狼毫、原生 Python；后台任务另需同一安装的 `pythonw.exe`、Windows PowerShell 5.1 和任务计划程序 | `%APPDATA%\Rime` |
| macOS | 鼠须管，在已登录的图形会话中运行 | `~/Library/Rime` |
| Ubuntu | Rime 前端；Fcitx5 前端偏好应用需要 `python3-gi`，内置首次词典导入需要 `rime_dict_manager` | `~/.config/ibus/rime`、`~/.config/fcitx5/rime`、`~/.config/fcitx/rime`、`~/.local/share/fcitx5/rime` |

Linux 支持 `XDG_CONFIG_HOME` 和 `XDG_DATA_HOME`。不支持 WSL，请使用 Windows 原生客户端。

Windows PowerShell：

```powershell
if (!(Test-Path remote.json)) { Copy-Item remote.json.example remote.json }
python rime.py --discover-target
python rime.py --dry-run
python rime.py
```

macOS / Ubuntu：

```bash
test -e remote.json || cp remote.json.example remote.json
python3 rime.py --discover-target
python3 rime.py --dry-run
python3 rime.py
```

模板默认关闭云同步；本地使用不需要设备令牌。普通运行会应用配置，并按周期检查第三方词典更新，可能联网；`--dry-run` 只预览，不联网或写文件。配置变化后会按自动维护策略等待空闲重新部署。

下文通用命令使用 `python3`，Windows 请换成 `python` 并使用本机路径。

### 选择或迁移输入法目录

发现多个目录时，明确选择已有目录：

```bash
python3 rime.py --discover-target --target /实际/Rime/目录
```

Windows 示例：`python rime.py --discover-target --target "D:\输入法\Rime"`。

选择保存在私有 `paths.local.json`。记忆目录失效时客户端会停止，不自动新建或切换。迁移后重新发现：

```bash
python3 rime.py --discover-target --rediscover-target
```

首次发现规则可在 [`paths.json`](paths.json) 调整；`--dry-run` 不保存选择。更改目标后重新安装后台服务以更新路径。

## 2. 修改配置与输入偏好

1. 编辑 `config/` 中相应文件，优先使用 `*.custom.yaml` 补丁；自定义短语写入 `config/custom_phrase.txt`。
2. 新增个人文件时，在 `sync-manifest.json` 的 `configuration.files` 中加入相对路径，不支持通配符。
3. 执行 `python3 rime.py --dry-run` 检查，再运行 `python3 rime.py` 应用；后台运行时会自动检查变化。

| 文件 | 用途 |
| --- | --- |
| [`sync-manifest.json`](sync-manifest.json) | 个人配置和自动学习词典的管理范围，两类分别由 `enabled` 开关控制 |
| [`third-party.json`](third-party.json) | 第三方词典上游、文件列表、刷新周期 |
| [`automation.json`](automation.json) | 自动部署、Linux 主题、日志和备份保留策略 |
| [`native-sync.json`](native-sync.json) | 原生词典维护周期、空闲门槛和重试策略 |
| `remote.json` | 本机 HTTPS 连接配置，由 [`remote.json.example`](remote.json.example) 复制 |
| `device.local.json`、`paths.local.json` | 本机身份、令牌及目录记忆，自动生成 |

禁用同步或缩小清单只停止管理，保留已有目标数据。删除仍在清单内、此前已管理的源文件则会传播删除，修改前会备份。不要把移出清单当作同步删除。

本机私有配置不进入 Git、镜像或云同步，不要复制其他设备的身份文件。项目、词典和备份目录应放在自己的用户目录中。

### 快捷键与外观

默认简体、不启用模糊音，保留雾凇纠错、中英混输、Emoji 与补全，每页 9 个候选。

| 平台 | 输入习惯与调整位置 |
| --- | --- |
| Windows / Linux | `Ctrl+Space` 切换中英文，切换时提交去分隔符拼音（`xi'an hao` → `xianhao`）；Shift 不切换，CapsLock 保留大写功能 |
| Windows | `-` / `=` 翻页；终端和编辑器初始英文名单、外观见 [`weasel.custom.yaml`](config/weasel.custom.yaml) |
| Ubuntu Fcitx5 | `Ctrl+Alt+Space` 激活/退出前端；输入偏好见 [`fcitx5/input.json`](config/fcitx5/input.json)，应用名单见 [`fcitx5.custom.yaml`](config/fcitx5.custom.yaml) |
| macOS | 鼠须管保持中文，`Ctrl+Space` 由系统切换输入源，英文使用系统英文输入源；外观见 [`squirrel.custom.yaml`](config/squirrel.custom.yaml) |

通用设置见 [`default.custom.yaml`](config/default.custom.yaml)，雾凇选项见 [`rime_ice.custom.yaml`](config/rime_ice.custom.yaml)。中文标点根据候选或最近提交字符判断，粘贴或移动光标后可能回退中文标点。

Windows 自定义图标需要本机准备 `icons/chinese.ico` 和 `icons/english.ico`，二进制图标不随个人配置云同步。Linux 主题由 `config/fcitx5/theme.json` 管理，默认自动应用；Classic UI 外观也会影响使用它的其他输入法。手动应用：

```bash
python3 client/platforms/linux/apply_fcitx5_theme.py --dry-run
python3 client/platforms/linux/apply_fcitx5_theme.py
```

### 修改后立即部署

需要立即检查配置效果时，在停止输入后运行：

```bash
python3 rime.py --deploy-now --dry-run
python3 rime.py --deploy-now
```

该命令备份并应用清单内的个人配置，然后立即部署，可能短暂打断输入。它跳过本次部署的空闲等待和失败退避，不联网、不刷新第三方词典、不同步个人词典；Linux 主题和前端偏好仍需正常运行应用。不能与 `--watch`、`--service`、`--sync-now` 或原生词典同步选项合用。

## 3. 启用多设备云同步

先按 [服务端指南](server/README.md) 部署服务，由维护者为每台设备配置独立令牌和 Rime 安装 ID。同一人的设备使用相同服务端用户，每台设备的 `installation_id` 必须唯一。

在本机 `remote.json` 中填写 HTTPS 地址并启用，其他字段可保留模板默认值：

```json
{
  "enabled": true,
  "url": "https://YOUR_PUBLIC_HOST/rime/v1/state",
  "interval_seconds": 60,
  "retry_seconds": 30,
  "timeout_seconds": 30,
  "token_refresh_seconds": 2592000,
  "auto_expand_dictionaries": true
}
```

```bash
python3 rime.py --init
python3 rime.py --sync-now
```

`--init` 读取安装 ID，隐藏输入令牌并保存到 `device.local.json`，不联网、不注册设备或修改 Rime 安装 ID。更换令牌时重新初始化。默认每 30 天自动刷新令牌，需要服务端支持；设 `token_refresh_seconds: 0` 可关闭。

使用其他连接文件时，每次运行和安装服务均携带 `--remote-config /路径/remote.local.json`。配置文件范围必须得到服务端授权；个人词典范围只有两端均允许自动扩展时才会自动追加。

### 自动学习词典

**快照传输成功不代表已导入输入法。** 自动合并、导出需要接入 Rime 原生全量同步入口。

Windows（替换为本机实际安装路径）：

```powershell
python rime.py --sync-now --weasel-deployer 'C:\Program Files\Rime\weasel-0.17.4\WeaselDeployer.exe'
python rime.py --service install --weasel-deployer 'C:\Program Files\Rime\weasel-0.17.4\WeaselDeployer.exe'
```

Ubuntu Fcitx5 / macOS 鼠须管：

```bash
python3 rime.py --native-sync-builtin --sync-now
python3 rime.py --native-sync-builtin --service install
```

其他 Unix 前端可配置 `--native-sync-all-command` 包装器，开发约定见 [原生全量同步](PROJECT.md#原生全量同步)。各原生入口不可混用。

默认原生维护至少间隔 15 分钟，失败也等待 15 分钟，键鼠空闲 30 秒后执行；无变化时每小时仍安排一次导出。`--sync-now` 和服务重启不绕过这些限制。`deferred` 表示等待条件满足，收到的快照会保留，不能视为已导入。KDE Wayland 建议持续后台运行以观察空闲；检测不可用时等待锁屏。

macOS 首次空闲维护可能重启鼠须管，以启用及时输出的完成日志，会短暂中断输入；之后已配置的进程不重复重启。

全量入口会自动补齐本机词典名称，仅增加、不移除；服务端授权不足时停止，需维护者扩展范围。支持的内置入口可首次导入范围内远端独有词典，但不会安装其方案或模型。自定义包装器和仅交换快照模式不自动建库。

未接入原生入口时：

1. 在输入法菜单执行“同步用户资料”，导出本机学习数据。
2. 运行客户端，交换词典快照。
3. 再执行“同步用户资料”，让 Rime 合并；后续客户端运行会上传新快照。

默认原生快照目录为实际目录下的 `sync/`；修改过 Rime `sync_dir` 时传入 `--rime-sync-dir /实际同步目录`。也可关闭远端同步，以 `--dictionary-store /私有共享目录 --device-id 本机安装ID` 使用共享目录交换快照。

### 处理配置冲突

两端同时修改同一文件时，客户端保留双方内容并停止该轮个人配置应用。根据日志找到状态目录中的 `remote/conflicts.json`，检查双方内容，在 `config/` 手动合并后执行：

```bash
python3 rime.py --resolve-conflicts local
```

要接受服务端版本，使用 `--resolve-conflicts remote`。选项作用于本轮**所有配置冲突**；选择远端会备份并覆盖本地冲突文件。不要未经检查直接选边。更详细的恢复语义见 [合并、删除与恢复](PROJECT.md#合并删除与恢复)。

## 4. 刷新第三方词典

[`third-party.json`](third-party.json) 默认从雾凇拼音上游每天检查一次，失败后 15 分钟重试。可修改开关、上游、文件列表和周期；失败保留上一可用版本，不覆盖个人补丁、短语和自动学习数据。

```bash
python3 rime.py --third-party-only --dry-run
python3 rime.py --third-party-only --refresh-third-party
```

普通运行及后台模式也会按周期检查。强制刷新仍遵守 `enabled` 开关；刷新后需重新部署，可由正常后台自动维护完成。入口词典 `rime_ice.dict.yaml`、`melt_eng.dict.yaml` 及方案依赖需自行维护。

## 5. 后台运行

自动安装当前用户的后台服务，无需手写服务文件或使用 sudo：

```bash
# 预览服务定义，不写文件、不调用系统服务管理器
python3 rime.py --service install --dry-run
# 安装、设置用户登录后自动运行，并立即启动
python3 rime.py --service install
# 查询运行状态
python3 rime.py --service status
# 停止服务、取消自动运行并删除服务定义
python3 rime.py --service uninstall
```

| 平台 | 注册方式 | 前提 |
| --- | --- | --- |
| Windows 原生 | 当前用户计划任务 `rime-config-<用户 SID>` | 原生 Python 含 pythonw.exe，任务计划程序可用 |
| Ubuntu | systemd 用户服务 | 当前用户会话可访问 systemd 用户管理器 |
| macOS | launchd 用户 LaunchAgent | 在已登录的图形用户会话中安装 |

Windows 任务在登录时启动，安装后也会立即启动；采用普通用户权限，无控制台窗口。除失败重试外，每分钟有恢复触发器，已有实例时忽略新启动；允许电池供电运行，不设单次运行时限。需要持续停用时请卸载或在任务计划程序中禁用任务，仅点击“结束”会在下个周期恢复。它不是登录前运行的 Windows SCM 服务。组织策略禁止创建任务时会报错，不自动提权。


安装时复用已记忆的实际配置目录，也可用参数明确指定：

```bash
python3 rime.py --service install --target /实际/Rime/目录 --interval 10
```

项目路径、Python 路径、目标目录和自定义参数会保存到服务定义中。支持保留 `--device-config`、`--paths-config`、`--paths-state`、`--sync-config`、`--remote-config`、`--third-party-config`、`--state-dir` 及个人词典参数；令牌仍从私有设备配置读取，不复制到服务文件。原生同步包装程序须使用绝对路径。

重复安装会更新并重启服务。迁移项目、Python 或目标目录，或更换启动参数后，应重新安装；只修改同步范围、远端配置或第三方刷新配置，无需重新安装。每个系统用户使用一个服务实例。若已有同名手写服务，安装器会提示先手动迁移，不直接覆盖。

Windows 日志位于 `%LOCALAPPDATA%\rime-config\logs\service.log`。每次后台进程启动时，超过 10 MiB 的旧日志保留为 `service.log.1`；持续运行期间不轮转。查看日志：

```powershell
Get-Content "$env:LOCALAPPDATA\rime-config\logs\service.log" -Tail 50 -Wait
```

其他平台查看日志：

```bash
# Ubuntu
journalctl --user -u rime-config.service -f
# macOS
tail -f ~/Library/Logs/rime-config/stdout.log ~/Library/Logs/rime-config/stderr.log
```

卸载仅移除后台服务，保留输入法配置、私有身份、词典、备份与日志。目标目录失效时也可查询或卸载服务。

升级旧版本后，也需携带原有持续参数重新安装服务；当前入口为根目录 `rime.py`，旧 `client/sync.py` 已移除。手工持续运行可用 `python3 rime.py --watch`，不要与后台服务同时启动。

## 6. 自动维护、日志与备份

`automation.json` 每轮重新读取，自动部署默认等待空闲 30 秒、失败后 900 秒重试。部署配置与词典合并分别记录，部署成功不等于个人词典已导入。

默认状态目录为 `~/.local/state/rime-config/<目标路径标识>/`，可用 `--state-dir` 指定。应用日志在其 `logs/` 子目录中，默认保留 30 天、每文件约 10 MiB 后新建文件。

已完成的受管理备份默认每天清理一次，保留 30 天且每类至少最近 7 份，由 `automation.json` 的 `backups` 控制。失败、中断或无法确认完成的备份保留；同步基线、冲突、待上传数据及私有身份不会被清理。旧自定义策略没有 `backups` 字段时默认关闭备份清理。

手工恢复前先停止后台同步，并将要长期保留的配置写回 `config/`。不要直接覆盖正在使用的词典数据库。服务端备份与人工恢复流程见 [服务端指南](server/README.md#维护与备份)，当前不提供异机备份或恢复向导。

## 7. 常见问题

| 情况 | 处理 |
| --- | --- |
| 找不到目录或候选不唯一 | 用 `--discover-target --target` 指定已有目录；迁移后重新发现并更新后台服务 |
| 应用后输入行为没变 | 检查是否等待空闲部署、完整方案和模型是否齐全；需要立即检查时运行 `--deploy-now` |
| 同步后看不到学习词条 | 检查原生合并是否成功；`deferred` 需等待空闲和维护周期，手动模式需再次执行“同步用户资料” |
| 云同步返回 401 / 403 | 检查设备令牌、服务端设备配置及两端范围授权 |
| 第三方下载失败或网络中断 | 保留现有数据，恢复网络后重试；持续模式会按配置周期重试 |
| 服务端恢复后报告版本回退 | 停止并按人工恢复流程核对数据与基线，不删除状态目录强行继续 |
| 想停用 Windows 后台任务 | 执行 `--service uninstall` 或禁用任务；仅结束进程会被恢复触发器重新启动 |

查看全部选项：`python3 rime.py --help`。只读查看结构化计划：`python3 rime.py --plan-json`；它不会联网或执行维护，不保证远端合并后的最终结果。平台验收范围、开发测试和实现限制统一见 [PROJECT.md](PROJECT.md)。
