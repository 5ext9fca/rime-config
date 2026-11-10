"""Authenticated HTTPS transport and endpoint configuration."""
import json
import math
import os
from pathlib import Path
import http.client
import urllib.request
import urllib.error
import urllib.parse
from client.transport.remote_errors import RemoteError, RevisionChanged
def load_remote(path):
    config = json.loads(Path(path).read_text(encoding='utf-8'))
    required = {'enabled', 'url', 'interval_seconds', 'retry_seconds', 'timeout_seconds'}
    if not isinstance(config, dict) or not required <= set(config) or set(config)-required-{'token_env','token_refresh_seconds','auto_expand_dictionaries'}:
        raise ValueError('Invalid remote.json fields')
    if type(config.get('token_refresh_seconds',0)) is not int or config.get('token_refresh_seconds',0)<0 or 0<config.get('token_refresh_seconds',0)<86400:
        raise ValueError('token_refresh_seconds must be 0 or at least 86400')
    if type(config.get('auto_expand_dictionaries',False)) is not bool:
        raise ValueError('auto_expand_dictionaries must be boolean')
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

