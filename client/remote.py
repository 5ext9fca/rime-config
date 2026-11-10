"""HTTPS state exchange with conservative three-way configuration merging."""
import base64
import binascii
from file_lock import lock_exclusive
import hashlib
import http.client
import json
import math
import os
import subprocess
from pathlib import Path
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from dictionaries import checked, component, exchange, snapshots, validate_snapshot
from sync import atomic_write, safe_path


class RemoteError(RuntimeError):
    pass


class RevisionChanged(RemoteError):
    pass


def load_remote(path):
    config = json.loads(Path(path).read_text(encoding='utf-8'))
    required = {'enabled', 'url', 'interval_seconds', 'retry_seconds', 'timeout_seconds'}
    if not isinstance(config, dict) or set(config) not in (required, required | {'token_env'}):
        raise ValueError('Invalid remote.json fields')
    if type(config['enabled']) is not bool:
        raise ValueError('remote.enabled must be boolean')
    parsed = urllib.parse.urlsplit(config['url'])
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path != '/rime/v1/state':
        raise ValueError('remote.url must be https://HOST/rime/v1/state without credentials or query')
    if 'token_env' in config and (not isinstance(config['token_env'], str) or not config['token_env'].isidentifier()):
        raise ValueError('Invalid token_env')
    for key in ('interval_seconds', 'retry_seconds', 'timeout_seconds'):
        value = config[key]
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError(f'Invalid remote.{key}')
    return config


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request(config, method, payload=None):
    token = config.get('token') or os.environ.get(config.get('token_env', ''), '')
    if len(token) < 32 or not token.isascii() or any(ord(c) < 33 or ord(c) > 126 for c in token):
        raise RemoteError('同步令牌未配置或无效，请先运行 --init')
    body = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(config['url'], data=body, method=method,
                                 headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json', 'Accept': 'application/json'})
    try:
        with urllib.request.build_opener(NoRedirect()).open(req, timeout=config['timeout_seconds']) as response:
            raw = response.read(80 * 1024 * 1024 + 1)
            if response.status != 200 or len(raw) > 80 * 1024 * 1024:
                raise RemoteError('Invalid server response')
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        if exc.code == 409:
            raise RevisionChanged('服务端版本变化，下一轮重新拉取合并') from exc
        raise RemoteError(f'服务端返回 HTTP {exc.code}') from exc
    except (OSError, ValueError, http.client.HTTPException) as exc:
        raise RemoteError('HTTPS 同步失败，请检查网络、证书与服务状态') from exc


def encode(data):
    return base64.b64encode(data).decode()


def decode(value):
    if not isinstance(value, str):
        raise RemoteError('Invalid remote file encoding')
    try:
        data = base64.b64decode(value, validate=True)
        data.decode('utf-8-sig')
        return data
    except (ValueError, binascii.Error) as exc:
        raise RemoteError('Invalid remote text') from exc


def merge_file(base, local, remote, tracked):
    """Return a whole-file merge; never silently resolve two distinct edits."""
    if local == remote:
        return local
    if not tracked:
        if local is None:
            return remote
        if remote is None:
            return local
        raise RemoteError('首次同步时双方文件不同')
    if local == base:
        return remote
    if remote == base:
        return local
    raise RemoteError('双方均修改了同一文件')


def synchronize(config, scope, source, sync_dir, device, state, command=None,
                dry_run=False, transport=request, now=None, force=False, resolve=None, native=None):
    if not config['enabled']:
        return 'disabled'
    component(device)
    source, sync_dir, state = [Path(os.path.abspath(Path(p).expanduser())) for p in (source, sync_dir, state)]
    for a, b in ((source, state), (source, sync_dir), (state, sync_dir)):
        if a == b or a in b.parents or b in a.parents:
            raise ValueError('远端同步源、状态与 Rime 同步目录不能重叠')
    safe_path(source)
    checked(sync_dir, directory=True)
    safe_path(state)
    files = scope['configuration']['files'] if scope['configuration']['enabled'] else []
    names = scope['dictionaries']['names'] if scope['dictionaries']['enabled'] else []
    if not files and not names:
        return 'disabled'
    if dry_run:
        print(f'远端同步计划: {len(files)} 个配置文件，{len(names)} 个词典；不联网或执行原生命令。', flush=True)
        return 'planned'
    now = time.time() if now is None else now
    key = hashlib.sha256(json.dumps([config, scope, device, str(source), str(sync_dir)], sort_keys=True).encode()).hexdigest()
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    with safe_path(state, 'lock').open('a') as lock:
        lock_exclusive(lock)
        schedule_path = safe_path(state, 'schedule.json')
        schedule = json.loads(schedule_path.read_text(encoding='utf-8')) if schedule_path.exists() else {}
        if not force and not resolve and schedule.get('key') == key and now < schedule.get('next_attempt', 0):
            return 'blocked' if schedule.get('error') else 'not-due'
        baseline_path = safe_path(state, 'baseline.json')
        baseline = json.loads(baseline_path.read_text(encoding='utf-8')) if baseline_path.exists() else {}
        pending_path = safe_path(state, 'pending.json')
        pending = json.loads(pending_path.read_text(encoding='utf-8')) if pending_path.exists() else {}
        binding = [config['url'], device, str(source), str(sync_dir)]
        if pending and pending.get('binding') != binding:
            raise RemoteError('未完成提交属于其他服务或设备，请使用独立状态目录')
        if baseline and baseline.get('binding') != binding:
            raise RemoteError('远端同步状态属于其他服务、设备或目录，请使用独立状态目录')
        try:
            remote = transport(config, 'GET')
            if remote['device'] != device:
                raise RemoteError('服务端令牌绑定的 device 与 --device-id 不一致')
            if pending and pending.get('user') != remote['user']:
                raise RemoteError('未完成提交属于其他用户，请使用独立状态目录')
            if baseline and remote['user'] != baseline['user']:
                raise RemoteError('服务端用户已变化，请使用独立状态目录')
            if type(remote['revision']) is not int or remote['revision'] < baseline.get('revision', 0):
                raise RemoteError('服务端版本回退，请检查数据库恢复记录')
            allowed = remote['scope']
            if files and (not allowed['configuration']['enabled'] or not set(files) <= set(allowed['configuration']['files'])):
                raise RemoteError('客户端配置范围超出服务端清单')
            if names and (not allowed['dictionaries']['enabled'] or not set(names) <= set(allowed['dictionaries']['names'])):
                missing = sorted(set(names) - set(allowed['dictionaries']['names']))
                raise RemoteError('客户端词典范围超出服务端清单，请启用并对齐服务端范围: ' + ', '.join(missing))
            local, merged, updates, conflicts = {}, {}, {}, {}
            base = baseline.get('configuration', {})
            for name in files:
                path = safe_path(source, name)
                local[name] = encode(path.read_bytes()) if path.exists() else None
                server_value = remote['configuration'].get(name)
                if server_value is not None:
                    decode(server_value)
                if name in base and base[name] is not None and name not in remote['configuration']:
                    raise RemoteError('服务端缺少已同步文件且没有删除标记，拒绝推断删除')
                try:
                    if name not in base and name in remote['configuration'] and server_value is None and local[name] is not None:
                        raise RemoteError('远端删除标记与本地文件冲突')
                    pending_configs = pending.get('configuration', {})
                    known_upload = name in pending_configs and pending_configs[name] == server_value
                    merge_base = server_value if known_upload else base.get(name)
                    merged[name] = merge_file(merge_base, local[name], server_value, name in base or known_upload)
                except RemoteError:
                    conflicts[name] = {'base': base.get(name), 'local': local[name], 'remote': server_value}
                    if resolve in ('local', 'remote'):
                        merged[name] = local[name] if resolve == 'local' else server_value
                    else:
                        continue
                if merged[name] != server_value:
                    updates[name] = merged[name]
            if conflicts:
                conflict_path = safe_path(state, 'conflicts.json')
                atomic_write(conflict_path, json.dumps({'revision': remote['revision'], 'files': conflicts}, indent=2).encode())
                if resolve not in ('local', 'remote'):
                    raise RemoteError(f'配置冲突，双方 Base64 内容已保留: {conflict_path}；检查后使用 --resolve-conflicts local 或 remote')
                print(f'按显式选择解决 {len(conflicts)} 个配置冲突: {resolve}', flush=True)
            # All config conflicts are detected before native commands or uploads.
            with tempfile.TemporaryDirectory(prefix='incoming-', dir=state) as temp:
                store = Path(temp)
                own_before = snapshots(sync_dir, [device], names) if names else {}
                own_base = baseline.get('dictionaries', {})
                remote_own = remote['dictionaries'].get(device, {})
                for owner, dictionaries in remote['dictionaries'].items():
                    component(owner)
                    for name, value in dictionaries.items():
                        if name not in names:
                            continue
                        data = decode(value)
                        validate_snapshot(data, owner, name)
                        if owner == device:
                            path_key = f'{device}/{name}.userdb.txt'
                            current = own_before.get(path_key)
                            if current is not None and encode(current) != value and value != own_base.get(name) and value != pending.get('dictionaries', {}).get(name):
                                raise RemoteError('本设备服务端词典与本地快照分叉，保留双方；请检查设备 ID 是否复用')
                            if current is None:
                                # Restore a lost local snapshot without touching a live database.
                                atomic_write(checked(sync_dir / path_key), data)
                        else:
                            atomic_write(store / owner / (name + '.userdb.txt'), data)
                if names:
                    exchange(sync_dir, store, device, state / 'dictionary-apply', command=command, names=names, native=native)
                outgoing = snapshots(sync_dir, [device], names) if names and (not native or native.publish_allowed) else {}
                dictionary_updates = {Path(path).name.removesuffix('.userdb.txt'): encode(data) for path, data in outgoing.items()}
                dictionary_updates = {name: value for name, value in dictionary_updates.items() if remote_own.get(name) != value}
                payload = {'base_revision': remote['revision'], 'configuration': updates, 'dictionaries': dictionary_updates}
                if updates or dictionary_updates:
                    atomic_write(pending_path, json.dumps({'binding': binding, 'user': remote['user'], **payload}, indent=2).encode())
                    acknowledged = transport(config, 'PATCH', payload)
                else:
                    acknowledged = remote
            # Do not overwrite edits made while the HTTPS/native operations ran.
            for name in files:
                path = safe_path(source, name)
                current = encode(path.read_bytes()) if path.exists() else None
                if current != local[name]:
                    raise RemoteError('同步过程中 config/ 已变化，保留本地修改并在下一轮重新合并')
            session = state / 'backups' / uuid.uuid4().hex
            changes = [name for name in files if merged[name] != local[name]]
            for name in changes:
                if local[name] is not None:
                    atomic_write(safe_path(session, name), decode(local[name]))
            completed = []
            try:
                for name in changes:
                    path = safe_path(source, name)
                    if merged[name] is None:
                        path.unlink(missing_ok=True)
                    else:
                        atomic_write(path, decode(merged[name]))
                    completed.append(name)
                new_base = dict(base)
                new_base.update(merged)
                new_own = dict(own_base)
                new_own.update({Path(path).name.removesuffix('.userdb.txt'): encode(data) for path, data in outgoing.items()})
                mode = 'native-all' if native and names else 'native-command' if command and names else 'snapshots-only'
                application = native.application if native and names else {'mode': mode, 'names': names}
                atomic_write(baseline_path, json.dumps({'binding': binding, 'user': remote['user'], 'revision': acknowledged['revision'], 'configuration': new_base, 'dictionaries': new_own, 'dictionary_application': application}, indent=2).encode())
            except BaseException:
                for name in reversed(completed):
                    path = safe_path(source, name)
                    if local[name] is None:
                        path.unlink(missing_ok=True)
                    else:
                        atomic_write(path, decode(local[name]))
                raise
            pending_path.unlink(missing_ok=True)
            schedule = {'key': key, 'next_attempt': now + config['interval_seconds']}
            atomic_write(schedule_path, json.dumps(schedule).encode())
            print(f'服务端同步完成，版本 {acknowledged["revision"]}；配置合并写入 config/。', flush=True)
            return 'synced'
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError, RemoteError) as exc:
            atomic_write(schedule_path, json.dumps({'key': key, 'next_attempt': now + config['retry_seconds'], 'error': True}).encode())
            if isinstance(exc, RemoteError):
                raise
            raise RemoteError('远端同步失败；本地修改及上次成功基线保留') from exc
