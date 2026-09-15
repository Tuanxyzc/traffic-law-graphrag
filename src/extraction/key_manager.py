"""Thread-safe API Key Manager with round-robin rotation and 429 quota backoff."""

from __future__ import annotations

import logging
import os
import threading
import time

logger = logging.getLogger(__name__)


def mask_key(key: str) -> str:
    """Masks an API key for safe logging."""
    if not key or len(key) <= 8:
        return "***"
    return f"{key[:4]}...{key[-4:]}"


class KeyManager:
    """Manages a pool of API keys, automatically rotating when rate limits are hit."""

    def __init__(
        self,
        api_keys: list[str] | None = None,
        default_cooldown: float = 60.0,
    ) -> None:
        self.default_cooldown = default_cooldown
        self._lock = threading.Lock()
        self._current_index = 0
        self._cooldowns: dict[str, float] = {}

        if api_keys is not None:
            self._keys = [k.strip() for k in api_keys if k and k.strip()]
        else:
            self._keys = self._load_keys_from_env()

        if not self._keys:
            logger.warning(
                "No Gemini API keys found in environment. Set GEMINI_API_KEYS in .env."
            )

    def _load_keys_from_env(self) -> list[str]:
        keys: list[str] = []
        raw_keys = os.getenv("GEMINI_API_KEYS", "")
        if raw_keys:
            keys.extend([k.strip() for k in raw_keys.split(",") if k.strip()])

        single_key = os.getenv("GEMINI_API_KEY", "").strip()
        if single_key and single_key not in keys:
            keys.append(single_key)

        return keys

    @property
    def key_count(self) -> int:
        with self._lock:
            return len(self._keys)

    def get_key(self, max_wait: float = 120.0) -> str:
        """Retrieves the next available API key not currently in cooldown."""
        with self._lock:
            if not self._keys:
                raise ValueError("No API keys available in KeyManager pool.")

            now = time.time()
            total = len(self._keys)

            # 1. Try to find a key that is not in cooldown starting from current_index
            for i in range(total):
                idx = (self._current_index + i) % total
                candidate = self._keys[idx]
                cooldown_until = self._cooldowns.get(candidate, 0.0)
                if now >= cooldown_until:
                    self._current_index = idx
                    return candidate

            # 2. If all keys are on cooldown, find the one that expires earliest
            earliest_key = min(self._keys, key=lambda k: self._cooldowns.get(k, 0.0))
            wait_time = self._cooldowns[earliest_key] - now

        if wait_time > max_wait:
            raise TimeoutError(
                f"All API keys are exhausted. Minimum wait time {wait_time:.1f}s exceeds limit {max_wait}s."
            )

        if wait_time > 0:
            logger.info(
                "All %d API keys in cooldown. Waiting %.1fs for key %s to cool down...",
                total,
                wait_time,
                mask_key(earliest_key),
            )
            time.sleep(wait_time)

        with self._lock:
            self._current_index = self._keys.index(earliest_key)
            return earliest_key

    def mark_rate_limited(self, key: str, cooldown_seconds: float | None = None) -> str:
        """Marks a key as rate-limited (HTTP 429), applies cooldown, and switches to next key."""
        cd = cooldown_seconds if cooldown_seconds is not None else self.default_cooldown
        with self._lock:
            now = time.time()
            self._cooldowns[key] = now + cd
            masked = mask_key(key)
            logger.warning(
                "API Key %s reached quota limit (HTTP 429). Put on cooldown for %.0fs.",
                masked,
                cd,
            )

            # Advance index
            if self._keys:
                self._current_index = (self._current_index + 1) % len(self._keys)

        return self.get_key()
