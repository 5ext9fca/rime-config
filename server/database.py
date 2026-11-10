"""SQLite schema initialization."""
def initialize(db):
    db.execute('CREATE TABLE IF NOT EXISTS credentials (user TEXT, device TEXT, seed TEXT, current TEXT, previous TEXT, previous_until REAL, PRIMARY KEY(user,device))')
    db.execute('CREATE TABLE IF NOT EXISTS dictionary_scopes (user TEXT, name TEXT, PRIMARY KEY(user,name))')
    db.execute('CREATE TABLE IF NOT EXISTS maintenance (key TEXT PRIMARY KEY, timestamp REAL)')


