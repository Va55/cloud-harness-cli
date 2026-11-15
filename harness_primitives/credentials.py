"""
Secure credential caching for AWS Harness.

Only caches TEMPORARY credentials (AssumeRole, SSO).
Never caches static access keys.

Uses atomic writes:
- O_CREAT | O_EXCL | O_NOFOLLOW + fsync + os.replace()
- File permissions: 0600
- Directory permissions: 0700
"""

import json
import os
import time
from pathlib import Path


class CredentialCache:
    """Secure credential caching with atomic writes."""

    CACHE_DIR = Path.home() / ".cache" / "aws-harness"

    def __init__(self):
        self.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        os.chmod(self.CACHE_DIR, 0o700)

    def put(self, session_key: str, credentials: dict, ttl_seconds: int = 3600):
        """Store credentials with TTL using atomic write.

        Only cache temporary credentials (Never static keys).
        """
        cache_file = self.CACHE_DIR / f"{session_key}.json"
        data = {
            "credentials": credentials,
            "expires_at": time.time() + ttl_seconds,
            "created_at": time.time(),
        }
        # Atomic write with UNIQUE tmp name (pid) — a crashed process
        # cannot wedge future writes with a stale .tmp file.
        # O_NOFOLLOW is POSIX-only (missing on Windows) — getattr guard
        # keeps the strict flag where it exists without crashing there.
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        tmp_path = f"{cache_file}.{os.getpid()}.tmp"
        try:
            fd = os.open(tmp_path,
                         os.O_CREAT | os.O_EXCL | os.O_WRONLY | nofollow, 0o600)
        except FileExistsError:
            # Our own stale tmp (pid reuse) — remove and retry once
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            try:
                fd = os.open(tmp_path,
                             os.O_CREAT | os.O_EXCL | os.O_WRONLY | nofollow, 0o600)
            except OSError:
                return  # Cannot write — fail silently, cache is best-effort
        try:
            with os.fdopen(fd, 'w') as f:
                json.dump(data, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, str(cache_file))
        except Exception:
            # Clean up temp file on error
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    def get(self, session_key: str) -> dict | None:
        """Get cached credentials if not expired."""
        cache_file = self.CACHE_DIR / f"{session_key}.json"
        if not cache_file.exists():
            return None
        try:
            with open(cache_file, 'r') as f:
                data = json.load(f)
            if time.time() > data["expires_at"]:
                return None  # Expired
            return data["credentials"]
        except (json.JSONDecodeError, KeyError):
            return None  # Corrupted

    def clear(self, session_key: str):
        """Remove specific cache entry."""
        cache_file = self.CACHE_DIR / f"{session_key}.json"
        if cache_file.exists():
            cache_file.unlink()

    def clear_all(self):
        """Clear all cached credentials and stale tmp files (--refresh flag)."""
        for f in self.CACHE_DIR.glob("*.json"):
            try:
                f.unlink()
            except OSError:
                pass
        # Also sweep orphaned tmp files from crashed processes
        for f in self.CACHE_DIR.glob("*.tmp"):
            try:
                f.unlink()
            except OSError:
                pass

    @property
    def exists(self) -> bool:
        return self.CACHE_DIR.exists()
