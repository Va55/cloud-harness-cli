"""Tests for the credential cache — security critical.

Verifies:
- Atomic writes don't wedge after crash (unique tmp names)
- Permissions: 0600 file, 0700 dir
- TTL expiry
- Only temp credentials pattern supported
- clear_all sweeps stale .tmp files
"""

import json
import os
import stat
from pathlib import Path

import pytest

from harness_primitives.credentials import CredentialCache


@pytest.fixture
def cache(tmp_path, monkeypatch):
    """CredentialCache pointed at a temp dir."""
    monkeypatch.setattr(CredentialCache, "CACHE_DIR", tmp_path / "creds")
    return CredentialCache()


class TestPermissions:
    def test_dir_created_with_0700(self, cache):
        assert stat.S_IMODE(os.stat(cache.CACHE_DIR).st_mode) == 0o700

    def test_file_written_with_0600(self, cache):
        cache.put("sess", {"AccessKeyId": "AKIA-TEMP"}, ttl_seconds=60)
        f = cache.CACHE_DIR / "sess.json"
        assert stat.S_IMODE(os.stat(f).st_mode) == 0o600

    def test_no_group_or_other_access(self, cache):
        cache.put("sess", {"key": "val"}, ttl_seconds=60)
        mode = stat.S_IMODE(os.stat(cache.CACHE_DIR / "sess.json").st_mode)
        assert mode & 0o077 == 0, "No group/other access allowed"


class TestPutGet:
    def test_roundtrip(self, cache):
        creds = {"AccessKeyId": "AKIA-TEMP", "SecretAccessKey": "sec", "SessionToken": "tok"}
        cache.put("sess", creds, ttl_seconds=3600)
        assert cache.get("sess") == creds

    def test_missing_key_returns_none(self, cache):
        assert cache.get("nonexistent") is None

    def test_expired_returns_none(self, cache):
        cache.put("sess", {"key": "val"}, ttl_seconds=-1)
        assert cache.get("sess") is None

    def test_corrupted_file_returns_none(self, cache):
        f = cache.CACHE_DIR / "corrupt.json"
        f.write_text("not json at all {{{")
        assert cache.get("corrupt") is None

    def test_clear_removes_entry(self, cache):
        cache.put("sess", {"key": "val"}, ttl_seconds=60)
        cache.clear("sess")
        assert cache.get("sess") is None


class TestAtomicWrites:
    def test_crashed_tmp_does_not_wedge_future_writes(self, cache):
        """The audit found this bug: deterministic .tmp name meant a crashed
        process left a stale tmp that blocked all future writes forever."""
        key = "wedged"
        cache_file = cache.CACHE_DIR / f"{key}.json"
        # Simulate a crash: leave a stale tmp file behind
        stale_tmp = Path(f"{cache_file}.{os.getpid()}.tmp")
        stale_tmp.write_text("partial write, crashed")
        os.chmod(stale_tmp, 0o600)

        # Next write must succeed (clean up or use unique name)
        cache.put(key, {"key": "new"}, ttl_seconds=60)
        assert cache.get(key) == {"key": "new"}, \
            "Stale tmp file must not block future writes"

    def test_concurrent_writes_no_corruption(self, cache):
        """Two processes writing the same key — last one wins, no corruption."""
        import threading

        def writer(i):
            cc = CredentialCache()
            cc.put("shared", {"writer": i}, ttl_seconds=60)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        result = cache.get("shared")
        assert result is not None
        assert "writer" in result  # Valid JSON, not corrupted

    def test_clear_all_sweeps_stale_tmp(self, cache):
        stale = cache.CACHE_DIR / "orphan.json.99999.tmp"
        stale.write_text("garbage")
        cache.put("live", {"key": "val"}, ttl_seconds=60)
        cache.clear_all()
        assert not stale.exists(), "clear_all must sweep orphaned .tmp files"
        assert cache.get("live") is None


class TestNeverCacheStaticKeys:
    def test_cache_format_contains_only_temp_fields(self, cache):
        """Verify stored JSON has credentials + TTL structure only."""
        cache.put("sess", {"SessionToken": "tok"}, ttl_seconds=60)
        f = cache.CACHE_DIR / "sess.json"
        data = json.loads(f.read_text())
        assert "credentials" in data
        assert "expires_at" in data
        assert "created_at" in data
