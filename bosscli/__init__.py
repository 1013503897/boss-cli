"""boss-cli: off-device BOSS直聘 search API client (pure-Python libyzwg reproduction)."""
from .yzwg import (
    native_signature, native_encode_request, native_encode_request_body,
    native_decode_content, native_calculate_crc32, SALT,
)

__all__ = [
    "native_signature", "native_encode_request", "native_encode_request_body",
    "native_decode_content", "native_calculate_crc32", "SALT",
]
__version__ = "0.1.0"
