# Rime 配置与同步

在 Windows 原生、macOS 和 Ubuntu 上管理 Rime 个人配置、自定义短语和自动学习词典，并通过自建服务在设备间同步。支持按项目配置定期刷新雾凇拼音词典。

**修改配置请编辑 `config/`。** 同步结果会先更新此目录，再应用到实际输入法目录；直接修改实际目录中的受管理配置，会被下次应用覆盖。

## 开始使用

需要 Python 3.9 或更新版本（Windows 建议 3.12 或更新版本），客户端无需额外 Python 包。请先安装对应平台的 Rime 输入法和完整雾凇拼音方案。本工具刷新词典，不负责安装或升级完整方案、Lua、OpenCC 和语言模型；配置依赖的万象模型需另行准备。

Windows 使用原生 Python 和 PowerShell，在本项目根目录执行：

```powershell
if (!(Test-Path remote.json)) { Copy-Item remote.json.example remote.json }
python rime.py --discover-target
python rime.py --dry-run
python rime.py --service install --dry-run
python rime.py --service install
python rime.py --service status
# 需要停止并取消登录自动运行时
python rime.py --service uninstall
```

自动发现 `%APPDATA%\Rime`；自定义目录使用 `--target "D:\输入法\Rime"`。Windows 无需 WSL。安装后台任务需要同一 Python 安装中的 `pythonw.exe`、Windows PowerShell 5.1 和可用的任务计划程序。请在自己的 Windows 登录会话中执行，任务仅在该用户登录期间运行。以下其他示例在 Windows 中将 `python3` 换成 `python`，使用 Windows 路径，跨行命令改为单行。

macOS、Ubuntu 命令均在本项目根目录执行：

```bash
# 首次使用复制禁用的模板；保留已存在的本机连接设置
test -e remote.json || cp remote.json.example remote.json
# 查找并记住本机实际配置目录，不需要设备令牌
python3 rime.py --discover-target
# 预览：不联网、不修改文件
python3 rime.py --dry-run
# 应用一次；默认也会检查是否需要刷新第三方词典
python3 rime.py
```

应用完成后，客户端按 `automation.json` 自动安排重新部署。本机 Fcitx5 会等待空闲；KDE Wayland 使用事件式输入空闲检测，接口不可用时等待锁屏。Windows/macOS 现有内置部署适配器，也可配置提供完成凭据的包装器；macOS 已完成实机验收，Windows 新增部署适配器仍待实机复验。

| 平台 | 默认发现位置 |
| --- | --- |
| Windows 原生 | `%APPDATA%\Rime` |
| macOS / 鼠须管 | `~/Library/Rime` |
| Ubuntu | `~/.config/ibus/rime`、`~/.config/fcitx5/rime`、`~/.config/fcitx/rime`、`~/.local/share/fcitx5/rime`（支持 `XDG_CONFIG_HOME` 和 `XDG_DATA_HOME`） |

找到多个目录时，明确选择其中一个现有目录：

```bash
python3 rime.py --discover-target --target /实际/Rime/目录
```

首次搜索路径和标记文件可在 [`paths.json`](paths.json) 中调整。选择保存在私有 `paths.local.json`，后续自动复用。记忆的目录不存在时会停止；迁移目录后可重新发现：

```bash
python3 rime.py --discover-target --rediscover-target
```

指定 `--target` 也会更新记忆；`--dry-run` 不更新。修改目标后请重启正在运行的后台服务。

## 配置文件与同步范围

| 文件 | 用途 |
| --- | --- |
| [`config/`](config/) | 个人配置源文件，日常在此编辑 |
| [`sync-manifest.json`](sync-manifest.json) | 个人配置与个人词典的同步、应用范围 |
| [`third-party.json`](third-party.json) | 第三方词典上游、文件清单、刷新周期和开关 |
| [`remote.json.example`](remote.json.example) | 公网连接模板，默认禁用；首次复制为 Git 忽略的 `remote.json` |
| [`paths.json`](paths.json) | 各平台首次发现目录的规则 |
| `device.local.json` | 初始化生成的本机安装 ID、设备令牌和目录 |
| `paths.local.json` | 自动保存的各平台实际配置目录 |

Windows 新原子写入文件使用受保护的 ACL，仅文件所有者、SYSTEM 和管理员可访问；项目、快照与备份目录也应放在自己的用户目录内，避免共享目录继承宽松权限。Unix 继续使用 0600 文件权限。

`remote.json` 和两个 `*.local.json` 文件属于本机私有配置，不进入 Git、Docker 镜像或云同步。客户端默认仍读取 `remote.json`；也可用 `--remote-config` 选择其他私有文件。

在 `sync-manifest.json` 中：

- `configuration.files` 列出相对于 `config/` 的个人配置、短语或手工词库路径，不支持通配符。新增文件后应将其加入清单。
- `dictionaries.names` 列出自动学习词典名，不带后缀；当前为 `luna_pinyin` 和 `rime_ice`。
- 两类数据分别由 `enabled` 控制。禁用或从清单移除，只停止管理，保留目标数据。
- 删除 `config/` 中仍在清单内、此前已管理的文件，会同步删除对应目标文件；修改前会备份。

清单和刷新配置会自动重新加载。使用公网同步时，服务端清单也需允许配置文件；词典范围可在两端开启自动扩展后按用户持久化追加。仓库中留存的第三方资源不因存在于 `config/` 就参与个人同步。

## 启用多设备云同步

先按 [服务端部署指南](server/README.md) 部署 VPS，并为每台设备配置独立的安装 ID 和令牌。同一人的设备使用相同服务端用户，每台设备的 Rime `installation_id` 必须不同。

将 [`remote.json.example`](remote.json.example) 复制为本机 `remote.json`（已有文件不要覆盖），在 `remote.json` 中填写 HTTPS 地址并启用：

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
python3 rime.py --init
# 立即同步一次
python3 rime.py --sync-now
# 持续运行
python3 rime.py --watch
```

初始化将身份保存到 `device.local.json`，不自动注册服务端设备，也不修改 Rime 安装 ID。自动新设备注册明确不在实现范围内，设备由维护者在服务端手动配置。轮换令牌时重新运行 `--init`。只做本地配置应用无需初始化令牌。

### 自动学习词典

Windows 可以接入小狼毫原生全量同步（路径按本机安装位置调整）：

```powershell
# 单轮云同步；原生 /sync 仍遵守独立周期和空闲条件
python rime.py --sync-now --weasel-deployer 'C:\Program Files\Rime\weasel-0.17.4\WeaselDeployer.exe'
# 保存到后台任务；后续重新安装任务时也保留此参数
python rime.py --service install --weasel-deployer 'C:\Program Files\Rime\weasel-0.17.4\WeaselDeployer.exe'
```

云同步与原生维护分开调度，避免每分钟打断输入。根目录 [`native-sync.json`](native-sync.json) 默认规定：原生维护至少间隔 **15 分钟**，失败重试也至少间隔 15 分钟，Windows 键鼠空闲 **30 秒**后才执行；没有变化则跳过，每小时到期后仍等待空闲导出一次，以覆盖输入法内存中的学习数据。`--sync-now` 只强制云同步，不绕过原生维护限制。可用 `--native-sync-config` 指定其他策略文件；默认文件每轮重读，修改后无需重新安装任务。

收到新快照后会保留，等待维护条件满足再合并；此时状态为 `deferred`，不代表已导入。正常等待期间配置同步和已导出快照传输继续进行；上次原生失败留下的快照在再次验证成功前不上传。维护到期时只调用一次 `/sync`，等待全部原生任务完成并确认输入服务恢复。项目清单会自动补入本机用户数据库及 `sync/` 中的新词典名，保留旧名称；若服务端清单缺少这些名称，应同步修改服务端 `sync-manifest.json` 并重建容器，然后重试。不会自动回传 `/sync` 附带生成的配置备份或第三方资源。

Unix 同样使用全量同步和范围补齐规则，通过 `--native-sync-all-command '["/absolute/path/to/platform-native-sync-wrapper"]'` 指定平台包装器。包装器必须等待原生合并、导出成功并提供本轮完成凭据，不能只发送异步触发命令；协议见 [原生全量同步](PROJECT.md#原生全量同步)。本轮未配置或实机验证 Unix 包装器。

未接入原生命令时，使用以下手动流程：

1. 在 Rime 菜单执行“同步用户资料”，等待本机学习数据导出。
2. 运行客户端同步，将选定词典的快照上传，并接收其他设备的快照。
3. 再执行“同步用户资料”，由 Rime 合并到本机词典；后续客户端同步会上传新的快照。

**快照传输成功不代表已导入输入法。** 日常新学习的数据也需要先由 Rime 导出。默认快照目录是实际配置目录下的 `sync/`；如果修改过 Rime 的 `sync_dir`，运行时应传入 `--rime-sync-dir /实际同步目录`。

也可使用私有共享目录替代 VPS：

```bash
python3 rime.py --watch --device-id 本机安装ID \
  --dictionary-store /私有共享目录
```

此模式要求关闭 `remote.json` 的远端同步，各设备需访问同一共享目录，也可配合同样的全量原生入口。Windows 后台原生同步及真实 VPS 联调已完成，Unix 原生入口配置及其他平台实机验收仍待完成。

### 遇到配置冲突

不同设备同时修改同一个配置文件时会停止该轮个人配置应用，保留双方内容；不会自动拼接 YAML。冲突记录位于日志所示状态目录的 `remote/conflicts.json`。

检查双方内容后，在 `config/` 手工合并，再执行：

```bash
python3 rime.py --resolve-conflicts local
```

也可用 `--resolve-conflicts remote` 接受服务端版本。这两个选项会对本轮**所有配置冲突**选边，远端选边会覆盖并备份本地冲突文件。详细恢复方法见 [PROJECT.md](PROJECT.md#合并删除与恢复)。

## 刷新雾凇拼音词典

[`third-party.json`](third-party.json) 默认启用，每天检查一次，失败后 15 分钟重试。可调整 `enabled`、`interval_seconds`、`retry_seconds` 和 `source.files`。刷新不覆盖个人补丁、短语及自动学习词典。

```bash
# 预览刷新范围
python3 rime.py --third-party-only --dry-run
# 立即刷新，仍遵守 enabled 开关
python3 rime.py --third-party-only --refresh-third-party
```

普通运行和 `--watch` 也会按周期检查。刷新后需重新部署输入法。入口词典 `rime_ice.dict.yaml`、`melt_eng.dict.yaml` 及完整方案依赖需自行维护；Windows 已完成真实上游 17 个受管理文件的下载、校验和部署验证。

## 当前输入偏好

项目已配置默认简体、不启用模糊音，沿用雾凇纠错和中英混输，开启 Emoji 与补全。主要操作：

- Windows/Linux：`Ctrl+Space` 切换中英文，Shift 不切换，CapsLock 保留大写功能。切换时提交去掉空格和分隔符的拼音，例如 `xi'an hao` → `xianhao`。
- macOS：鼠须管固定中文，终端与编辑器也使用中文模式。`Ctrl+Space` 由系统处理，英文输入使用系统英文输入源；鼠须管内部的英文状态会自动恢复为中文。用户已明确接受此行为。
- Windows 小狼毫使用 `-`、`=` 翻页；竖排列表、每页 9 候选、14 号字，黑/白半透明背景随系统主题切换，绿色圆角高亮。窗口圆角 12、候选圆角 7、阴影半径 12，背景约 90% 不透明，文字保持不透明。
- 不要求中英文状态跨窗口共享；终端和代码编辑器默认英文，仍可手动切换。程序名单及外观在 [`weasel.custom.yaml`](config/weasel.custom.yaml) 中调整，仅适用于 Windows 小狼毫。
- 中文模式下，标点根据当前候选或最近提交字符选择中英文形式。无法读取应用任意光标前文本，粘贴或移动光标后可能回退中文标点。

通用快捷键见 [`default.custom.yaml`](config/default.custom.yaml)，雾凇选项见 [`rime_ice.custom.yaml`](config/rime_ice.custom.yaml)。macOS 外观见 [`squirrel.custom.yaml`](config/squirrel.custom.yaml)，已加入本地同步清单：竖排列表、14 号字、系统毛玻璃叠加明暗黑白半透明底色（约 90% 不透明）、绿色圆角高亮；窗口圆角 12、高亮圆角 7、高亮阴影 12。候选数量沿用通用配置的 9 个。鼠须管使用系统字体回退，字体观感及窗口边距不保证与 Windows 像素一致；鼠须管的阴影作用于候选高亮，无法逐项等同 Windows 窗口阴影及偏移；仅迁移外观，不迁移 Windows 程序名单。这些偏好修改后仍需重新部署；当前 macOS UI 已于 2026-11-10 由用户确认验收通过。Ubuntu Fcitx5 外观见下方 Linux 主题说明。

已有服务端也必须在其 `sync-manifest.json` 中允许 `squirrel.custom.yaml`，才能通过 HTTPS 同步此文件。仅更新本地清单和应用配置不会自动修改远端范围或上传配置。

## 备份与常见问题

修改前的备份保存在 `~/.local/state/rime-config/<目标路径标识>/`，可用 `--state-dir` 指定。备份包含个人数据；已完成的受管理备份按 `automation.json` 的 `backups` 策略清理，默认保留 30 天且每类至少保留最近 7 份。失败、中断及无法确认完成的旧备份保留。手工恢复前先停止后台同步，并把要长期保留的修改写回 `config/`。

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

## 跨平台执行计划

各平台共用配置变更、同步阶段依赖和原生维护调度规则；Windows、Linux、macOS 的原生入口与服务管理由平台执行器负责。只读 JSON 预览：

```bash
python rime.py --plan-json
```

有原生入口时沿用日常运行参数，例如 Windows 加上 `--weasel-deployer` 及其路径。预览不联网、不调用原生入口、不写状态或扩充同步清单；包含当前本地配置的文件指纹和阶段决策，不包含令牌或词典正文。远端合并后的文件计划在实际执行时重新生成，空闲状态在执行时检查，因此预览不承诺远端内容或最终执行结果。JSON 计划不能作为输入重放。服务定义仍使用 `--service install --dry-run` 预览。

实际执行的私有状态目录保存 `workflow-plan.json` 和 `workflow-result.json`；原生维护计划位于 `native-all/plan.json`。架构与契约见 [跨平台计划与执行](PROJECT.md#跨平台计划与执行)。

## Windows 验收记录

2026-11-10 新入口续验已将本机任务迁移到根目录 `rime.py`，保留原有设备身份、基线、备份和原生限频参数。170 项回归中 153 通过、17 项按平台条件跳过；隔离 DLL 首次建库、多设备词频合并和真实输入引擎检查通过。17 个配置范围项与真实 HTTPS、本机配置源及适用目标一致，原生 `/sync` 合并导出及回传、内置自动部署和部署后资源指纹复核已验证。已合并 `f6a5020` 的重试修复，最终 HTTPS 核对版本为 44。桌面 UI 和新入口重新登录触发仍需现场确认，详情见 [Windows 新入口续验](PROJECT.md#windows-新入口续验2026-11-10排除桌面-ui)。下列为此前各阶段的历史记录。

Windows 原生支持已于 2026-11-10 完成本轮验收，由用户确认接受。后台任务已安装并确认单实例运行、日志持续更新；回归测试为 85 项，其中 78 项通过、7 项因符号链接权限限制跳过。

本机现已连接 `https://198.13.57.54:8443/rime/v1/state`，后台每 60 秒检查云同步，网络失败后 30 秒重试；原生维护采用独立的 15 分钟限频和空闲检测。生产端 6 个配置文件、2 份词典快照核对通过；设备令牌仅保存在私有配置中。Windows 已接入原生 `/sync` 自动合并、导出及回传，模式为 `native-all`，每轮另记录是否完成或延后。最新 Windows 回归 99 项：92 通过、7 项因符号链接权限跳过。测试证据见 [Windows 验收总结](PROJECT.md#windows-验收总结)、[公网部署与同步验收](PROJECT.md#公网部署与同步验收) 和 [原生全量同步](PROJECT.md#原生全量同步)。

## macOS 验收记录

2026-11-10 合并远端至 `1e30035` 并升级新入口后，回归 167 项：160 通过、7 项其他平台测试跳过。真实引擎、隔离原生合并、首次词典导入与重复词频检查通过；后台自动部署已取得真实成功凭据，部署后资源指纹一致；LaunchAgent 更新、卸载恢复、异常重启和单实例通过。先前 UI 和注销登录启动已由用户确认，本轮不重复 UI 验收。

本机正式云配置保存在 Git 忽略的 `remote.local.json`，仓库模板为禁用的 `remote.json.example`。本机已启用内置全量同步，日常执行或重新安装服务时保留参数：

```bash
python3 rime.py --remote-config remote.local.json --native-sync-builtin --sync-now
python3 rime.py --remote-config remote.local.json --native-sync-builtin --service install
```

后台现在自动合并、导出及回传个人词典，模式为 `native-all`。输入活跃或未到维护间隔时记录 deferred；`--sync-now` 和服务重启不绕过 900 秒限频。此次实测发现并修复鼠须管日志缓冲导致完成摘要不可见的问题；按默认失败重试恢复后，两个词典取得真实成功凭据，17 个配置范围项（含 1 个删除标记）和 2 份本机快照与 HTTPS revision 40 一致。日志配置与首次空闲重启行为见 [内置维护说明](#内置原生维护)，详细证据见 [macOS 新入口与内置维护续验](PROJECT.md#macos-新入口与内置维护续验2026-11-10)。

Ubuntu 实机验收已完成，结果及能力边界见 [Ubuntu 实机验收](PROJECT.md#ubuntu--linux-实机验收2026-11-10)。

## Ubuntu / Fcitx5 实机运行

Fcitx5 Rime 通常使用 `~/.local/share/fcitx5/rime`（支持 `XDG_DATA_HOME`）；保留旧的配置目录候选。多个目录并存时用 `--target` 明确选择。

本机已完成配置应用、HTTPS 同步、systemd 生命周期、真实重新登录自动启动及用户 UI 验收。后台已启用 `--native-sync-builtin`，使用 `native-all` 在空闲/锁屏后自动合并并导出个人词典；2026-11-10 已完成真实锁屏触发和云端回传验收。未到维护间隔或尚未空闲时记录 deferred，不能当作本轮导入成功。不要将隔离验收脚本用作生产原生包装器。

使用私有云配置时，单次执行与安装后台服务都要传入：

```bash
python3 rime.py --remote-config remote.local.json --sync-now
python3 rime.py --remote-config remote.local.json --service install
python3 rime.py --service status
```

已实测注销后重新登录自动启动及 HTTPS 同步成功。日常运行 `--service status` 检查 active/running；使用 `journalctl --user -u rime-config.service -b` 查看启动及同步记录。无需开启 linger，也不要同时手工启动第二个持续进程。详细验证边界见 [Ubuntu 实机验收](PROJECT.md#ubuntu--linux-实机验收2026-11-10)。

### Linux 外观主题

当前 Linux UI 已由用户确认验收通过：约 10% 透明，背景模糊关闭。

`config/fcitx5/` 保存从 Windows/macOS hx 外观迁移的 Fcitx5 Classic UI 明暗主题：竖排、14 号字、黑白半透明底色（约 90% 不透明）、绿色高亮、窗口圆角 12、高亮圆角 7 和柔和窗口阴影。明暗跟随系统；候选数沿用 Rime 的 9 个。背景模糊已关闭，保留 约 90% 不透明的底色，直接透出背景细节。Classic UI 外观也会影响使用它的其他输入法。

```bash
python3 client/platforms/linux/apply_fcitx5_theme.py --dry-run
python3 client/platforms/linux/apply_fcitx5_theme.py
```

应用命令将主题复制到 `$XDG_DATA_HOME/fcitx5/themes`（默认 `~/.local/share`），合并 `$XDG_CONFIG_HOME/fcitx5/conf/classicui.conf`（默认 `~/.config`）的外观项，保留其他选项，并重新加载 Classic UI。原文件和回滚清单保存在 `private/fcitx5-theme/`；失败恢复文件。无需重新部署 Rime。

这些前端资源以 `config/fcitx5/theme.json` 文本资源包加入个人云同步，沿用三方比较和冲突保留；仅 Linux 自动应用到 Fcitx5，其他平台仅保存资源包，不复制到 Rime 用户目录。直接修改资源包可同步；修改开发用主题源后，重建资源包可运行 `python3 client/platforms/linux/generate_fcitx5_theme.py`（开发环境需要 Pillow），再执行应用命令。常规安装使用仓库中的 PNG，无需 Pillow。

macOS 注销后重新登录自动启动验收已由用户确认完成。恢复向导明确不在实现范围内；服务端恢复后继续按人工流程核对数据及重建同步基线，版本回退时客户端仍会停止以保护数据。

## 自动维护

当前 Ubuntu 已启用以下功能；服务端需要配套版本，旧客户端仍可继续使用原有状态接口。

| 功能 | 配置及默认策略 |
| --- | --- |
| 自动令牌刷新 | `remote.json` / 私有覆盖文件中的 `token_refresh_seconds: 2592000`，每 30 天轮换；最短 86400 秒，设为 0 关闭 |
| 服务端词典范围扩展 | 客户端 `auto_expand_dictionaries: true`，服务端也必须启用；按用户追加，默认最多 128 个名称 |
| Linux 主题同步应用 | `sync-manifest.json` 包含 `fcitx5/theme.json`；`automation.json` 的 `linux_theme: true` 控制自动应用 |
| 自动重新部署 | `automation.json` 的 `deployment`，变更指纹成功后不重复部署，失败默认 900 秒重试 |
| 客户端日志过期清理 | `automation.json` 的 `logs`，后台日志保留 30 天，每文件约 10 MiB 后新建文件 |
| 服务端备份及清理 | 独立容器每日备份数据库、设置与范围，保留 30 天且至少最近 7 套；只清理有完整性凭据的自动备份套件 |

自动令牌刷新要求使用私有 `device.local.json`，不支持只从环境变量取得令牌的旧式身份。客户端先持久化待轮换令牌，再提交刷新；响应丢失会使用同一个候选令牌重试。旧令牌有 24 小时普通请求宽限期，过期后仅允许携带当前新令牌完成原轮换重试。服务端保存令牌哈希；撤销设备或更换服务端初始令牌会撤销其派生令牌。不要在另一台设备复制身份文件。刷新不会自动注册设备。

范围扩展只处理客户端清单中的个人词典名；全量原生模式仍会先补齐本机范围。配置文件授权不会自动扩大，第三方资源不会进入个人词典范围；关闭词典同步或服务端自动扩展开关时不会绕过限制。服务端增量范围存于 SQLite，普通扩展不需重建容器。

`automation.json` 每轮重读，也可用 `--automation-config /绝对路径/文件.json` 指定，并随服务安装参数持久化。它不属于云同步内容，远端主题不能携带部署命令。部署与词典原生合并是两件事；自动部署不等于已实现无人值守词典合并。

KDE Wayland 通过 `ext_idle_notifier_v1` 版本 2 持续订阅输入空闲及恢复事件，达到配置阈值后可自动重新部署，无需锁屏。首次连接、服务重启或阈值变化后重新等待阈值；断线、接口缺失时退回锁屏判断。监听复用 Python 标准库，无需新增软件包；用户服务须具有当前会话的 `WAYLAND_DISPLAY` 和 `XDG_RUNTIME_DIR`。单轮进程通常先记录 deferred，持续后台运行才能保留监听。Windows、macOS 已增加内置部署适配器（macOS 实机验收已完成，Windows 待复验）；自定义包装器仍优先，可在 `deployment.commands` 按平台配置绝对路径参数数组；包装器须检查 `RIME_DEPLOY_IDLE_SECONDS`，通过前端部署并等待真实完成，在 `RIME_DEPLOY_RECEIPT` 写入 `{"status":"success"}`，未开始时可写 `{"status":"deferred"}`。目标由 `RIME_USER_DIR` 传入；240 秒超时或缺少凭据视为失败。不能把异步通知返回 0 当成成功。

后台应用日志位于当前 `--state-dir` 下的 `logs/rime-日期-编号.log`（默认 `~/.local/state/rime-config/<目标标识>/logs/`）。过期清理只处理这些受管理日志，保留同步基线、待确认上传、个人快照、配置备份及历史验收证据。旧版 launchd/Windows 外层日志和系统 journal 仍由原有机制管理，不进行全局清理。服务端应用日志也按 30 天清理，Docker 启动日志另限制为 3×10 MiB。

### 客户端备份保留

`automation.json` 新增独立策略（不与日志保留混用）：

```json
"backups": {
  "enabled": true,
  "retention_days": 30,
  "keep_minimum": 7,
  "interval_seconds": 86400
}
```

每轮检查调度，默认每天清理一次。范围为当前状态目录中的配置、远端配置、快照交换、第三方词典、主题、成功原生运行及已完成的清单变更备份；各类分别保留至少 7 份。只有同时超过保留期且不在最近保留数内才删除。失败/中断/未确认的备份、当前最新原生运行、存在待确认上传或同步失败时的远端备份均保留。同步基线、冲突内容、活动词典、待上传快照、私有凭据和历史验收目录不会清理。

新备份由写入方成功完成后登记 `.completed/` 凭据；旧配置/第三方备份可通过 `journal.json` 的 applied 状态识别，旧原生运行通过 success 结果识别，其余没有可靠完成证据的历史备份保留。清理使用对应写入锁，遇到忙碌或异常目录则延后。老的自定义 `automation.json` 若没有 `backups` 字段，默认关闭清理；项目默认配置已开启。

用 `python3 rime.py --dry-run` 查看待删除项（`backup-prune-plan`），预览不写文件、不加锁。`--plan-json` 的 version=3 工作流单独显示 `backup-cleanup` 阶段。独立主题应用命令也对自己管理的已完成备份应用同一策略。

### 服务端独立自动备份

Compose 的 `backup` 服务每 60 秒检查持久化调度，默认每天执行一次，不依赖 API 访问或健康检查触发。它没有网络接口，共用数据卷及只读设置/范围清单。首次升级会自动生成包含配置的完整备份套件；备份后验证 SQLite 完整性和各文件 SHA-256，再执行保留清理。

查看状态：`docker compose ps backup` 和 `docker compose logs --tail=20 backup`。需要立即额外备份时，在服务端运行 `docker compose exec backup python -m server.backup_worker --once --force`，仍遵守并发锁及保留规则。数据库恢复仍按人工流程处理，没有新增恢复向导。

## 内置原生维护

Ubuntu Fcitx5 和 macOS 鼠须管可使用 `--native-sync-builtin` 接入全量原生同步，不能与 `--native-sync-command`、`--native-sync-all-command` 或 `--weasel-deployer` 混用。Windows 原生全量同步继续使用已验收的 `--weasel-deployer`。先预览，再用相同参数更新用户服务：

```bash
python3 rime.py --remote-config remote.local.json --native-sync-builtin --dry-run --plan-json
python3 rime.py --remote-config remote.local.json --native-sync-builtin --service install
```

内置入口复用 `native-sync.json` 的持久化限频、空闲、失败重试和全范围预检查。Fcitx5 通过本轮 journal 游标、前端 PID、操作类型和开始/完成通知确认；鼠须管通过当前进程的新日志区段、任务开始和成功总数、词典集合及新快照确认。鼠须管需要可读的 INFO 日志；只有命令返回 0 不算完成。Linux 空闲检测不可用时仍等待锁屏。两种维护共用前端锁，失败不发布未经确认的输出；不直接操作活动数据库。

Windows 内置重新部署从当前用户/机器注册表定位唯一 `WeaselDeployer.exe`，检查注册目标、输入空闲和部署互斥，运行 `/deploy`，核对本次进程日志并探测输入服务恢复。macOS 使用已运行的唯一鼠须管进程、CoreGraphics 空闲检测及 `--reload`，等待新增日志的部署任务完成。自定义 `deployment.commands` 仍优先。

macOS 内置维护需要及时读取鼠须管日志。客户端在真实空闲且取得维护锁后检查鼠须管的 `GLOG_logbufsecs=0`；若未设置，会正常退出鼠须管，再通过 `open --env` 以进程专属无缓冲日志重新启动，短暂中断输入。每个已正确配置的鼠须管进程只需检查，不重复重启；系统登录后若启动了未带该变量的实例，下次空闲维护会重新配置。不会修改全局 launchctl 环境或应用包。随后以新进程 PID 和本轮日志偏移确认原生任务完成；重启失败或缺少完成摘要时继续禁止发布未经确认的快照，并保留重试限频。

Ubuntu 和 macOS 已完成内置原生同步及重新部署实机验收；Windows 新增部署适配器仍待对应设备复验。两端后台已启用内置全量入口，原生维护仍须满足空闲/锁屏条件，状态 deferred 不表示导入成功。

兼容配置准备新增 `melt_eng.schema.yaml`、`radical_pinyin.schema.yaml`、对应两个 custom 补丁、`hx_english_algebra.yaml` 和 `grammar.yaml`。它们消除内部拼写回引，并保留原有编译结果；两个方案是项目维护的兼容副本，第三方词典刷新不更新它们。用户已批准 VPS 范围扩展及本机启用：生产清单现为 14 个配置文件，六个兼容文件已通过 HTTPS 同步并应用到 Ubuntu。

本机上线验证：用户锁屏后，Fcitx5 自动重新部署与两个个人词典的原生全量合并均成功；14 个配置和两份本机快照与 HTTPS 返回一致（验收 revision=30）。随后维护计划按 900 秒最小间隔延后，服务 active/running、无异常重启。真实部署日志中未出现本轮针对的循环依赖或缺失 grammar 警告。上述为 Ubuntu 阶段记录；macOS 后续验收结果见 [macOS 验收记录](#macos-验收记录)，Windows 新增部署适配器仍待实机复验。

## 远端独有词典首次导入与支持范围

内置全量同步（Ubuntu Fcitx5、macOS 鼠须管）及 Windows `--weasel-deployer` 现在支持首次导入：词典名必须在客户端清单及服务端授权范围内；若收到有效快照但本机尚无该数据库，客户端先在实际目录所在文件系统的私有隔离目录中调用 Rime 原生 restore/backup，合并该名称的各设备快照并校验导出身份。成功关闭数据库后，仅向不存在的目标路径原子发布，再执行正常的前端全量同步及完成验证。不会自动导入清单外词典，也不会下载对应方案、基础词库或模型。

已有数据库只走原生全量同步，不被初始化流程复制或覆盖。并发创建、原生导入失败、空间不足或文件系统不支持原子“不覆盖”移动时停止本轮，保留快照并按既有策略重试；部分初始化已完成时，下轮继续正常原生合并，不重复累加词频。初始化成功不等于前端同步成功，后续原生完成凭据未确认前仍禁止上传。Linux 需安装 `rime_dict_manager`；macOS 使用鼠须管随附工具；Windows 使用已配置小狼毫的 librime levers API。自定义包装器及仅交换快照模式不自动取得此能力。

按用户要求，WSL 客户端支持已移除：不再提供路径发现、平台计划、服务分派或 Windows 互操作桥接；在 WSL 中运行明确报错，请使用 Windows 原生客户端。旧路径配置中的 wsl 候选仅在读取时丢弃，私有记忆及旧设备数据不删除；旧 WSL 服务应在原环境手动停用，避免它继续运行旧代码。

异机备份明确不实现。服务端保留同机定时完整备份、过期清理及隔离恢复验证；自动新设备注册和恢复向导也继续不实现。


当前客户端入口为 `python3 rime.py`；旧 `client/sync.py` 已移除。升级已有后台服务后，使用原先的持续参数重新运行 `python3 rime.py --service install ...`，使 systemd、launchd 或 Windows 登录任务指向新入口。设备身份、令牌、同步基线、备份和清单格式保持原状。仅包含新前端偏好的工作流计划升级为 version=4。

Ubuntu 的 `config/fcitx5/input.json` 管理前端输入偏好，通过 Fcitx5 D-Bus 备份、合并、应用并读回验证，保留无关快捷键。`Ctrl+Space` 交给 Rime Lua 中英切换；`Ctrl+Alt+Space` 用于激活/退出 Fcitx5；Shift 不临时切换，不跨窗口共享输入状态。需要系统 Python 的 PyGObject/Gio（Ubuntu `python3-gi`）。切换前端本身时提交原始输入；Rime 内部中英切换则提交去分隔符拼音。该 JSON 只有纳入同步清单且启用配置处理时才应用。

三端共用 `default.custom.yaml`、方案补丁和 `lua/hx_preferences.lua`；应用初始英文名单分别位于 Windows 的 `weasel.custom.yaml`、Linux 的 `fcitx5.custom.yaml`；macOS 的 `squirrel.custom.yaml` 改为中文初始状态，共用 Lua 根据 Squirrel 前端身份锁定中文。应用标识由前端提供，Wayland/XWayland 或发行渠道可能不同；Windows/Linux 未匹配时沿用方案默认，手动切换仍可用；macOS 始终保持中文。


Windows 的雾凇/朙月方案通过自定义补丁引用已有 `icons/chinese.ico`、`icons/english.ico`；新设备需另行准备这两个资源文件，图标二进制不随个人配置云同步。Ctrl+Space 在 Windows/Linux 按一次完整按键周期切换，长按重复和松开不再触发第二次 Lua 切换；macOS 行为不变。PiliPlus/Flutter 的短按外部二次切换已增加 Windows 按键周期保护，用户确认短按和长按均正常；验证边界见 [图标与按键修正](PROJECT.md#windows-图标与-ctrlspace-释放修正2026-11-10)。


### 测试时立即部署

修改 `config/` 后，可以单次应用并立即重新部署：

```powershell
python rime.py --deploy-now --dry-run  # 只读预览
python rime.py --deploy-now            # 备份应用受管配置，然后立即部署
```

此测试入口不联网、不刷新第三方词典、不执行个人词典 `/sync`，不修改原生同步限频状态。它覆盖自动部署开关，跳过本次部署的空闲等待、失败退避及“资源未变化”判断；仍保留配置备份、文件锁、原生维护互斥、真实完成凭据和部署后指纹复核。命令可能打断正在进行的输入，应在测试时手动运行。自定义部署包装器收到 `RIME_DEPLOY_IDLE_SECONDS=0`，仍须提供完成凭据；如果包装器返回 deferred，命令返回非零。

支持 `--target`、`--state-dir`、`--sync-config`、`--automation-config` 等路径配置，以及 `--dry-run`。不能与 `--watch`、`--service`、云同步、原生词典同步等动作混用，也不会进入服务启动参数。只应用个人配置清单中启用的文件；Linux 的 Fcitx5 主题和前端偏好应用仍走正常工作流。测试结果保存在状态目录的 `deployment-test-result.json`，原生部署凭据沿用 `deployment/`。这是本地配置测试，不代表已完成云同步。
