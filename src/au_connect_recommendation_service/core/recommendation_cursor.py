"""Signed, user-scoped continuation tokens for score-descending/ID-ascending order."""
import base64
import binascii
import hashlib
import hmac
import json
import math

from bson import ObjectId

from au_connect_recommendation_service.core.env import INTERNAL_API_KEY


class InvalidCursor(ValueError):
    pass


def encode_cursor(user_id: str, score: float, candidate_id: str) -> str:
    payload = json.dumps([1, user_id, score, candidate_id], separators=(",", ":")).encode()
    signature = hmac.digest(INTERNAL_API_KEY.encode(), b"connection-cursor:" + payload, hashlib.sha256)
    return base64.urlsafe_b64encode(signature + payload).decode().rstrip("=")


def decode_cursor(token: str, user_id: str) -> tuple[float, str]:
    try:
        if not token or len(token) > 1024:
            raise ValueError
        raw = base64.b64decode(token + "=" * (-len(token) % 4), altchars=b"-_", validate=True)
        signature, payload = raw[:32], raw[32:]
        expected = hmac.digest(INTERNAL_API_KEY.encode(), b"connection-cursor:" + payload, hashlib.sha256)
        if not hmac.compare_digest(signature, expected):
            raise ValueError
        version, owner, score, candidate_id = json.loads(payload)
        if (type(version) is not int or version != 1 or owner != user_id
                or type(score) not in (int, float) or not math.isfinite(score)
                or not 0 <= score <= 1 or not isinstance(candidate_id, str)
                or not ObjectId.is_valid(candidate_id) or str(ObjectId(candidate_id)) != candidate_id):
            raise ValueError
        return float(score), candidate_id
    except (ValueError, TypeError, binascii.Error, UnicodeError) as exc:
        raise InvalidCursor("Invalid connection recommendations cursor (malformed or wrong user)") from exc
