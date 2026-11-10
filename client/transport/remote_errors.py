"""Remote protocol errors shared by transport and orchestration."""
class RemoteError(RuntimeError):
    pass


class RevisionChanged(RemoteError):
    pass

