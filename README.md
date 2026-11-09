# Rime 配置与同步

在 WSL、macOS 和 Ubuntu 上管理 Rime 个人配置、自定义短语和自动学习词典，并通过自建服务在设备间同步。支持按项目配置定期刷新雾凇拼音词典。

**修改配置请编辑 `config/`。** 同步结果会先更新此目录，再应用到实际输入法目录；直接修改实际目录中的受管理配置，会被下次应用覆盖。

## 开始使用

需要 Python 3.9 或更新版本，客户端无需额外 Python 包。请先安装对应平台的 Rime 输入法和完整雾凇拼音方案。本工具刷新词典，不负责安装或升级完整方案、Lua、OpenCC 和语言模型；配置依赖的万象模型需另行准备。

以下命令均在本项目根目录执行：

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

1. 在 Rime 菜单执行“同步用户资料”，等待本机学习数据导出。
2. 运行客户端同步，将选定词典的快照上传，并接收其他设备的快照。
3. 再执行“同步用户资料”，由 Rime 合并到本机词典；后续客户端同步会上传新的快照。

**快照传输成功不代表已导入输入法。** 日常新学习的数据也需要先由 Rime 导出。默认快照目录是实际配置目录下的 `sync/`；如果修改过 Rime 的 `sync_dir`，运行时应传入 `--rime-sync-dir /实际同步目录`，WSL 使用 Linux 路径。

也可使用私有共享目录替代 VPS：

```bash
python3 client/sync.py --watch --device-id 本机安装ID \
  --dictionary-store /私有共享目录
```

此模式要求关闭 `remote.json` 的远端同步，各设备需访问同一共享目录。无人值守原生导入需要平台专用包装程序，约定见 [个人词典技术说明](PROJECT.md#自动学习个人词典)。目前尚未完成三端原生导入及真实 VPS 联调。

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

普通运行和 `--watch` 也会按周期检查。刷新后需重新部署输入法。入口词典 `rime_ice.dict.yaml`、`melt_eng.dict.yaml` 及完整方案依赖需自行维护；当前环境尚未完成真实上游下载与客户端部署验证。

## 当前输入偏好

项目已配置默认简体、不启用模糊音，沿用雾凇纠错和中英混输，开启 Emoji 与补全。主要操作：

- `Ctrl+Space` 切换中英文，Shift 不切换，CapsLock 保留大写功能。切换时提交去掉空格和分隔符的拼音，例如 `xi'an hao` → `xianhao`。
- `-`、`=` 翻页；横排 9 候选、14 号字，黑/白背景随系统主题切换，绿色矩形高亮。
- 不要求中英文状态跨窗口共享；终端和代码编辑器默认英文，仍可手动切换。程序名单及外观在 [`weasel.custom.yaml`](config/weasel.custom.yaml) 中调整，仅适用于 Windows 小狼毫。
- 中文模式下，标点根据当前候选或最近提交字符选择中英文形式。无法读取应用任意光标前文本，粘贴或移动光标后可能回退中文标点。

通用快捷键见 [`default.custom.yaml`](config/default.custom.yaml)，雾凇选项见 [`rime_ice.custom.yaml`](config/rime_ice.custom.yaml)。这些偏好应用后仍需重新部署，主题及真实输入体验需实机确认；macOS/Ubuntu 外观需按前端另行配置。

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
| WSL | systemd 用户服务 | 已启用 systemd，且用户服务管理器可用 |
| Ubuntu | systemd 用户服务 | 当前用户会话可访问 systemd 用户管理器 |
| macOS | launchd 用户 LaunchAgent | 在已登录的图形用户会话中安装 |

WSL 服务仅在发行版和用户管理器运行期间工作，不会自动唤醒或启动 WSL。安装器不会修改 `/etc/wsl.conf`、启用 linger 或创建 Windows 计划任务。

安装时复用已记忆的实际配置目录，也可用参数明确指定：

```bash
python3 client/sync.py --service install --target /实际/Rime/目录 --interval 10
```

项目路径、Python 路径、目标目录和自定义参数会保存到服务定义中。支持保留 `--device-config`、`--paths-config`、`--paths-state`、`--sync-config`、`--remote-config`、`--third-party-config`、`--state-dir` 及个人词典参数；令牌仍从私有设备配置读取，不复制到服务文件。原生同步包装程序须使用绝对路径。

重复安装会更新并重启服务。迁移项目、Python 或目标目录，或更换启动参数后，应重新安装；只修改同步范围、远端配置或第三方刷新配置，无需重新安装。每个系统用户使用一个服务实例。若已有同名手写服务，安装器会提示先手动迁移，不直接覆盖。

查看日志：

```bash
# WSL / Ubuntu
journalctl --user -u rime-config.service -f
# macOS
tail -f ~/Library/Logs/rime-config/stdout.log ~/Library/Logs/rime-config/stderr.log
```

卸载仅移除后台服务，保留输入法配置、私有身份、词典、备份与日志。目标目录失效时也可查询或卸载服务。
