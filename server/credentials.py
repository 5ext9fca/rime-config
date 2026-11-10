"""Persistent device rotation, per-user scope additions and managed backups."""
from contextlib import closing
import hashlib
import hmac
import json
import os
from pathlib import Path
import sqlite3
import time


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def authenticate(db, devices, token, refresh=False, now=None):
    now = time.time() if now is None else now
    hashed = digest(token)
    for device in devices:
        seed = digest(device['token'])
        row = db.execute('SELECT seed,current,previous,previous_until FROM credentials WHERE user=? AND device=?',
                         (device['user'],device['device'])).fetchone()
        # Removing a settings entry revokes every rotated token. Changing its
        # bootstrap token resets that registration without reviving old tokens.
        if row is None or row[0] != seed:
            db.execute('INSERT OR REPLACE INTO credentials VALUES (?,?,?,?,?,?)',
                       (device['user'],device['device'],seed,seed,'',0))
            row=(seed,seed,'',0)
        if hmac.compare_digest(hashed,row[1]):
            return device, 'current'
        if row[2] and hmac.compare_digest(hashed,row[2]) and (refresh or now < row[3]):
            return device, 'previous'
    return None, None


def rotate(db, device, auth_kind, token, now=None):
    from client.config.identity import valid_token
    valid_token(token)
    now=time.time() if now is None else now
    key=(device['user'],device['device'])
    current,previous,until=db.execute('SELECT current,previous,previous_until FROM credentials WHERE user=? AND device=?',key).fetchone()
    new=digest(token)
    if hmac.compare_digest(new,current):
        return {'status':'rotated'}  # lost response retry, including expired grace
    if auth_kind != 'current' or (previous and now < until):
        raise PermissionError('Rotation already pending or in grace period')
    if hmac.compare_digest(new,previous):
        raise ValueError('Cannot reuse previous token')
    db.execute('UPDATE credentials SET current=?,previous=?,previous_until=? WHERE user=? AND device=?',
               (new,current,now+86400,*key))
    return {'status':'rotated'}


