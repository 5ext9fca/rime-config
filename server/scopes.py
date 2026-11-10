"""Per-user dictionary scope extension."""
def extend_scope(db, user, names, base, limit):
    from client.core.dictionary_format import component
    if not isinstance(names,list) or not names or len(names)>limit:
        raise ValueError('Invalid dictionary list')
    for name in names:
        component(name)
        if '.userdb' in name.casefold():raise ValueError('Invalid dictionary name')
    old=[r[0] for r in db.execute('SELECT name FROM dictionary_scopes WHERE user=?',(user,))]
    merged=set(base)|set(old)|set(names)
    if len(merged)>limit or len({n.casefold() for n in merged})!=len(merged):
        raise ValueError('Dictionary limit or case collision')
    db.executemany('INSERT OR IGNORE INTO dictionary_scopes VALUES (?,?)',[(user,n) for n in names])
    return sorted(merged)


