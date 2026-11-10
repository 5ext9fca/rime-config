"""Command-line parsing; execution belongs to runtime/workflow."""
import argparse
import os
import sys
from pathlib import Path
from client.project import SOURCE

def parse_args():
    if os.name == 'nt':
        for stream in (sys.stdout, sys.stderr):
            if hasattr(stream, 'reconfigure'):
                stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--automation-config', type=Path, default=SOURCE.parent / 'automation.json', help='主题、重新部署及日志保留策略')
    parser.add_argument('--paths-config', type=Path, default=SOURCE.parent / 'paths.json', help='初次发现目录的候选路径配置')
    parser.add_argument('--paths-state', type=Path, help='私有路径记忆文件，默认与 device 配置同目录的 paths.local.json')
    parser.add_argument('--discover-target', action='store_true', help='仅发现/确认并记住目标目录，不同步或初始化令牌')
    parser.add_argument('--rediscover-target', action='store_true', help='忽略旧记忆和身份文件路径，重新按候选路径发现')
    parser.add_argument('--init', action='store_true', help='初始化项目内的本机安装 ID、设备令牌和目标目录，然后退出')
    parser.add_argument('--device-config', type=Path, default=SOURCE.parent / 'device.local.json', help='本机私有项目配置文件')
    parser.add_argument('--token-stdin', action='store_true', help='初始化时从标准输入读取一行设备令牌')
    parser.add_argument('--remote-config', type=Path, default=SOURCE.parent / 'remote.json', help='服务端连接及同步周期配置')
    parser.add_argument('--sync-now', action='store_true', help='立即进行一轮服务端同步')
    parser.add_argument('--deploy-now', action='store_true', help='单次测试：备份应用本地配置并立即部署，跳过部署空闲/退避；不联网或同步词典')
    parser.add_argument('--resolve-conflicts', choices=['local', 'remote'], help='显式选择本轮配置冲突的本地或服务端版本')
    parser.add_argument('--sync-config', type=Path, default=SOURCE.parent / 'sync-manifest.json', help='配置与个人词典同步/应用范围文件')
    parser.add_argument('--third-party-config', type=Path, default=SOURCE.parent / 'third-party.json', help='第三方词典刷新配置文件')
    parser.add_argument('--refresh-third-party', action='store_true', help='立即检查第三方词典，仍遵守配置 enabled 开关')
    parser.add_argument('--third-party-only', action='store_true', help='只运行第三方词典刷新')
    parser.add_argument('--dictionary-store', type=Path, help='个人词典快照交换目录（可为私有同步盘）')
    parser.add_argument('--device-id', help='本机 installation.yaml 中的 installation_id')
    parser.add_argument('--rime-sync-dir', type=Path, help='Rime 原生同步根目录，默认目标目录下 sync')
    parser.add_argument('--native-sync-command', help='JSON 参数数组；需等待 Rime 原生同步完成再退出的命令')
    parser.add_argument('--native-sync-builtin', action='store_true', help='使用平台内置全量原生同步适配器')
    parser.add_argument('--native-sync-all-command', help='Unix 等平台原生全量同步包装器 JSON 数组，完成后写入 RIME_SYNC_RECEIPT')
    parser.add_argument('--weasel-deployer', type=Path, help='Windows 原生 WeaselDeployer.exe；独立限频调度 /sync 并验证完成')
    parser.add_argument('--native-sync-config', type=Path, default=SOURCE.parent / 'native-sync.json', help='原生维护独立周期与空闲阈值')
    parser.add_argument('--target', type=Path, help='Rime 用户配置目录')
    parser.add_argument('--state-dir', type=Path, help='备份及管理清单目录')
    parser.add_argument('--dry-run', '--plan', action='store_true', help='只显示变更，不写文件')
    parser.add_argument('--plan-json', action='store_true', help='输出版本化 JSON 计划；只读、不联网、不调用平台执行器')
    parser.add_argument('--watch', action='store_true', help='持续检查并应用配置')
    parser.add_argument('--interval', type=float, default=5, help='检查间隔秒数（默认 5）')
    parser.add_argument('--service', choices=['install', 'uninstall', 'status'], help='注册并启动、卸载或查询当前用户的自动同步服务')
    args = parser.parse_args()
    if args.deploy_now and any((args.service, args.watch, args.init, args.discover_target,
            args.rediscover_target, args.plan_json, args.sync_now, args.resolve_conflicts,
            args.refresh_third_party, args.third_party_only, args.token_stdin,
            args.dictionary_store, args.native_sync_command, args.native_sync_all_command,
            args.native_sync_builtin, args.weasel_deployer, args.rime_sync_dir)):
        parser.error('--deploy-now 是独立测试操作，只能与路径/配置选项及 --dry-run 同用')
    if args.plan_json:
        if args.service or args.watch or args.init or args.discover_target or args.resolve_conflicts or args.token_stdin:
            parser.error('--plan-json 是独立的只读计划操作')
        args.dry_run = True
    if sum(bool(v) for v in (args.native_sync_command, args.native_sync_all_command, args.weasel_deployer, args.native_sync_builtin)) > 1:
        parser.error('逐词典命令、全量命令和小狼毫入口只能选择一个')
    if args.service and (args.init or args.discover_target or args.watch or args.sync_now or args.resolve_conflicts or args.refresh_third_party or args.token_stdin):
        parser.error('--service 不能与初始化、路径发现或单次同步动作同用')
    if args.service == 'status' and args.dry_run:
        parser.error('--service status 不支持 --dry-run')
    if args.discover_target and (args.init or args.watch or args.sync_now or args.resolve_conflicts or args.refresh_third_party or args.third_party_only):
        parser.error('--discover-target 是独立路径操作')
    if args.token_stdin and not args.init:
        parser.error('--token-stdin 只能与 --init 同用')
    if args.init and (args.watch or args.dry_run or args.sync_now or args.resolve_conflicts or args.refresh_third_party or args.third_party_only):
        parser.error('--init 是独立初始化操作，不能与同步/预览选项同用')
    if args.interval <= 0 or not __import__('math').isfinite(args.interval):
        parser.error('--interval 必须为有限正数')
    if args.watch and args.dry_run:
        parser.error('--watch 不能与 --dry-run 同用')
    if args.third_party_only and args.dictionary_store:
        parser.error('--third-party-only 不能与个人词典选项同用')
    return args

def main():
    from client.application.runtime import run
    from client.platforms.platform_execution import close_executors
    try:return run(parse_args())
    finally:close_executors()
