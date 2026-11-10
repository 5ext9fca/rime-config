"""One observed workflow transaction; no persistent polling loop."""
import contextlib
import json
import subprocess
import sys
from client.project import SOURCE
from client.core.configuration import apply, observe_configuration
from client.storage.filesystem import atomic_write
from client.storage.config_paths import safe_path
from client.config.paths import existing_target
from client.config.identity import load_identity

def run_cycle(args,target,state,device_config_path,force_refresh,force_remote,resolution):
    existing_target(target)
    from client.core.scope import load_scope
    project_scope = load_scope(args.sync_config)
    config_scope = project_scope['configuration']
    dictionary_scope = project_scope['dictionaries']
    scope = [name for name in config_scope['files'] if not name.startswith('fcitx5/')]
    from client.config.automation import load as load_automation
    automation = load_automation(args.automation_config)
    if args.watch and not args.dry_run and automation['logs']['enabled']:
        from client.maintenance.logs import DailyLog
        if not isinstance(sys.stdout, DailyLog):
            sys.stdout = sys.stderr = DailyLog(state / 'logs',automation['logs'])
        else:sys.stdout.policy=automation['logs']
    from client.providers.third_party import load_config, refresh, RefreshError
    third_party_config = load_config(args.third_party_config, scope)
    from client.transport.http_transport import load_remote
    from client.application.cloud_sync import synchronize
    from client.transport.remote_errors import RemoteError
    remote_config = load_remote(args.remote_config)
    identity = load_identity(device_config_path)
    device_id = args.device_id or identity.get('installation_id')
    if identity and args.device_id and args.device_id != identity['installation_id']:
        raise ValueError('--device-id 与私有设备配置不一致，请为另一设备指定独立 --device-config')
    if identity:
        remote_config['token'] = identity['token']
    if args.dictionary_store and not device_id:
        raise ValueError('共享目录同步需要安装 ID，请先 --init 或指定 --device-id')
    remote_active = remote_config['enabled'] and not args.third_party_only
    native = None
    if (args.native_sync_all_command or args.weasel_deployer or args.native_sync_builtin) and not args.third_party_only:
        if not device_id or not (remote_active or args.dictionary_store):
            raise ValueError('全量原生同步需要设备身份及远端或共享目录同步')
        from client.maintenance.native_sync import FullNativeSync, load_schedule
        native = FullNativeSync(target, args.rime_sync_dir or target / 'sync', device_id,
                                args.sync_config, state / 'native-all',
                                command=args.native_sync_all_command, deployer=args.weasel_deployer,
                                policy=load_schedule(args.native_sync_config), builtin=args.native_sync_builtin)
        if args.plan_json:
            import io
            with contextlib.redirect_stdout(io.StringIO()):
                project_scope = native.prepare(True)
        else:
            project_scope = native.prepare(args.dry_run)
        dictionary_scope = project_scope['dictionaries']
    if remote_active and not device_id:
        raise ValueError('服务端同步需要安装 ID，请先运行 --init')
    if remote_active and args.dictionary_store:
        raise ValueError('服务端模式与 --dictionary-store 共享目录模式不能同时启用')
    if not remote_active and not args.third_party_only and not args.dictionary_store and (args.device_id or args.rime_sync_dir or args.native_sync_command):
        raise ValueError('个人词典选项需要启用服务端同步或 --dictionary-store')
    from client.core.plans import workflow, execute_workflow, dumps
    from client.config.paths import platform_key
    plan = workflow(platform_key(), remote=remote_active,
                    configuration=config_scope['enabled'] and bool(config_scope['files']),
                    dictionaries=dictionary_scope['enabled'] and bool(dictionary_scope['names']),
                    store=bool(args.dictionary_store), third_party=third_party_config['enabled'],
                    third_party_only=args.third_party_only,
                    native_backend='builtin' if args.native_sync_builtin else 'weasel' if args.weasel_deployer else
                    'command' if args.native_sync_all_command else
                    'legacy-command' if args.native_sync_command else 'snapshots-only',
                    automation=automation,theme_enabled='fcitx5/theme.json' in config_scope['files'],
                    frontend_preferences='fcitx5/input.json' in config_scope['files'])
    if args.plan_json:
        if plan['steps'][1]['action'] != 'skip':
            _, _, file_plan = observe_configuration(SOURCE, target, state, scope, remote_active or not scope)
            plan['steps'][1]['details'] = {'source': str(SOURCE), 'target': str(target),
                                         'local_preview': file_plan,
                                         'rebuild_after_remote': remote_active}
        if native and dictionary_scope['enabled']:
            owner = 0 if remote_active else 2
            plan['steps'][owner]['details']['native_preview'] = native.preview(dictionary_scope['names'])
        print(dumps(plan))
        return 0

    def run_remote():
        try:
            if not args.dry_run:
                from client.providers.token_refresh import refresh as refresh_token
                from client.transport.http_transport import request
                refresh_token(remote_config,device_config_path,state / 'token',request)
            outcome = synchronize(remote_config, project_scope, SOURCE,
                                  args.rime_sync_dir or target / 'sync', device_id,
                                  state / 'remote', command=args.native_sync_command,
                                  dry_run=args.dry_run, force=force_remote, resolve=resolution, native=native)
            status = 'blocked' if outcome == 'blocked' else 'skipped' if outcome in ('not-due', 'disabled', 'planned') else 'success'
            return {'status': status, 'reason': outcome}
        except RemoteError as exc:
            print(str(exc), file=sys.stderr)
            return {'status': 'failed', 'reason': 'remote-error'}

    def run_configuration():
        if scope:
            apply(SOURCE, target, state, args.dry_run, includes=scope, allow_empty=remote_active)
        return {'status': 'success', 'reason': 'configuration-checked'}

    def run_dictionaries():
        from client.application.dictionaries import exchange
        exchange(args.rime_sync_dir or target / 'sync', args.dictionary_store,
                 device_id, state / 'dictionaries', args.dry_run,
                 args.native_sync_command, names=dictionary_scope['names'], native=native)
        return {'status': 'deferred' if native and native.application.get('status') == 'deferred' else 'success',
                'reason': 'dictionary-exchange-checked'}

    def run_third_party():
        try:
            refresh(third_party_config, target, state / 'third-party', args.dry_run, force_refresh)
            return {'status': 'success', 'reason': 'third-party-checked'}
        except RefreshError as exc:
            print(str(exc), file=sys.stderr)
            return {'status': 'failed', 'reason': 'third-party-error'}

    def run_theme():
        from client.platforms.linux.theme import apply as apply_theme
        from client.platforms.platform_execution import get_executor
        try:
            if not (SOURCE / 'fcitx5/theme.json').exists():
                return {'status':'skipped','reason':'theme-absent-preserve-installed'}
            outcome=apply_theme(SOURCE,state / 'theme',args.dry_run,get_executor())
            return {'status':'success','reason':outcome}
        except (OSError,ValueError,subprocess.SubprocessError):
            return {'status':'failed','reason':'theme-application-failed'}

    def run_deployment():
        from client.maintenance.deployment import deploy
        from client.platforms.platform_execution import get_executor
        names=(scope if config_scope['enabled'] and not args.third_party_only else []) + (third_party_config['source']['files'] if third_party_config['enabled'] else [])
        try:
            outcome=deploy(target,names,state / 'deployment',automation['deployment'],get_executor(),args.dry_run)
            return {'status':'deferred' if outcome=='deferred' else 'success','reason':outcome}
        except (OSError,ValueError,subprocess.SubprocessError):
            print('自动重新部署失败，保留待部署状态并按周期重试。',file=sys.stderr)
            return {'status':'failed','reason':'deployment-failed'}

    def run_log_cleanup():
        from client.maintenance.logs import clean
        if not args.dry_run:clean(state / 'logs',automation['logs'])
        return {'status':'success','reason':'managed-logs-retained'}

    def run_backup_cleanup():
        from client.maintenance.backup_retention import clean
        report=clean(state,automation['backups'],args.dry_run)
        for name in report['planned']:
            print(('backup-prune-plan' if args.dry_run else 'backup-prune')+'\t'+name,flush=True)
        return {'status':'deferred' if report['status']=='busy' or report['skipped'] else 'success',
                'reason':report['status']}

    if not args.dry_run:
        atomic_write(safe_path(state, 'workflow-plan.json'), dumps(plan).encode())
    def publish(report):
        atomic_write(safe_path(state, 'workflow-result.json'), json.dumps(report, ensure_ascii=False, indent=2).encode())
    def run_preferences():
        from client.platforms.linux.frontend_preferences import apply as apply_preferences
        try:
            outcome=apply_preferences(SOURCE,state/'frontend-preferences',args.dry_run)
            return {'status':'success','reason':outcome}
        except Exception:
            return {'status':'failed','reason':'frontend-preferences-failed'}
    handlers = {'remote-sync': run_remote, 'configuration-apply': run_configuration,
                                    'dictionary-exchange': run_dictionaries, 'third-party-refresh': run_third_party,
                                    'theme-apply':run_theme,'frontend-deploy':run_deployment,'log-cleanup':run_log_cleanup,
                                    'backup-cleanup':run_backup_cleanup}
    if plan['version']==4:handlers['frontend-preferences']=run_preferences
    result=execute_workflow(plan,handlers,publish=None if args.dry_run else publish)
    if not remote_active and not args.third_party_only and dictionary_scope['enabled'] and dictionary_scope['names'] and not args.dictionary_store:
        print('个人词典范围已启用，但未配置服务端或 --dictionary-store；本轮不交换或应用个人词典。', flush=True)
    personal_ok = not any(s['status'] in ('failed', 'blocked') for s in result['steps'])
    return 0 if personal_ok else 1
