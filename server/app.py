"""Authenticated, revision-checked Rime state storage behind a TLS reverse proxy."""
import base64
from contextlib import closing
import binascii
import hmac
import json
import os
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import credentials, database, scopes, backups
from client.core.scope import load_scope
from client.core.dictionary_format import component, validate_snapshot


class APIError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message


def decode(value):
    if not isinstance(value, str):
        raise ValueError('Expected base64 string')
    try:
        data = base64.b64decode(value, validate=True)
        data.decode('utf-8-sig')
        return data
    except (binascii.Error, UnicodeError) as exc:
        raise ValueError('Expected base64 UTF-8 text') from exc


def create_app(settings_path=None):
    path = Path(settings_path or os.environ.get('RIME_SETTINGS', '/config/settings.json'))
    settings = json.loads(path.read_text())
    required = {'database', 'scope', 'max_request_bytes', 'max_state_bytes', 'devices'}
    if not required <= set(settings) or set(settings)-required-{'auto_expand_dictionaries','max_dictionaries','backups'}:
        raise ValueError('Invalid server settings fields')
    for key in ('max_request_bytes', 'max_state_bytes'):
        if type(settings[key]) is not int or settings[key] <= 0:
            raise ValueError('Invalid size limit')
    auto_expand = settings.get('auto_expand_dictionaries', False)
    max_dictionaries = settings.get('max_dictionaries', 128)
    backup_policy = settings.get('backups', {'enabled': False, 'interval_seconds': 86400, 'retention_days': 30, 'keep_minimum': 7})
    if type(auto_expand) is not bool or type(max_dictionaries) is not int or not 1 <= max_dictionaries <= 1024:
        raise ValueError('Invalid scope expansion policy')
    if (not isinstance(backup_policy, dict) or set(backup_policy) != {'enabled','interval_seconds','retention_days','keep_minimum'}
            or type(backup_policy['enabled']) is not bool or any(type(backup_policy[k]) is not int or backup_policy[k] <= 0 for k in ('interval_seconds','retention_days','keep_minimum'))):
        raise ValueError('Invalid backup policy')
    scope_path = (path.parent / settings['scope']).resolve()
    load_scope(scope_path)
    devices = settings['devices']
    if not isinstance(devices, list) or not devices:
        raise ValueError('Configure at least one device')
    tokens, identities = set(), set()
    for device in devices:
        if not isinstance(device, dict) or set(device) != {'user', 'device', 'token'}:
            raise ValueError('Invalid device settings')
        component(device['user'])
        component(device['device'])
        token = device['token']
        if not isinstance(token, str) or len(token) < 32 or not token.isascii() or not all(33 <= ord(c) <= 126 for c in token) or token.startswith('REPLACE_'):
            raise ValueError('Replace device token with a random secret of at least 32 characters')
        identity = (device['user'], device['device'])
        if token in tokens or identity in identities:
            raise ValueError('Duplicate device identity or token')
        tokens.add(token)
        identities.add(identity)
    db_path = (path.parent / settings['database']).resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(db_path)) as db, db:
        db.execute('PRAGMA journal_mode=WAL')
        database.initialize(db)
        db.execute('CREATE TABLE IF NOT EXISTS states (user TEXT PRIMARY KEY, revision INTEGER NOT NULL, payload TEXT NOT NULL)')

    def transact(device, patch=None):
        scope = load_scope(scope_path)
        configs = set(scope['configuration']['files']) if scope['configuration']['enabled'] else set()
        with closing(sqlite3.connect(db_path, timeout=20)) as db, db:
            db.execute('BEGIN IMMEDIATE' if patch is not None else 'BEGIN')
            if auto_expand and scope['dictionaries']['enabled']:
                scope['dictionaries']['names'] = sorted(set(scope['dictionaries']['names']) | {r[0] for r in db.execute('SELECT name FROM dictionary_scopes WHERE user=?',(device['user'],))})
            names = set(scope['dictionaries']['names']) if scope['dictionaries']['enabled'] else set()
            row = db.execute('SELECT revision, payload FROM states WHERE user=?', (device['user'],)).fetchone()
            revision, state = (row[0], json.loads(row[1])) if row else (0, {'configuration': {}, 'dictionaries': {}})
            if patch is not None:
                if not isinstance(patch, dict) or set(patch) != {'base_revision', 'configuration', 'dictionaries'}:
                    raise APIError(400, 'Invalid patch fields')
                if type(patch['base_revision']) is not int or patch['base_revision'] < 0:
                    raise APIError(400, 'Invalid base_revision')
                if patch['base_revision'] != revision:
                    raise APIError(409, 'Revision changed; pull and merge again')
                if not isinstance(patch['configuration'], dict) or not isinstance(patch['dictionaries'], dict):
                    raise APIError(400, 'Expected patch maps')
                for name, value in patch['configuration'].items():
                    if name not in configs:
                        raise APIError(403, 'Configuration is outside server scope')
                    if value is not None:
                        decode(value)
                for name, value in patch['dictionaries'].items():
                    if name not in names:
                        raise APIError(403, 'Dictionary is outside server scope')
                    validate_snapshot(decode(value), device['device'], name)
                before = json.dumps(state, sort_keys=True)
                state['configuration'].update(patch['configuration'])
                if patch['dictionaries']:
                    state['dictionaries'].setdefault(device['device'], {}).update(patch['dictionaries'])
                payload = json.dumps(state, sort_keys=True)
                if len(payload.encode()) > settings['max_state_bytes']:
                    raise APIError(413, 'User state quota exceeded')
                if payload != before:
                    revision += 1
                    db.execute('INSERT INTO states VALUES (?, ?, ?) ON CONFLICT(user) DO UPDATE SET revision=excluded.revision,payload=excluded.payload', (device['user'], revision, payload))
            return {'revision': revision, 'user': device['user'], 'device': device['device'], 'scope': scope,
                    'configuration': {k: v for k, v in state['configuration'].items() if k in configs},
                    'dictionaries': {owner: {k: v for k, v in values.items() if k in names} for owner, values in state['dictionaries'].items()}}

    def application(environ, start_response):
        def reply(status, value):
            data = json.dumps(value, ensure_ascii=False).encode()
            statuses = {200: 'OK', 400: 'Bad Request', 401: 'Unauthorized', 403: 'Forbidden', 404: 'Not Found', 405: 'Method Not Allowed', 409: 'Conflict', 411: 'Length Required', 413: 'Content Too Large', 415: 'Unsupported Media Type', 503: 'Service Unavailable'}
            start_response(f'{status} {statuses[status]}', [('Content-Type', 'application/json; charset=utf-8'), ('Content-Length', str(len(data))), ('Cache-Control', 'private, no-store'), ('X-Content-Type-Options', 'nosniff')])
            return [data]
        try:
            route = environ.get('PATH_INFO', '')
            method = environ.get('REQUEST_METHOD', '')
            if route == '/healthz' and method == 'GET':
                from client.maintenance.logs import clean
                clean(db_path.parent / 'logs', {'enabled':True,'retention_days':30})
                with closing(sqlite3.connect(db_path)) as db, db:
                    db.execute('SELECT 1 FROM states LIMIT 1')
                return reply(200, {'status': 'ok'})
            if route not in ('/rime/v1/state','/rime/v1/token/refresh','/rime/v1/scope/dictionaries'):
                return reply(404, {'error': 'Not found'})
            auth = environ.get('HTTP_AUTHORIZATION', '')
            with closing(sqlite3.connect(db_path, timeout=20)) as db, db:
                db.execute('BEGIN IMMEDIATE')
                identity, auth_kind = credentials.authenticate(db,devices,auth[7:] if auth.startswith('Bearer ') else '', refresh=route=='/rime/v1/token/refresh')
            if identity is None:
                return reply(401, {'error': 'Invalid credentials'})
            if method == 'GET' and route == '/rime/v1/state':
                return reply(200, transact(identity))
            if method != ('PATCH' if route == '/rime/v1/state' else 'POST'):
                return reply(405, {'error': 'Use GET or PATCH'})
            if environ.get('CONTENT_TYPE', '').split(';')[0] != 'application/json':
                return reply(415, {'error': 'Expected application/json'})
            size = environ.get('CONTENT_LENGTH', '')
            if not size:
                return reply(411, {'error': 'Content-Length required'})
            if not size.isdigit():
                return reply(400, {'error': 'Invalid Content-Length'})
            size = int(size)
            if size > settings['max_request_bytes']:
                return reply(413, {'error': 'Request too large'})
            body = environ['wsgi.input'].read(size)
            if len(body) != size:
                return reply(400, {'error': 'Incomplete body'})
            payload = json.loads(body)
            if not isinstance(payload, dict):
                raise APIError(400, 'Expected JSON object')
            if route != '/rime/v1/state':
                with closing(sqlite3.connect(db_path, timeout=20)) as db, db:
                    db.execute('BEGIN IMMEDIATE')
                    # Revalidate under the mutation lock: another worker may rotate.
                    identity, auth_kind = credentials.authenticate(db,devices,auth[7:],refresh=route=='/rime/v1/token/refresh')
                    if identity is None:raise APIError(401,'Invalid credentials')
                    if route.endswith('/token/refresh'):
                        if set(payload) != {'token'}:raise APIError(400,'Invalid rotation payload')
                        try:result=credentials.rotate(db,identity,auth_kind,payload['token'])
                        except PermissionError:raise APIError(409,'Token rotation conflict')
                    else:
                        scope=load_scope(scope_path)
                        if not auto_expand or not scope['dictionaries']['enabled']:raise APIError(403,'Scope expansion disabled')
                        if set(payload) != {'names'}:raise APIError(400,'Invalid scope payload')
                        result={'names':scopes.extend_scope(db,identity['user'],payload['names'],scope['dictionaries']['names'],max_dictionaries)}
                return reply(200,result)
            return reply(200, transact(identity, payload))
        except APIError as exc:
            return reply(exc.status, {'error': exc.message})
        except (ValueError, TypeError, KeyError):
            return reply(400, {'error': 'Invalid request or snapshot'})
        except (OSError, sqlite3.Error):
            return reply(503, {'error': 'Storage unavailable'})
    return application
