"""Thread-safe Multi-Provider API Key Manager with round-robin rotation, 429 quota backoff, and cross-provider failover."""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


def mask_key(key: str) -> str:
    """Masks an API key for safe logging."""
    if not key or len(key) <= 8:
        return "***"
    return f"{key[:4]}...{key[-4:]}"


@dataclass(frozen=True)
class ProviderKey:
    """Represents an active API key with its provider metadata."""

    provider: str  # "gemini", "groq", "cerebras", "cohere"
    key: str
    api_type: str  # "gemini" or "openai"
    endpoint: str
    model: str


PROVIDER_DEFAULTS: dict[str, dict[str, Any]] = {
    "gemini": {
        "api_type": "gemini",
        "endpoint": "https://generativelanguage.googleapis.com/v1beta",
        "default_generate_model": "gemini-2.5-flash",
        "default_rewrite_model": "gemini-2.5-flash",
        "env_keys_var": "GEMINI_API_KEYS",
        "env_key_var": "GEMINI_API_KEY",
    },
    "groq": {
        "api_type": "openai",
        "endpoint": "https://api.groq.com/openai/v1",
        "default_generate_model": "qwen/qwen3.8-27b",
        "default_rewrite_model": "qwen/qwen3.8-27b",
        "env_keys_var": "GROQ_API_KEYS",
        "env_key_var": "GROQ_API_KEY",
    },
    "cerebras": {
        "api_type": "openai",
        "endpoint": "https://api.cerebras.ai/v1",
        "default_generate_model": "qwen-3.8-27b",
        "default_rewrite_model": "qwen-3.8-27b",
        "env_keys_var": "CEREBRAS_API_KEYS",
        "env_key_var": "CEREBRAS_API_KEY",
    },
    "cohere": {
        "api_type": "openai",
        "endpoint": "https://api.cohere.ai/compatibility/v1",
        "default_generate_model": "command-r-08-2024",
        "default_rewrite_model": "command-r-08-2024",
        "env_keys_var": "COHERE_API_KEYS",
        "env_key_var": "COHERE_API_KEY",
    },
}

DEFAULT_PROVIDER_ORDER: list[str] = ["gemini", "groq", "cerebras", "cohere"]


class KeyManager:
    """Manages pools of API keys across multiple LLM providers (Gemini, Groq, Cerebras, Cohere).

    Features:
    - Intra-provider round-robin key rotation when rate-limited (HTTP 429) or server error (HTTP 5xx).
    - Cross-provider failover: when ALL keys of a provider are on cooldown, automatically fails over to the next provider.
    - Full backward compatibility with legacy single-provider (Gemini) KeyManager usage.
    """

    def __init__(
        self,
        api_keys: list[str] | dict[str, list[str]] | None = None,
        default_cooldown: float = 60.0,
        provider_order: list[str] | tuple[str, ...] | None = None,
        provider_models: dict[str, str] | None = None,
        provider_endpoints: dict[str, str] | None = None,
    ) -> None:
        self.default_cooldown = default_cooldown
        self._lock = threading.Lock()
        self._cooldowns: dict[tuple[str, str], float] = {}
        self._provider_models: dict[str, str] = provider_models or {}
        self._provider_endpoints: dict[str, str] = provider_endpoints or {}

        # 1. Determine key pools per provider
        self._providers_keys: dict[str, list[str]] = {}
        if isinstance(api_keys, dict):
            for p, keys in api_keys.items():
                clean_keys = [k.strip() for k in keys if k and k.strip()]
                if clean_keys:
                    self._providers_keys[p.lower()] = clean_keys
        elif isinstance(api_keys, list):
            # Backward compatibility: single list of keys defaults to gemini provider
            clean_keys = [k.strip() for k in api_keys if k and k.strip()]
            if clean_keys:
                self._providers_keys["gemini"] = clean_keys
        else:
            self._providers_keys = self._load_keys_from_env()

        # 2. Determine provider order and active providers
        if provider_order:
            raw_order = list(provider_order)
        elif isinstance(api_keys, dict):
            raw_order = list(api_keys.keys())
        else:
            raw_order = self._load_order_from_env()
        # Keep only providers that actually have configured keys
        self._active_providers: list[str] = [
            p.lower() for p in raw_order if p.lower() in self._providers_keys
        ]
        # Include any remaining providers that have keys but were omitted from order
        for p in self._providers_keys:
            if p not in self._active_providers:
                self._active_providers.append(p)

        self._current_provider_index = 0
        self._current_key_indices: dict[str, int] = {
            p: 0 for p in self._providers_keys
        }

        if not self._active_providers:
            logger.warning(
                "No LLM API keys found across any providers (Gemini, Groq, Cerebras, Cohere). "
                "Set GEMINI_API_KEYS, GROQ_API_KEYS, CEREBRAS_API_KEYS, or COHERE_API_KEYS in .env."
            )

    def _load_keys_from_env(self) -> dict[str, list[str]]:
        """Loads API keys from environment variables for all supported providers."""
        pools: dict[str, list[str]] = {}
        for provider, config in PROVIDER_DEFAULTS.items():
            keys: list[str] = []
            raw_keys = os.getenv(config["env_keys_var"], "")
            if raw_keys:
                keys.extend([k.strip() for k in raw_keys.split(",") if k.strip()])

            single_key = os.getenv(config["env_key_var"], "").strip()
            if single_key and single_key not in keys:
                keys.append(single_key)

            if keys:
                pools[provider] = keys
        return pools

    def _load_order_from_env(self) -> list[str]:
        raw_order = os.getenv("LLM_PROVIDER_ORDER", "")
        if raw_order:
            parsed = [p.strip().lower() for p in raw_order.split(",") if p.strip()]
            if parsed:
                return parsed
        return list(DEFAULT_PROVIDER_ORDER)

    @property
    def active_provider(self) -> str:
        """Returns the currently active provider name."""
        with self._lock:
            if not self._active_providers:
                return "none"
            return self._active_providers[self._current_provider_index]

    @property
    def active_providers(self) -> list[str]:
        """Returns list of providers with available keys in priority order."""
        with self._lock:
            return list(self._active_providers)

    @property
    def key_count(self) -> int:
        """Total key count across all configured providers."""
        with self._lock:
            return sum(len(keys) for keys in self._providers_keys.values())

    @property
    def _keys(self) -> list[str]:
        """Backward-compatibility property returning keys of currently active provider."""
        with self._lock:
            if not self._active_providers:
                return []
            curr_provider = self._active_providers[self._current_provider_index]
            return self._providers_keys.get(curr_provider, [])

    def _resolve_model(self, provider: str, purpose: str) -> str:
        """Resolves target model name for given provider and purpose."""
        env_override = os.getenv(f"{provider.upper()}_MODEL")
        if env_override:
            return env_override

        cfg_key = f"{provider}_{purpose}"
        if cfg_key in self._provider_models:
            return self._provider_models[cfg_key]
        if provider in self._provider_models:
            return self._provider_models[provider]

        defaults = PROVIDER_DEFAULTS.get(provider, {})
        if purpose == "rewrite":
            return str(defaults.get("default_rewrite_model", "gemini-2.5-flash"))
        return str(defaults.get("default_generate_model", "gemini-2.5-flash"))

    def _resolve_endpoint(self, provider: str) -> str:
        """Resolves endpoint URL for given provider."""
        env_override = os.getenv(f"{provider.upper()}_ENDPOINT")
        if env_override:
            return env_override
        if provider in self._provider_endpoints:
            return self._provider_endpoints[provider]
        defaults = PROVIDER_DEFAULTS.get(provider, {})
        return str(defaults.get("endpoint", ""))

    def get_provider_key(
        self,
        purpose: str = "generate",
        max_wait: float = 120.0,
    ) -> ProviderKey:
        """Retrieves next available key with provider metadata, performing inter-provider failover if needed."""
        with self._lock:
            if not self._active_providers:
                raise ValueError("No API keys available across any configured providers in KeyManager pool.")

            now = time.time()
            total_providers = len(self._active_providers)

            # 1. Check providers starting from current active provider
            for p_offset in range(total_providers):
                p_idx = (self._current_provider_index + p_offset) % total_providers
                provider = self._active_providers[p_idx]
                keys = self._providers_keys[provider]
                cur_k_idx = self._current_key_indices[provider]
                total_keys = len(keys)

                # Check if current provider has a key not in cooldown
                for k_offset in range(total_keys):
                    k_idx = (cur_k_idx + k_offset) % total_keys
                    candidate_key = keys[k_idx]
                    cooldown_until = self._cooldowns.get((provider, candidate_key), 0.0)
                    if now >= cooldown_until:
                        # If we had to switch to another provider because earlier ones exhausted
                        if p_idx != self._current_provider_index:
                            prev_provider = self._active_providers[self._current_provider_index]
                            logger.warning(
                                "All keys for provider '%s' are on cooldown. Failing over to provider '%s'.",
                                prev_provider,
                                provider,
                            )
                            self._current_provider_index = p_idx

                        self._current_key_indices[provider] = k_idx
                        api_type = PROVIDER_DEFAULTS.get(provider, {}).get("api_type", "openai")
                        endpoint = self._resolve_endpoint(provider)
                        model = self._resolve_model(provider, purpose=purpose)

                        return ProviderKey(
                            provider=provider,
                            key=candidate_key,
                            api_type=api_type,
                            endpoint=endpoint,
                            model=model,
                        )

            # 2. If all keys across all providers are on cooldown, find the earliest expiring key
            earliest_provider: str | None = None
            earliest_key: str | None = None
            earliest_time = float("inf")

            for prov, k_list in self._providers_keys.items():
                for k in k_list:
                    cd = self._cooldowns.get((prov, k), 0.0)
                    if cd < earliest_time:
                        earliest_time = cd
                        earliest_provider = prov
                        earliest_key = k

            if earliest_provider is None or earliest_key is None:
                raise ValueError("No keys available in KeyManager pool.")

            wait_time = earliest_time - now

        if wait_time > max_wait:
            raise TimeoutError(
                f"All API keys across all providers are exhausted. "
                f"Minimum wait time {wait_time:.1f}s exceeds limit {max_wait}s."
            )

        if wait_time > 0:
            logger.info(
                "All keys in cooldown across providers. Waiting %.1fs for provider '%s' (key %s)...",
                wait_time,
                earliest_provider,
                mask_key(earliest_key),
            )
            time.sleep(wait_time)

        with self._lock:
            self._current_provider_index = self._active_providers.index(earliest_provider)
            self._current_key_indices[earliest_provider] = self._providers_keys[earliest_provider].index(earliest_key)
            api_type = PROVIDER_DEFAULTS.get(earliest_provider, {}).get("api_type", "openai")
            endpoint = self._resolve_endpoint(earliest_provider)
            model = self._resolve_model(earliest_provider, purpose=purpose)

            return ProviderKey(
                provider=earliest_provider,
                key=earliest_key,
                api_type=api_type,
                endpoint=endpoint,
                model=model,
            )

    def get_key(self, max_wait: float = 120.0) -> str:
        """Backward-compatibility: retrieves the next available API key string."""
        return self.get_provider_key(max_wait=max_wait).key

    def _find_provider_for_key(self, key: str, explicit_provider: str | None = None) -> str:
        if explicit_provider and explicit_provider in self._providers_keys:
            return explicit_provider
        for p, keys in self._providers_keys.items():
            if key in keys:
                return p
        if self._active_providers:
            return self._active_providers[self._current_provider_index]
        return "gemini"

    def mark_rate_limited(
        self,
        key: str,
        cooldown_seconds: float | None = None,
        provider: str | None = None,
    ) -> str:
        """Marks a key as rate-limited (HTTP 429), applies cooldown, and advances to next key or provider."""
        cd = cooldown_seconds if cooldown_seconds is not None else self.default_cooldown
        with self._lock:
            prov = self._find_provider_for_key(key, explicit_provider=provider)
            now = time.time()
            self._cooldowns[(prov, key)] = now + cd
            masked = mask_key(key)
            logger.warning(
                "Provider '%s' API Key %s reached quota limit (HTTP 429). Put on cooldown for %.0fs.",
                prov,
                masked,
                cd,
            )

            # Advance index for this provider
            if self._providers_keys.get(prov):
                self._current_key_indices[prov] = (
                    self._current_key_indices[prov] + 1
                ) % len(self._providers_keys[prov])

        return self.get_key()

    def mark_server_error(
        self,
        key: str,
        cooldown_seconds: float = 15.0,
        provider: str | None = None,
    ) -> str:
        """Marks a key as encountering server error (HTTP 5xx), applies short cooldown, and advances key."""
        with self._lock:
            prov = self._find_provider_for_key(key, explicit_provider=provider)
            now = time.time()
            self._cooldowns[(prov, key)] = now + cooldown_seconds
            masked = mask_key(key)
            logger.warning(
                "Provider '%s' API Key %s encountered server error (HTTP 5xx). Put on short cooldown for %.0fs.",
                prov,
                masked,
                cooldown_seconds,
            )

            # Advance index for this provider
            if self._providers_keys.get(prov):
                self._current_key_indices[prov] = (
                    self._current_key_indices[prov] + 1
                ) % len(self._providers_keys[prov])

        return self.get_key()
