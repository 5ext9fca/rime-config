"""Pure three-way comparison, including explicit deletion and conflict semantics."""
class MergeConflict(ValueError):
    pass

def merge_file(base, local, remote, tracked):
    """Return a whole-file merge; never silently resolve two distinct edits."""
    if local == remote:
        return local
    if not tracked:
        if local is None:
            return remote
        if remote is None:
            return local
        raise MergeConflict('首次同步时双方文件不同')
    if local == base:
        return remote
    if remote == base:
        return local
    raise MergeConflict('双方均修改了同一文件')

