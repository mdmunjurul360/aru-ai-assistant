"""Environment string parsing utilities for V4 configuration."""

from __future__ import annotations

import re
from typing import Any, Mapping


def parse_api_keys(
    plural_val: str | None = None,
    singular_val: str | None = None,
) -> list[str]:
    """
    Parse and merge API keys from plural and singular environment variables.
    Supports comma, semicolon, and newline separation.
    Strips whitespace and quotes, ignores empty tokens, and removes duplicates preserving order.
    """
    raw_tokens: list[str] = []
    # Process singular first so primary key retains index 0 if both exist
    for source in (singular_val, plural_val):
        if not source:
            continue
        tokens = re.split(r"[,;\n\r]+", str(source))
        for token in tokens:
            cleaned = token.strip().strip("'\"").strip()
            if cleaned:
                raw_tokens.append(cleaned)

    seen: set[str] = set()
    result: list[str] = []
    for key in raw_tokens:
        if key not in seen:
            seen.add(key)
            result.append(key)
    return result


def parse_cloudflare_credentials(
    env_source: Mapping[str, Any],
) -> list[dict[str, str]]:
    """
    Parse paired Cloudflare account credentials from environment mapping.
    Supports:
      - Primary account: CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_API_KEY (or _1)
      - Numbered variables: CLOUDFLARE_ACCOUNT_ID_2, CLOUDFLARE_API_KEY_2, etc.
      - Delimited account pairs: CLOUDFLARE_ACCOUNTS="acc1:key1,acc2:key2"
    """
    accounts: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add_pair(acc: str | None, key: str | None) -> None:
        c_acc = (acc or "").strip().strip("'\"").strip()
        c_key = (key or "").strip().strip("'\"").strip()
        if c_acc and c_key and (c_acc, c_key) not in seen:
            seen.add((c_acc, c_key))
            accounts.append({"account_id": c_acc, "api_key": c_key})

    # 1. Primary account
    acc_1 = env_source.get("CLOUDFLARE_ACCOUNT_ID") or env_source.get("CLOUDFLARE_ACCOUNT_ID_1") or ""
    key_1 = env_source.get("CLOUDFLARE_API_KEY") or env_source.get("CLOUDFLARE_API_KEY_1") or ""
    keys_1_plural = parse_api_keys(env_source.get("CLOUDFLARE_API_KEYS"), key_1)
    if acc_1:
        if keys_1_plural:
            for k in keys_1_plural:
                add_pair(acc_1, k)
        elif key_1:
            add_pair(acc_1, key_1)

    # 2. Numbered accounts (_2, _3, ...)
    numbered_indices: set[int] = set()
    for k in env_source.keys():
        m = re.match(r"^CLOUDFLARE_ACCOUNT_ID_(\d+)$", k, re.IGNORECASE)
        if m:
            numbered_indices.add(int(m.group(1)))
        m2 = re.match(r"^CLOUDFLARE_API_KEY_(\d+)$", k, re.IGNORECASE)
        if m2:
            numbered_indices.add(int(m2.group(1)))
        m3 = re.match(r"^CLOUDFLARE_API_KEYS_(\d+)$", k, re.IGNORECASE)
        if m3:
            numbered_indices.add(int(m3.group(1)))

    for idx in sorted(numbered_indices):
        if idx == 1:
            continue
        acc_n = env_source.get(f"CLOUDFLARE_ACCOUNT_ID_{idx}") or ""
        key_n = env_source.get(f"CLOUDFLARE_API_KEY_{idx}") or ""
        keys_n_plural = parse_api_keys(env_source.get(f"CLOUDFLARE_API_KEYS_{idx}"), key_n)
        if acc_n:
            if keys_n_plural:
                for k in keys_n_plural:
                    add_pair(acc_n, k)
            elif key_n:
                add_pair(acc_n, key_n)

    # 3. Delimited CLOUDFLARE_ACCOUNTS
    raw_accounts = env_source.get("CLOUDFLARE_ACCOUNTS") or ""
    if raw_accounts:
        for item in re.split(r"[,;\n\r]+", str(raw_accounts)):
            item = item.strip()
            if ":" in item:
                parts = item.split(":", 1)
                add_pair(parts[0], parts[1])

    return accounts
