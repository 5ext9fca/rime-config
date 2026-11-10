"""Refresh explicitly selected GitHub dictionary blobs at a pinned commit."""
from client.storage.file_lock import lock_exclusive
import hashlib
import http.client
import json
import math
import os
from pathlib import Path
import re
import tempfile
import time
import urllib.parse
import urllib.request
import uuid

from client.storage.filesystem import atomic_write
from client.storage.config_paths import relative_name, safe_path


class RefreshError(RuntimeError):
    """A failed refresh, with the old success receipt preserved."""


def load_config(path, personal_files):
    config = json.loads(Path(path).read_text(encoding='utf-8'))
    keys = {'enabled', 'interval_seconds', 'retry_seconds', 'timeout_seconds', 'max_download_bytes', 'source'}
    if not isinstance(config, dict) or set(config) != keys:
        raise ValueError('第三方配置字段必须为: ' + ', '.join(sorted(keys)))
    if type(config['enabled']) is not bool:
        raise ValueError('enabled 必须为布尔值')
    for key in ('interval_seconds', 'retry_seconds', 'timeout_seconds', 'max_download_bytes'):
        value = config[key]
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError(f'{key} 必须为有限正数')
    if type(config['max_download_bytes']) is not int:
        raise ValueError('max_download_bytes 必须为整数')
    source = config['source']
    if not isinstance(source, dict) or set(source) != {'repository', 'ref', 'files'}:
        raise ValueError('source 必须包含 repository、ref、files')
    if not isinstance(source['repository'], str) or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', source['repository']):
        raise ValueError('repository 必须为 GitHub owner/repo')
    if not isinstance(source['ref'], str) or not source['ref'].strip():
        raise ValueError('ref 必须是分支、标签或提交 SHA')
    files = source['files']
    if not isinstance(files, list) or not files or not all(isinstance(n, str) for n in files):
        raise ValueError('source.files 必须是非空文件列表')
    if len({name.casefold() for name in files}) != len(files):
        raise ValueError('source.files 不能重复')
    for name in files:
        relative_name(name)
        p = relative_name(name.casefold())
        if not (name.endswith('.dict.yaml') or name.endswith('.txt')) or p.name.startswith('custom_phrase'):
            raise ValueError(f'只允许第三方词典文件: {name}')
        for personal in personal_files:
            q = relative_name(personal.casefold())
            if p == q or p in q.parents or q in p.parents:
                raise ValueError(f'第三方词典与个人配置清单冲突: {name}')
    return config


def get_bytes(url, timeout, limit):
    request = urllib.request.Request(url, headers={'User-Agent': 'rime-config-client', 'Accept': 'application/vnd.github+json'})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if urllib.parse.urlparse(response.url).scheme != 'https':
            raise ValueError('拒绝非 HTTPS 下载')
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError('上游响应超过下载大小限制')
    return data


def github_index(config):
    source = config['source']
    base = 'https://api.github.com/repos/' + source['repository']
    ref = urllib.parse.quote(source['ref'], safe='')
    timeout = config['timeout_seconds']
    commit = json.loads(get_bytes(base + '/commits/' + ref, timeout, 2 * 1024 * 1024))
    sha = commit['sha']
    if not isinstance(sha, str) or not re.fullmatch('[0-9a-f]{40}', sha):
        raise ValueError('GitHub 提交 SHA 无效')
    tree_sha = commit['commit']['tree']['sha']
    if not isinstance(tree_sha, str) or not re.fullmatch('[0-9a-f]{40}', tree_sha):
        raise ValueError('GitHub tree SHA 无效')
    tree = json.loads(get_bytes(base + '/git/trees/' + tree_sha + '?recursive=1', timeout, 16 * 1024 * 1024))
    if tree.get('truncated'):
        raise ValueError('上游文件清单被截断，拒绝刷新')
    entries = {item['path']: item for item in tree['tree']}
    selected = {}
    for name in source['files']:
        item = entries.get(name)
        if not item or item.get('type') != 'blob' or item.get('mode') not in ('100644', '100755'):
            raise ValueError(f'上游词典缺失或不是普通文件: {name}')
        if not re.fullmatch('[0-9a-f]{40}', item.get('sha', '')):
            raise ValueError(f'上游文件哈希无效: {name}')
        if type(item.get('size')) is not int or item['size'] <= 0:
            raise ValueError(f'上游词典大小无效: {name}')
        selected[name] = item
    if sum(item['size'] for item in selected.values()) > config['max_download_bytes']:
        raise ValueError('词典总大小超过 max_download_bytes')
    return sha, selected


def validate_blob(name, data, item):
    blob_sha = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
    if len(data) != item['size'] or blob_sha != item['sha']:
        raise ValueError(f'词典完整性校验失败: {name}')
    text = data.decode('utf-8-sig')
    if not text.strip() or '\0' in text:
        raise ValueError(f'词典文本无效: {name}')
    if name.endswith('.dict.yaml'):
        if not re.search(r'^---\s*$', text, re.M) or not re.search(r'^\.\.\.\s*$', text, re.M) or not re.search(r'^name:\s*\S+', text, re.M):
            raise ValueError(f'缺少 Rime 词典头: {name}')


def fingerprint(config):
    return hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()


def refresh(config, target, state, dry_run=False, force=False, now=None):
    """No network in dry-run; stage all blobs before backing up/replacing targets."""
    if not config['enabled']:
        if dry_run or force:
            print('第三方词典刷新已由项目配置禁用。', flush=True)
        return 'disabled'
    now = time.time() if now is None else now
    target, state = (Path(os.path.abspath(p)) for p in (target, state))
    if target == state or target in state.parents or state in target.parents:
        raise ValueError('第三方状态目录与目标目录不能重叠')
    safe_path(target)
    safe_path(state)
    for name in config['source']['files']:
        safe_path(target, name)
    receipt_path = safe_path(state, 'receipt.json')
    schedule_path = safe_path(state, 'schedule.json')
    key = fingerprint(config)

    def is_due():
        schedule = json.loads(schedule_path.read_text(encoding='utf-8')) if schedule_path.exists() else {}
        if schedule and schedule.get('target') != str(target):
            raise ValueError('第三方状态目录属于不同目标')
        return force or schedule.get('config') != key or now >= schedule.get('next_attempt', 0)

    if dry_run:
        due = is_due()
        print(f'第三方词典: {config["source"]["repository"]}@{config["source"]["ref"]}，' + ('待刷新' if due else '未到刷新时间'), flush=True)
        if due:
            for name in config['source']['files']:
                print(f'third-party-check\t{name}', flush=True)
        return 'planned' if due else 'not-due'
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    with safe_path(state, 'lock').open('a') as lock:
        lock_exclusive(lock)
        if not is_due():
            return 'not-due'
        schedule = {'target': str(target), 'config': key}
        try:
            commit, entries = github_index(config)
            print(f'第三方词典刷新: {config["source"]["repository"]}@{commit}', flush=True)
            hashes = {}
            # Stage under state, never under config/ or a live Rime directory.
            with tempfile.TemporaryDirectory(prefix='download-', dir=state) as temporary:
                stage = Path(temporary)
                for name, item in entries.items():
                    url = 'https://raw.githubusercontent.com/' + config['source']['repository'] + '/' + commit + '/' + urllib.parse.quote(name, safe='/')
                    data = get_bytes(url, config['timeout_seconds'], item['size'])
                    validate_blob(name, data, item)
                    atomic_write(stage / name, data)
                    hashes[name] = hashlib.sha256(data).hexdigest()
                changed = []
                for name in entries:
                    dest = safe_path(target, name)
                    if not dest.exists() or hashlib.sha256(dest.read_bytes()).hexdigest() != hashes[name]:
                        changed.append(name)
                session = state / 'backups' / (time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8])
                journal = {'target': str(target), 'commit': commit, 'files': {}, 'status': 'prepared'}
                if changed:
                    safe_path(session)
                    session.mkdir(parents=True)
                    for name in changed:
                        dest = safe_path(target, name)
                        existed = dest.exists()
                        journal['files'][name] = {'existed': existed, 'sha256': hashes[name]}
                        if existed:
                            atomic_write(session / 'files' / name, dest.read_bytes())
                    atomic_write(session / 'journal.json', json.dumps(journal, indent=2).encode())
                done = []
                try:
                    for name in changed:
                        atomic_write(safe_path(target, name), (stage / name).read_bytes())
                        done.append(name)
                        print(f'third-party-update\t{name}', flush=True)
                    receipt = {'target': str(target), 'repository': config['source']['repository'], 'ref': config['source']['ref'], 'commit': commit, 'files': hashes, 'updated_at': now}
                    atomic_write(receipt_path, json.dumps(receipt, indent=2).encode())
                except BaseException:
                    for name in reversed(done):
                        dest = safe_path(target, name)
                        if journal['files'][name]['existed']:
                            atomic_write(dest, (session / 'files' / name).read_bytes())
                        else:
                            dest.unlink(missing_ok=True)
                    raise
                if changed:
                    journal['status'] = 'applied'
                    atomic_write(session / 'journal.json', json.dumps(journal, indent=2).encode())
                    print(f'第三方词典已更新，备份: {session}；请重新部署 Rime。', flush=True)
                else:
                    print('第三方词典已是当前版本。', flush=True)
            schedule.update(next_attempt=now + config['interval_seconds'], last_success=now)
            atomic_write(schedule_path, json.dumps(schedule, indent=2).encode())
            return 'updated' if changed else 'unchanged'
        except (OSError, ValueError, KeyError, TypeError, http.client.HTTPException) as exc:
            schedule.update(next_attempt=now + config['retry_seconds'], last_error=str(exc))
            atomic_write(schedule_path, json.dumps(schedule, indent=2).encode())
            raise RefreshError(f'第三方词典刷新失败，将在 {config["retry_seconds"]} 秒后重试: {exc}') from exc
