import hashlib
from backend.app.config import settings

def compute_device_hash(raw_entropy: str) -> str:
    """
    Computes a cryptographic SHA-256 hash using the raw device entropy and host pepper.
    """
    payload = f"{settings.FINGERPRINT_PEPPER}:{raw_entropy.strip()}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

def verify_device_hash(raw_entropy: str, stored_hash: str) -> bool:
    """
    Verifies if the submitted device entropy matches the host-stored hash.
    """
    candidate_hash = compute_device_hash(raw_entropy)
    return candidate_hash == stored_hash
