from typing import Final

MIN_CONFIRMATIONS: Final[int] = 1

_PROTOCOL_LABEL_PREFIX: Final[bytes] = b"superorganism"
REGISTRATION_PROTOCOL_LABEL: Final[bytes] = _PROTOCOL_LABEL_PREFIX + b"-register-v1"
AUTHENTICATION_PROTOCOL_LABEL: Final[bytes] = (
    _PROTOCOL_LABEL_PREFIX + b"-authenticate-v1"
)
