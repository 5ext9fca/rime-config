"""Full native sync policy shared by Windows and Unix clients.

The manifest is an additive superset of native user databases and snapshots.
Third-party/config backups created by Rime are never part of dictionary scope.
"""
import contextlib
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import time
import uuid

from client.storage.snapshots import checked, snapshots
from client.core.dictionary_format import component
from client.storage.file_lock import lock_exclusive
from client.core.scope import load_scope
from client.storage.filesystem import atomic_write, is_link
from client.core.plans import maintenance
from client.platforms.platform_execution import get_executor


DEFAULT_SCHEDULE = dict(interval_seconds=900, retry_seconds=900,
                        idle_seconds=30, max_interval_seconds=3600)


def load_schedule(path):
    value = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(value, dict) or set(value) != set(DEFAULT_SCHEDULE):
        raise ValueError('原生调度配置字段无效')
    for key, number in value.items():
        if type(number) not in (int, float) or not math.isfinite(number) or number <= 0:
            raise ValueError('原生调度周期必须为正数: ' + key)
    if value['max_interval_seconds'] < value['interval_seconds']:
        raise ValueError('原生最长导出间隔不能小于最小维护间隔')
    return value


def database_names(target):
    result = set()
    for path in checked(Path(target), directory=True).iterdir():
        if '.userdb' not in path.name:
            continue
        name, suffix = path.name.split('.userdb', 1)
        if suffix not in ('', '.kct', '.txt') or name.startswith('.'):
            raise ValueError('发现不支持或未清理的原生词典，请先检查: ' + path.name)
        component(name)
        if is_link(path):
            raise ValueError('原生数据库不能是重解析路径')
        if path.is_dir():
            for child in path.rglob('*'):
                if is_link(child):
                    raise ValueError('原生数据库内部不能含重解析路径')
        else:
            checked(path)
        result.add(name)
    return result


def native_names(target, sync_dir):
    names = database_names(target)
    root = checked(Path(sync_dir), directory=True)
    if root.exists():
        for folder in root.iterdir():
            if is_link(folder):
                raise ValueError('原生同步目录不能含重解析路径')
            if folder.is_dir():
                component(folder.name)
                for key in snapshots(root, [folder.name]):
                    names.add(Path(key).name.removesuffix('.userdb.txt'))
    return names


class FullNativeSync:
    def __init__(self, target, sync_dir, device, manifest, state, command=None, deployer=None, policy=None, builtin=False):
        self.target, self.sync_dir, self.manifest, self.state = [
            Path(os.path.abspath(p)) for p in (target, sync_dir, manifest, state)]
        self.device = component(device)
        self.command, self.deployer = command, deployer
        self.builtin = builtin
        self.executor = get_executor()
        if builtin and self.executor.platform not in ('linux','macos'):
            raise ValueError('内置全量同步目前支持 Fcitx5 Linux 与 macOS 鼠须管')
        self.argv = None
        self.policy = dict(DEFAULT_SCHEDULE if policy is None else policy)
        self.publish_allowed = True
        self.application = {'mode': 'native-all', 'status': 'not-run'}
        if sum(map(bool,(command,deployer,builtin))) != 1:
            raise ValueError('全量原生同步须选择一个平台入口')
        if command:
            argv = json.loads(command)
            if (not isinstance(argv, list) or not argv or
                    not all(isinstance(x, str) and x and '{dictionary}' not in x for x in argv) or
                    not Path(argv[0]).is_absolute()):
                raise ValueError('全量原生同步命令须为绝对程序路径的 JSON 数组，不含 {dictionary}')
            self.argv = argv
        for path in (self.state, self.manifest):
            if path == self.target or self.target in path.parents or path == self.sync_dir or self.sync_dir in path.parents:
                raise ValueError('清单与状态不能放入原生目标或同步目录')

    def prepare(self, dry_run=False):
        """Only add discovered names; never enable a disabled dictionary section."""
        with contextlib.ExitStack() as stack:
            if not dry_run:
                checked(self.state, directory=True).mkdir(parents=True, exist_ok=True)
                lock = stack.enter_context(checked(self.state / 'scope.lock').open('a'))
                lock_exclusive(lock)
            original = self.manifest.read_bytes()
            scope = load_scope(self.manifest)
            if not scope['dictionaries']['enabled']:
                return scope
            discovered = native_names(self.target, self.sync_dir)
            current = scope['dictionaries']['names']
            added = sorted(discovered - set(current))
            combined = current + added
            if len({n.casefold() for n in combined}) != len(combined):
                raise ValueError('原生词典与清单存在大小写冲突')
            if added:
                scope['dictionaries']['names'] = combined
                if not dry_run:
                    if self.manifest.read_bytes() != original:
                        raise ValueError('补齐原生范围期间清单已变化，请重试')
                    scope_backup=self.state / 'scope-backups' / (uuid.uuid4().hex + '.json')
                    atomic_write(scope_backup, original)
                    atomic_write(self.manifest, (json.dumps(scope, ensure_ascii=False, indent=2) + '\n').encode())
                    from client.maintenance.backup_retention import completed as complete_backup
                    complete_backup(scope_backup)
                print('全量原生词典范围' + ('计划补入: ' if dry_run else '已补入: ') + ', '.join(added), flush=True)
            return scope

    def check(self, names):
        actual = native_names(self.target, self.sync_dir)
        if not actual <= set(names):
            self.prepare()
            raise ValueError('原生词典范围在本轮变化；已补入清单，请对齐服务端后重试')
        scope = load_scope(self.manifest)['dictionaries']
        if not scope['enabled'] or set(scope['names']) != set(names):
            raise ValueError('词典清单在本轮变化，停止原生同步')
        return database_names(self.target)

    def fingerprint(self, names):
        # Only stat live database files. Never read/copy an active database.
        records = []
        for path in sorted(self.target.iterdir()):
            if '.userdb' not in path.name:
                continue
            for item in sorted(path.rglob('*')) if path.is_dir() else [path]:
                if is_link(item):
                    raise ValueError('原生数据库内部不能含重解析路径')
                stat = item.stat()
                records.append((str(item.relative_to(self.target)), stat.st_size, stat.st_mtime_ns))
        devices = [p.name for p in self.sync_dir.iterdir() if p.is_dir()] if self.sync_dir.exists() else []
        files = snapshots(self.sync_dir, devices, names)
        records.extend((key, hashlib.sha256(data).hexdigest()) for key, data in sorted(files.items()))
        return hashlib.sha256(json.dumps([sorted(names), records]).encode()).hexdigest()

    def observe_idle(self):
        return self.executor.observe_idle(self.policy['idle_seconds'], delegated=self.argv is not None)

    def read_schedule(self):
        path = checked(self.state / 'schedule.json')
        schedule = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        binding = [str(self.target), str(self.sync_dir), self.device, self.command, str(self.deployer)]
        if self.builtin:binding.append('builtin:'+self.executor.platform)
        if schedule and schedule.get('binding') != binding:
            raise ValueError('原生调度状态属于其他入口或目录，请使用独立状态目录')
        if not schedule:
            old = checked(self.state / 'latest.json')
            last = json.loads(old.read_text(encoding='utf-8')) if old.exists() else {}
            stamp = last.get('completed_at', 0)
            schedule = {'binding': binding, 'last_attempt': stamp,
                        'last_success': stamp if last.get('status') == 'success' else 0,
                        'unsafe': last.get('status') in ('failed', 'running')}
        return path, schedule

    def preview(self, names):
        _, schedule = self.read_schedule()
        return maintenance(self.executor.platform, self.policy, schedule,
                           self.fingerprint(names), time.time())

    def run(self, names, now=None):
        expected = self.check(names)
        self.state.mkdir(parents=True, exist_ok=True)
        lock_path = checked(self.state / 'native.lock')
        with lock_path.open('a') as lock:
            lock_exclusive(lock)
            real_clock = now is None
            now = time.time() if real_clock else now
            path, schedule = self.read_schedule()
            fingerprint = self.fingerprint(names)
            self.publish_allowed = not schedule.get('unsafe', False)
            last_success = schedule.get('last_success', 0)
            plan = maintenance(self.executor.platform, self.policy, schedule, fingerprint, now)
            if plan['steps'][0]['action'] == 'observe':
                plan = maintenance(self.executor.platform, self.policy, schedule, fingerprint, now, self.observe_idle().state)
            decision = plan['steps'][0]
            atomic_write(self.state / 'plan.json', json.dumps(plan).encode())
            if decision['action'] != 'execute':
                reason = decision['reason']
                status = 'unchanged' if decision['action'] == 'skip' else 'deferred'
                self.application = {'mode': 'native-all', 'status': status, 'reason': reason,
                                    'names': list(names), 'last_success_at': last_success}
                atomic_write(path, json.dumps(schedule).encode())
                atomic_write(self.state / 'application.json', json.dumps(self.application).encode())
                print('原生维护跳过: ' + reason, flush=True)
                return self.application
            previous = dict(schedule)
            schedule.update(last_attempt=now, unsafe=True)
            atomic_write(path, json.dumps(schedule).encode())
            self.publish_allowed = False
            try:
                result = self.execute(names, expected)
                if result['status'] == 'deferred':
                    # A Unix wrapper may only report deferred before invoking
                    # native sync; preserve earlier failure quarantine.
                    schedule = previous
                    self.publish_allowed = not schedule.get('unsafe', False)
                    self.application = {'mode': 'native-all', 'status': 'deferred', 'reason': 'input-active',
                                        'names': list(names), 'last_success_at': last_success}
                else:
                    completed = time.time() if real_clock else now
                    schedule.update(last_attempt=completed, last_success=completed,
                                    fingerprint=self.fingerprint(names), unsafe=False)
                    self.publish_allowed = True
                    self.application = {'mode': 'native-all', 'status': 'success', 'names': list(names),
                                        'last_success_at': completed}
                atomic_write(path, json.dumps(schedule).encode())
                atomic_write(self.state / 'application.json', json.dumps(self.application).encode())
                return self.application
            except BaseException:
                self.application = {'mode': 'native-all', 'status': 'failed', 'names': list(names),
                                    'last_success_at': last_success}
                atomic_write(self.state / 'application.json', json.dumps(self.application).encode())
                raise

    def execute(self, names, expected):
        session = self.state / 'runs' / uuid.uuid4().hex
        session.mkdir(parents=True)
        # Snapshot backups are safe while Rime is live; never copy live DBs.
        before = snapshots(self.sync_dir, [self.device], names)
        for key, data in before.items():
            atomic_write(session / 'before' / key, data)
        if self.builtin or self.deployer:
            # Include scoped remote-only names in bootstrap and native completion
            # evidence; command wrappers retain their existing contract.
            expected = expected | native_names(self.target,self.sync_dir)
        result = {'status': 'running', 'mode': 'native-all', 'names': sorted(expected)}
        atomic_write(session / 'result.json', json.dumps(result).encode())
        try:
            evidence = self.executor.native(argv=self.argv, deployer=self.deployer, target=self.target,
                                            sync_dir=self.sync_dir, device=self.device, names=expected,
                                            session=session, idle_seconds=self.policy['idle_seconds'])
            if evidence.get('status') == 'deferred':
                result.update(status='deferred', completed_at=time.time())
                return result
            self.check(names)
            exported = snapshots(self.sync_dir, [self.device], names)
            if not expected <= {Path(k).name.removesuffix('.userdb.txt') for k in exported}:
                raise ValueError('原生同步缺少本机导出快照')
            # /sync only merges dictionaries which have a native database.
            pending = native_names(self.target, self.sync_dir) - expected
            if pending:
                raise ValueError('以下快照尚无本机用户数据库，不能宣称已导入: ' + ', '.join(sorted(pending)))
            result.update(status='success', completed_at=time.time(), evidence=evidence)
            print('原生全量同步完成: ' + ', '.join(sorted(expected)), flush=True)
            return result
        except BaseException as exc:
            reason = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
            result.update(status='failed', completed_at=time.time(), error=reason)
            print('原生全量同步未完成: ' + reason, flush=True)
            raise
        finally:
            atomic_write(session / 'result.json', json.dumps(result, ensure_ascii=False, indent=2).encode())
            atomic_write(self.state / 'latest.json', json.dumps(result, ensure_ascii=False, indent=2).encode())
