"""Versioned, platform-neutral decisions. No filesystem, network or OS calls."""
import hashlib
import json
import math
import re

PLATFORMS = {'windows', 'linux', 'macos'}
KINDS = {'configuration-plan', 'native-plan', 'workflow-plan'}
FIELDS = {'kind', 'version', 'platform', 'steps'}
STEP_FIELDS = {'id', 'action', 'reason', 'requires', 'details'}
ACTIONS = {
    'configuration-plan': {'create', 'replace', 'delete', 'skip'},
    'native-plan': {'execute', 'defer', 'skip', 'observe'},
    'workflow-plan': {'evaluate', 'skip'},
}
STAGES = ('remote-sync', 'configuration-apply', 'dictionary-exchange', 'third-party-refresh')
STAGES_V2 = STAGES + ('theme-apply','frontend-deploy','log-cleanup')
STAGES_V3 = STAGES_V2 + ('backup-cleanup',)
STAGES_V4 = STAGES_V3[:5]+('frontend-preferences',)+STAGES_V3[5:]


def step(identifier, action, reason, details=None, requires=()):
    return dict(id=identifier, action=action, reason=reason,
                requires=list(requires), details=details or {})


def envelope(kind, platform, steps):
    value = dict(kind=kind, version=1, platform=platform, steps=steps)
    validate(value, kind)
    return value


def validate(value, kind=None):
    if (not isinstance(value, dict) or set(value) != FIELDS or not isinstance(value['kind'], str) or value['kind'] not in KINDS
            or (kind and value['kind'] != kind) or type(value['version']) is not int
            or value['version'] not in (1,2,3,4) or (value['version']!=1 and value['kind']!='workflow-plan') or not isinstance(value['platform'], str) or value['platform'] not in PLATFORMS
            or not isinstance(value['steps'], list)):
        raise ValueError('不支持的计划类型、版本、平台或字段')
    seen = set()
    for item in value['steps']:
        if (not isinstance(item, dict) or set(item) != STEP_FIELDS
                or not isinstance(item['id'], str) or not item['id'] or item['id'] in seen
                or not isinstance(item['action'], str) or item['action'] not in ACTIONS[value['kind']]
                or not isinstance(item['reason'], str) or not item['reason']
                or not isinstance(item['requires'], list)
                or not all(isinstance(v, str) and v in seen for v in item['requires'])
                or len(set(item['requires'])) != len(item['requires'])
                or not isinstance(item['details'], dict)):
            raise ValueError('计划动作、依赖或字段无效')
        seen.add(item['id'])
        details = item['details']
        if value['kind'] == 'configuration-plan':
            if set(details) != {'before', 'after'} or not all(v is None or isinstance(v, str) and re.fullmatch('[0-9a-f]{64}', v) for v in details.values()):
                raise ValueError('文件计划指纹无效')
            before, after = details['before'], details['after']
            expected = 'skip' if before == after else 'delete' if after is None else 'create' if before is None else 'replace'
            if item['action'] != expected:
                raise ValueError('文件计划动作与指纹不一致')
        elif value['kind'] == 'native-plan':
            stamp = details.get('last_success_at')
            if set(details) != {'last_success_at'} or type(stamp) not in (int, float) or not math.isfinite(stamp) or stamp < 0:
                raise ValueError('原生计划成功时间无效')
    if value['kind'] == 'workflow-plan' and tuple(i['id'] for i in value['steps']) != ({1:STAGES,2:STAGES_V2,3:STAGES_V3,4:STAGES_V4}[value['version']]):
        raise ValueError('工作流阶段必须符合固定顺序')
    if value['kind'] == 'native-plan' and (len(value['steps']) != 1 or value['steps'][0]['id'] != 'native-sync'):
        raise ValueError('原生计划必须只有一个全量同步动作')
    return value


def dumps(value):
    validate(value)
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)


def digest(data):
    return hashlib.sha256(data).hexdigest() if data is not None else None


def configuration(platform, files, destinations, managed):
    """Values are bytes observed by the caller; plans contain hashes only."""
    steps = []
    for name in sorted(set(files) | set(managed)):
        before, after = destinations.get(name), files.get(name)
        action = ('skip' if before == after else 'delete' if after is None
                  else 'create' if before is None else 'replace')
        steps.append(step(name, action, 'unchanged' if action == 'skip' else
                          'source-removed' if action == 'delete' else 'source-changed',
                          {'before': digest(before), 'after': digest(after)}))
    return envelope('configuration-plan', platform, steps)


def maintenance(platform, policy, schedule, fingerprint, now, idle=None):
    cooldown = policy['retry_seconds'] if schedule.get('unsafe') else policy['interval_seconds']
    if now < schedule.get('last_attempt', 0) + cooldown:
        action, reason = 'defer', 'retry-wait' if schedule.get('unsafe') else 'interval'
    elif (not schedule.get('unsafe') and fingerprint == schedule.get('fingerprint')
          and now < schedule.get('last_success', 0) + policy['max_interval_seconds']):
        action, reason = 'skip', 'no-change'
    elif idle is None:
        action, reason = 'observe', 'idle-required'
    elif idle not in ('idle','delegated'):
        action, reason = 'defer', 'input-active' if idle=='active' else 'idle-unknown'
    else:
        action, reason = 'execute', 'due'
    return envelope('native-plan', platform, [step('native-sync', action, reason,
                    {'last_success_at': schedule.get('last_success', 0)})])


def workflow(platform, *, remote, configuration, dictionaries, store, third_party,
             third_party_only=False, native_backend='snapshots-only', automation=None, theme_enabled=False, frontend_preferences=False):
    remote = remote and not third_party_only
    config = configuration and not third_party_only
    exchange = dictionaries and store and not remote and not third_party_only
    base = envelope('workflow-plan', platform, [
        step('remote-sync', 'evaluate' if remote else 'skip',
             'runtime-cas-and-schedule' if remote else 'disabled',
             {'native_backend': native_backend if dictionaries else 'disabled'}),
        step('configuration-apply', 'evaluate' if config else 'skip',
             'recheck-after-remote-merge' if remote else 'local-authority',
             requires=['remote-sync'] if remote else []),
        step('dictionary-exchange', 'evaluate' if exchange else 'skip',
             'shared-store' if exchange else 'handled-by-remote' if remote else 'disabled',
             {'native_backend': native_backend}),
        step('third-party-refresh', 'evaluate' if third_party else 'skip',
             'independent-schedule' if third_party else 'disabled'),
    ])

    if automation is None:return base
    base['version']=2
    theme=automation['linux_theme'] and theme_enabled and platform=='linux' and config
    base['steps'] += [
        step('theme-apply','evaluate' if theme else 'skip','linux-theme-bundle' if theme else 'disabled',requires=['configuration-apply']),
        step('frontend-deploy','evaluate' if automation['deployment']['enabled'] and (config or third_party) else 'skip',
             'changed-resources-idle-and-receipt', requires=['configuration-apply','third-party-refresh','theme-apply']),
        step('log-cleanup','evaluate' if automation['logs']['enabled'] else 'skip','managed-logs-only')]
    if 'backups' in automation:
        base['version']=3
        base['steps'].append(step('backup-cleanup','evaluate' if automation['backups']['enabled'] else 'skip',
                                  'completed-managed-backups-only',dict(automation['backups'])))
    if frontend_preferences and 'backups' in automation:
        base['version']=4
        base['steps'].insert(5,step('frontend-preferences','evaluate' if platform=='linux' and config else 'skip',
            'frontend-input-bundle',requires=['configuration-apply']))
        base['steps'][6]['requires'].append('frontend-preferences')
    return validate(base)


def execute_workflow(plan, handlers, publish=None):
    """Dispatch only known stages; callers own observations and side effects.

    Remote/refresh handlers may return failed outcomes for existing retry
    semantics. Unexpected exceptions still abort, preserving current behavior.
    """
    validate(plan, 'workflow-plan')
    if set(handlers) != set({1:STAGES,2:STAGES_V2,3:STAGES_V3,4:STAGES_V4}[plan['version']]) or not all(callable(v) for v in handlers.values()):
        raise ValueError('工作流执行器不完整')
    report = {'kind': 'workflow-result', 'version': plan['version'], 'platform': plan['platform'],
              'steps': [{'id': i['id'], 'status': 'pending', 'reason': 'not-started'} for i in plan['steps']]}
    if publish:
        publish(report)
    results, outcomes = [], {}
    for item in plan['steps']:
        if item['action'] == 'skip':
            outcome = {'status': 'skipped', 'reason': item['reason']}
        elif any(outcomes[d]['status'] in ('failed', 'blocked') for d in item['requires']):
            outcome = {'status': 'blocked', 'reason': 'dependency-failed'}
        else:
            try:
                outcome = handlers[item['id']]()
            except BaseException:
                report['steps'] = results + [{'id': item['id'], 'status': 'failed', 'reason': 'executor-error'}]
                report['steps'] += [{'id': s['id'], 'status': 'blocked', 'reason': 'run-aborted'}
                                    for s in plan['steps'][len(results) + 1:]]
                if publish:
                    publish(report)
                raise
            if (not isinstance(outcome, dict) or set(outcome) != {'status', 'reason'}
                    or outcome['status'] not in ('success', 'skipped', 'deferred', 'blocked', 'failed')
                    or not isinstance(outcome['reason'], str)):
                raise ValueError('执行器返回了无效结果')
        outcomes[item['id']] = outcome
        results.append({'id': item['id'], **outcome})
    report['steps'] = results
    if publish:
        publish(report)
    return report
