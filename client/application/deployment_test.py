"""Explicit local deployment test; never enters cloud or dictionary workflows."""
import json
from client.config.automation import load as load_automation
from client.core.scope import load_scope
from client.core.configuration import apply
from client.maintenance.deployment import deploy
from client.platforms.platform_execution import get_executor
from client.providers.third_party import load_config
from client.storage.filesystem import atomic_write
from client.storage.config_paths import safe_path


def run(args, target, state, source):
    scope = load_scope(args.sync_config)['configuration']
    names = [n for n in scope['files'] if not n.startswith('fcitx5/')]
    third = load_config(args.third_party_config, names)
    resources = (names if scope['enabled'] else []) + (third['source']['files'] if third['enabled'] else [])
    if not resources:
        raise ValueError('没有启用的受管部署资源')
    policy = dict(load_automation(args.automation_config)['deployment'], enabled=True)
    report = {'version': 1, 'operation': 'deploy-now', 'status': 'pending', 'configuration': 'pending'}
    path = safe_path(state, 'deployment-test-result.json')
    if not args.dry_run:
        atomic_write(path, json.dumps(report).encode())
    try:
        if scope['enabled']:
            apply(source, target, state, args.dry_run, includes=names, allow_empty=True)
        report['configuration'] = 'success' if scope['enabled'] else 'disabled'
        result = deploy(target, resources, state / 'deployment', policy,
                        None if args.dry_run else get_executor(), dry_run=args.dry_run, force=True)
        report['status'] = result
        print('立即部署: ' + result, flush=True)
        return 0 if result in ('success', 'planned') else 1
    except BaseException as exc:
        report.update(status='failed', error_type=type(exc).__name__)
        raise
    finally:
        if not args.dry_run:
            atomic_write(path, json.dumps(report).encode())
