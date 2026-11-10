"""UTF-8 wire encoding."""
import base64
import binascii
from client.transport.remote_errors import RemoteError
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

