# Rime 配置与同步

在 Windows 原生、WSL、macOS 和 Ubuntu 上管理 Rime 个人配置、自定义短语和自动学习词典，并通过自建服务在设备间同步。支持按项目配置定期刷新雾凇拼音词典。

**修改配置请编辑 `config/`。** 同步结果会先更新此目录，再应用到实际输入法目录；直接修改实际目录中的受管理配置，会被下次应用覆盖。

## 开始使用

需要 Python 3.9 或更新版本（Windows 建议 3.12 或更新版本），客户端无需额外 Python 包。请先安装对应平台的 Rime 输入法和完整雾凇拼音方案。本工具刷新词典，不负责安装或升级完整方案、Lua、OpenCC 和语言模型；配置依赖的万象模型需另行准备。

Windows 使用原生 Python 和 PowerShell，在本项目根目录执行：

```powershell
python client/sync.py --discover-target
python client/sync.py --dry-run
python client/sync.py --service install --dry-run
python client/sync.py --service install
python client/sync.py --service status
# 需要停止并取消登录自动运行时
python client/sync.py --service uninstall
```

自动发现 `%APPDATA%\Rime`；自定义目录使用 `--target "D:\输入法\Rime"`。Windows 无需 WSL。安装后台任务需要同一 Python 安装中的 `pythonw.exe`、Windows PowerShell 5.1 和可用的任务计划程序。请在自己的 Windows 登录会话中执行，任务仅在该用户登录期间运行。以下其他示例在 Windows 中将 `python3` 换成 `python`，使用 Windows 路径，跨行命令改为单行。

WSL、macOS、Ubuntu 命令均在本项目根目录执行：

```bash
# 查找并记住本机实际配置目录，不需要设备令牌
python3 client/sync.py --discover-target
# 预览：不联网、不修改文件
python3 client/sync.py --dry-run
# 应用一次；默认也会检查是否需要刷新第三方词典
python3 client/sync.py
```

应用完成后，在输入法菜单执行 **“重新部署”**。本工具不会自动重启或部署输入法。

| 平台 | 默认发现位置 |
| --- | --- |
| Windows 原生 | `%APPDATA%\Rime` |
| WSL / Windows 小狼毫 | Windows `%APPDATA%/Rime`；本机为 `/mnt/c/Users/hx/AppData/Roaming/Rime` |
| macOS / 鼠须管 | `~/Library/Rime` |
| Ubuntu | `~/.config/ibus/rime`、`~/.config/fcitx5/rime`、`~/.config/fcitx/rime`（支持 `XDG_CONFIG_HOME`） |

找到多个目录时，明确选择其中一个现有目录：

```bash
python3 client/sync.py --discover-target --target /实际/Rime/目录
```

首次搜索路径和标记文件可在 [`paths.json`](paths.json) 中调整。选择保存在私有 `paths.local.json`，后续自动复用。记忆的目录不存在时会停止；迁移目录后可重新发现：

```bash
python3 client/sync.py --discover-target --rediscover-target
```

指定 `--target` 也会更新记忆；`--dry-run` 不更新。修改目标后请重启正在运行的后台服务。

## 配置文件与同步范围

| 文件 | 用途 |
| --- | --- |
| [`config/`](config/) | 个人配置源文件，日常在此编辑 |
| [`sync-manifest.json`](sync-manifest.json) | 个人配置与个人词典的同步、应用范围 |
| [`third-party.json`](third-party.json) | 第三方词典上游、文件清单、刷新周期和开关 |
| [`remote.json`](remote.json) | 公网服务地址、同步周期和开关，默认禁用 |
| [`paths.json`](paths.json) | 各平台首次发现目录的规则 |
| `device.local.json` | 初始化生成的本机安装 ID、设备令牌和目录 |
| `paths.local.json` | 自动保存的各平台实际配置目录 |

Windows 新原子写入文件使用受保护的 ACL，仅文件所有者、SYSTEM 和管理员可访问；项目、快照与备份目录也应放在自己的用户目录内，避免共享目录继承宽松权限。Unix 继续使用 0600 文件权限。

两个 `*.local.json` 文件属于本机私有配置，不进入 Git、Docker 镜像或云同步。

在 `sync-manifest.json` 中：

- `configuration.files` 列出相对于 `config/` 的个人配置、短语或手工词库路径，不支持通配符。新增文件后应将其加入清单。
- `dictionaries.names` 列出自动学习词典名，不带后缀；当前为 `luna_pinyin` 和 `rime_ice`。
- 两类数据分别由 `enabled` 控制。禁用或从清单移除，只停止管理，保留目标数据。
- 删除 `config/` 中仍在清单内、此前已管理的文件，会同步删除对应目标文件；修改前会备份。

清单和刷新配置会自动重新加载。使用公网同步时，服务端清单也需允许这些文件与词典。仓库中留存的第三方资源不因存在于 `config/` 就参与个人同步。

## 启用多设备云同步

先按 [服务端部署指南](server/README.md) 部署 VPS，并为每台设备配置独立的安装 ID 和令牌。同一人的设备使用相同服务端用户，每台设备的 Rime `installation_id` 必须不同。

在 [`remote.json`](remote.json) 中填写 HTTPS 地址并启用：

```json
{
  "enabled": true,
  "url": "https://YOUR_PUBLIC_HOST/rime/v1/state",
  "interval_seconds": 60,
  "retry_seconds": 30,
  "timeout_seconds": 30
}
```

随后执行：

```bash
# 自动读取安装 ID，隐藏输入服务端为本设备分配的令牌
python3 client/sync.py --init
# 立即同步一次
python3 client/sync.py --sync-now
# 持续运行
python3 client/sync.py --watch
```

初始化将身份保存到 `device.local.json`，不自动注册服务端设备，也不修改 Rime 安装 ID。轮换令牌时重新运行 `--init`。只做本地配置应用无需初始化令牌。

### 自动学习词典

Windows 可以接入小狼毫原生全量同步（路径按本机安装位置调整）：

```powershell
# 单轮云同步；原生 /sync 仍遵守独立周期和空闲条件
python client/sync.py --sync-now --weasel-deployer 'C:\Program Files\Rime\weasel-0.17.4\WeaselDeployer.exe'
# 保存到后台任务；后续重新安装任务时也保留此参数
python client/sync.py --service install --weasel-deployer 'C:\Program Files\Rime\weasel-0.17.4\WeaselDeployer.exe'
```

云同步与原生维护分开调度，避免每分钟打断输入。根目录 [`native-sync.json`](native-sync.json) 默认规定：原生维护至少间隔 **15 分钟**，失败重试也至少间隔 15 分钟，Windows 键鼠空闲 **30 秒**后才执行；没有变化则跳过，每小时到期后仍等待空闲导出一次，以覆盖输入法内存中的学习数据。`--sync-now` 只强制云同步，不绕过原生维护限制。可用 `--native-sync-config` 指定其他策略文件；默认文件每轮重读，修改后无需重新安装任务。

收到新快照后会保留，等待维护条件满足再合并；此时状态为 `deferred`，不代表已导入。正常等待期间配置同步和已导出快照传输继续进行；上次原生失败留下的快照在再次验证成功前不上传。维护到期时只调用一次 `/sync`，等待全部原生任务完成并确认输入服务恢复。项目清单会自动补入本机用户数据库及 `sync/` 中的新词典名，保留旧名称；若服务端清单缺少这些名称，应同步修改服务端 `sync-manifest.json` 并重建容器，然后重试。不会自动回传 `/sync` 附带生成的配置备份或第三方资源。

Unix 同样使用全量同步和范围补齐规则，通过 `--native-sync-all-command '["/absolute/path/to/platform-native-sync-wrapper"]'` 指定平台包装器。包装器必须等待原生合并、导出成功并提供本轮完成凭据，不能只发送异步触发命令；协议见 [原生全量同步](PROJECT.md#原生全量同步)。本轮未配置或实机验证 Unix 包装器。

未接入原生命令时，使用以下手动流程：

1. 在 Rime 菜单执行“同步用户资料”，等待本机学习数据导出。
2. 运行客户端同步，将选定词典的快照上传，并接收其他设备的快照。
3. 再执行“同步用户资料”，由 Rime 合并到本机词典；后续客户端同步会上传新的快照。

**快照传输成功不代表已导入输入法。** 日常新学习的数据也需要先由 Rime 导出。默认快照目录是实际配置目录下的 `sync/`；如果修改过 Rime 的 `sync_dir`，运行时应传入 `--rime-sync-dir /实际同步目录`，WSL 使用 Linux 路径。

也可使用私有共享目录替代 VPS：

```bash
python3 client/sync.py --watch --device-id 本机安装ID \
  --dictionary-store /私有共享目录
```

此模式要求关闭 `remote.json` 的远端同步，各设备需访问同一共享目录，也可配合同样的全量原生入口。Windows 后台原生同步及真实 VPS 联调已完成，Unix 原生入口配置及其他平台实机验收仍待完成。

### 遇到配置冲突

不同设备同时修改同一个配置文件时会停止该轮个人配置应用，保留双方内容；不会自动拼接 YAML。冲突记录位于日志所示状态目录的 `remote/conflicts.json`。

检查双方内容后，在 `config/` 手工合并，再执行：

```bash
python3 client/sync.py --resolve-conflicts local
```

也可用 `--resolve-conflicts remote` 接受服务端版本。这两个选项会对本轮**所有配置冲突**选边，远端选边会覆盖并备份本地冲突文件。详细恢复方法见 [PROJECT.md](PROJECT.md#合并删除与恢复)。

## 刷新雾凇拼音词典

[`third-party.json`](third-party.json) 默认启用，每天检查一次，失败后 15 分钟重试。可调整 `enabled`、`interval_seconds`、`retry_seconds` 和 `source.files`。刷新不覆盖个人补丁、短语及自动学习词典。

```bash
# 预览刷新范围
python3 client/sync.py --third-party-only --dry-run
# 立即刷新，仍遵守 enabled 开关
python3 client/sync.py --third-party-only --refresh-third-party
```

普通运行和 `--watch` 也会按周期检查。刷新后需重新部署输入法。入口词典 `rime_ice.dict.yaml`、`melt_eng.dict.yaml` 及完整方案依赖需自行维护；Windows 已完成真实上游 17 个受管理文件的下载、校验和部署验证。

## 当前输入偏好

项目已配置默认简体、不启用模糊音，沿用雾凇纠错和中英混输，开启 Emoji 与补全。主要操作：

- `Ctrl+Space` 切换中英文，Shift 不切换，CapsLock 保留大写功能。切换时提交去掉空格和分隔符的拼音，例如 `xi'an hao` → `xianhao`。
- Windows 小狼毫使用 `-`、`=` 翻页；竖排列表、每页 9 候选、14 号字，黑/白半透明背景随系统主题切换，绿色圆角高亮。窗口圆角 12、候选圆角 7、阴影半径 12，背景约 90% 不透明，文字保持不透明。
- 不要求中英文状态跨窗口共享；终端和代码编辑器默认英文，仍可手动切换。程序名单及外观在 [`weasel.custom.yaml`](config/weasel.custom.yaml) 中调整，仅适用于 Windows 小狼毫。
- 中文模式下，标点根据当前候选或最近提交字符选择中英文形式。无法读取应用任意光标前文本，粘贴或移动光标后可能回退中文标点。

通用快捷键见 [`default.custom.yaml`](config/default.custom.yaml)，雾凇选项见 [`rime_ice.custom.yaml`](config/rime_ice.custom.yaml)。macOS 外观见 [`squirrel.custom.yaml`](config/squirrel.custom.yaml)，已加入本地同步清单：竖排列表、14 号字、系统毛玻璃叠加明暗黑白半透明底色（约 90% 不透明）、绿色圆角高亮；窗口圆角 12、高亮圆角 7、高亮阴影 12。候选数量沿用通用配置的 9 个。鼠须管使用系统字体回退，字体观感及窗口边距不保证与 Windows 像素一致；鼠须管的阴影作用于候选高亮，无法逐项等同 Windows 窗口阴影及偏移；仅迁移外观，不迁移 Windows 程序名单。这些偏好修改后仍需重新部署；当前 macOS UI 已于 2026-11-10 由用户确认验收通过。Ubuntu 外观需按前端另行配置。

已有服务端也必须在其 `sync-manifest.json` 中允许 `squirrel.custom.yaml`，才能通过 HTTPS 同步此文件。仅更新本地清单和应用配置不会自动修改远端范围或上传配置。

## 备份与常见问题

修改前的备份保存在 `~/.local/state/rime-config/<目标路径标识>/`，可用 `--state-dir` 指定。备份包含个人数据，不自动清理。手工恢复前先停止后台同步，并把要长期保留的修改写回 `config/`。

| 情况 | 处理 |
| --- | --- |
| 找不到目录或候选不唯一 | 检查 `paths.json`，用 `--discover-target --target` 明确选择 |
| 应用后输入行为没变 | 在输入法菜单重新部署，检查完整方案及模型依赖 |
| 词典同步后看不到词条 | 确认已执行 Rime 原生“同步用户资料”完成导入 |
| 云同步返回 401 / 403 | 分别检查设备令牌、客户端与服务端范围清单 |
| 第三方下载失败 | 检查网络，持续模式会按刷新配置重试 |

更多失败恢复及实现限制见 [PROJECT.md](PROJECT.md)。

## 后台运行

自动安装当前用户的后台服务，无需手写服务文件或使用 sudo：

```bash
# 预览服务定义，不写文件、不调用系统服务管理器
python3 client/sync.py --service install --dry-run
# 安装、设置用户登录后自动运行，并立即启动
python3 client/sync.py --service install
# 查询运行状态
python3 client/sync.py --service status
# 停止服务、取消自动运行并删除服务定义
python3 client/sync.py --service uninstall
```

| 平台 | 注册方式 | 前提 |
| --- | --- | --- |
| Windows 原生 | 当前用户计划任务 `rime-config-<用户 SID>` | 原生 Python 含 pythonw.exe，任务计划程序可用 |
| WSL | systemd 用户服务 | 已启用 systemd，且用户服务管理器可用 |
| Ubuntu | systemd 用户服务 | 当前用户会话可访问 systemd 用户管理器 |
| macOS | launchd 用户 LaunchAgent | 在已登录的图形用户会话中安装 |

Windows 任务在登录时启动，安装后也会立即启动；采用普通用户权限，无控制台窗口。除失败重试外，每分钟有恢复触发器，已有实例时忽略新启动；允许电池供电运行，不设单次运行时限。需要持续停用时请卸载或在任务计划程序中禁用任务，仅点击“结束”会在下个周期恢复。它不是登录前运行的 Windows SCM 服务。组织策略禁止创建任务时会报错，不自动提权。

WSL 服务仅在发行版和用户管理器运行期间工作，不会自动唤醒或启动 WSL。安装器不会修改 `/etc/wsl.conf`、启用 linger 或创建 Windows 计划任务。

安装时复用已记忆的实际配置目录，也可用参数明确指定：

```bash
python3 client/sync.py --service install --target /实际/Rime/目录 --interval 10
```

项目路径、Python 路径、目标目录和自定义参数会保存到服务定义中。支持保留 `--device-config`、`--paths-config`、`--paths-state`、`--sync-config`、`--remote-config`、`--third-party-config`、`--state-dir` 及个人词典参数；令牌仍从私有设备配置读取，不复制到服务文件。原生同步包装程序须使用绝对路径。

重复安装会更新并重启服务。迁移项目、Python 或目标目录，或更换启动参数后，应重新安装；只修改同步范围、远端配置或第三方刷新配置，无需重新安装。每个系统用户使用一个服务实例。若已有同名手写服务，安装器会提示先手动迁移，不直接覆盖。

Windows 日志位于 `%LOCALAPPDATA%\rime-config\logs\service.log`。每次后台进程启动时，超过 10 MiB 的旧日志保留为 `service.log.1`；持续运行期间不轮转。查看日志：

```powershell
Get-Content "$env:LOCALAPPDATA\rime-config\logs\service.log" -Tail 50 -Wait
```

其他平台查看日志：

```bash
# WSL / Ubuntu
journalctl --user -u rime-config.service -f
# macOS
tail -f ~/Library/Logs/rime-config/stdout.log ~/Library/Logs/rime-config/stderr.log
```

卸载仅移除后台服务，保留输入法配置、私有身份、词典、备份与日志。目标目录失效时也可查询或卸载服务。

## 跨平台执行计划

各平台共用配置变更、同步阶段依赖和原生维护调度规则；Windows、WSL/Linux、macOS 的原生入口与服务管理由平台执行器负责。只读 JSON 预览：

```bash
python client/sync.py --plan-json
```

有原生入口时沿用日常运行参数，例如 Windows 加上 `--weasel-deployer` 及其路径。预览不联网、不调用原生入口、不写状态或扩充同步清单；包含当前本地配置的文件指纹和阶段决策，不包含令牌或词典正文。远端合并后的文件计划在实际执行时重新生成，空闲状态在执行时检查，因此预览不承诺远端内容或最终执行结果。JSON 计划不能作为输入重放。服务定义仍使用 `--service install --dry-run` 预览。

实际执行的私有状态目录保存 `workflow-plan.json` 和 `workflow-result.json`；原生维护计划位于 `native-all/plan.json`。架构与契约见 [跨平台计划与执行](PROJECT.md#跨平台计划与执行)。

## Windows 验收记录

Windows 原生支持已于 2026-11-10 完成本轮验收，由用户确认接受。后台任务已安装并确认单实例运行、日志持续更新；回归测试为 85 项，其中 78 项通过、7 项因符号链接权限限制跳过。

本机现已连接 `https://198.13.57.54:8443/rime/v1/state`，后台每 60 秒检查云同步，网络失败后 30 秒重试；原生维护采用独立的 15 分钟限频和空闲检测。生产端 6 个配置文件、2 份词典快照核对通过；设备令牌仅保存在私有配置中。Windows 已接入原生 `/sync` 自动合并、导出及回传，模式为 `native-all`，每轮另记录是否完成或延后。最新 Windows 回归 99 项：92 通过、7 项因符号链接权限跳过。测试证据见 [Windows 验收总结](PROJECT.md#windows-验收总结)、[公网部署与同步验收](PROJECT.md#公网部署与同步验收) 和 [原生全量同步](PROJECT.md#原生全量同步)。

## macOS 验收记录

2026-11-10 合并远端后，回归 101 项通过、5 项 Windows 专用测试跳过，隔离词典原生合并和重复词频检查通过。Mac 已以独立设备接入 VPS：7 个配置、2 份本机快照核对一致，鼠须管实际合并 Windows 词条成功，重复 HTTPS 同步保持版本 18。新版 LaunchAgent 运行正常；macOS UI 已于 2026-11-10 由用户确认验收通过，验收版本启用系统毛玻璃、恢复默认行距 5。

本机正式云配置保存在 Git 忽略的 `remote.local.json`，仓库 `remote.json` 仍是禁用的示例。本机手动执行或重新安装服务时使用：

```bash
python3 client/sync.py --remote-config remote.local.json --sync-now
python3 client/sync.py --service install --remote-config remote.local.json
```

后台目前自动同步配置和快照，**尚未安装 macOS 无人值守原生包装器**。学习数据导出及接收快照导入仍需在鼠须管执行“同步用户资料”，快照传输不等于原生合并。详见 [macOS 公网与原生合并续验](PROJECT.md#macos-公网与原生合并续验2026-11-10)。

下一阶段由另一台 Ubuntu 实机开展 Linux 验收，步骤及未完成项见 [Ubuntu / Linux 验收交接](PROJECT.md#ubuntu--linux-验收交接)。
