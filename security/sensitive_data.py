from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


class SensitiveDataPolicy:
    """
    Central runtime policy for credential-like data.

    Responsibilities:

    1. block filesystem paths that are likely to contain credentials;
    2. redact secret-looking values before tool observations, sessions,
       traces, or console output can expose them.

    The text rules are deliberately conservative so ordinary source
    code such as ``token = os.getenv("TOKEN")`` is not rewritten just
    because it contains a security-related variable name.

    This is defense in depth, not an operating-system sandbox.
    """

    REDACTED = "[REDACTED]"

    SENSITIVE_KEYS = {
        "api_key",
        "apikey",
        "authorization",
        "password",
        "passwd",
        "secret",
        "access_token",
        "refresh_token",
        "token",
        "client_secret",
        "private_key",
    }

    SENSITIVE_DIRECTORY_NAMES = {
        ".ssh",
        ".aws",
        ".gnupg",
    }

    SENSITIVE_EXACT_FILENAMES = {
        ".env",
        ".npmrc",
        ".pypirc",
        ".netrc",
        ".git-credentials",
        "credentials",
        "credentials.json",
        "id_rsa",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
    }

    SAFE_ENV_FILENAMES = {
        ".env.example",
        ".env.sample",
        ".env.template",
    }

    SENSITIVE_SUFFIXES = {
        ".pem",
        ".key",
        ".p12",
        ".pfx",
    }

    SAFE_PLACEHOLDER_VALUES = {
        "none",
        "null",
        "true",
        "false",
        "placeholder",
        "changeme",
        "change-me",
        "example",
        "your-key-here",
        "your-token-here",
    }

    # Environment-style assignments are intentionally strict:
    # no whitespace around '=' and only a simple literal value.
    # This catches common .env / `env` output without mangling source
    # expressions such as API_KEY = os.getenv("API_KEY").
    _ENV_ASSIGNMENT_PATTERN = re.compile(
        r"(?im)"
        r"(?P<prefix>\b[A-Z][A-Z0-9_]*"
        r"(?:API_KEY|ACCESS_TOKEN|REFRESH_TOKEN|PASSWORD|PASSWD|SECRET|TOKEN)"
        r"=)"
        r"(?P<quote>[\"']?)"
        r"(?P<value>[A-Za-z0-9._~+/=-]{4,})"
        r"(?P=quote)"
        r"(?=[ \t]*(?:$|[#;]))"
    )

    _BEARER_PATTERN = re.compile(
        r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}"
    )

    _KNOWN_TOKEN_PATTERNS = (
        re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
        re.compile(r"\bgithub_pat_[A-Za-z0-9_]{12,}\b"),
        re.compile(r"\bgh[pousr]_[A-Za-z0-9]{12,}\b"),
        re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
        re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"),
    )

    # ========================================================
    # Key detection
    # ========================================================

    @classmethod
    def is_sensitive_key(
        cls,
        key: str,
    ) -> bool:
        normalized = (
            key
            .strip()
            .lower()
            .replace("-", "_")
        )

        if normalized in cls.SENSITIVE_KEYS:
            return True

        for sensitive in cls.SENSITIVE_KEYS:
            if normalized.endswith(
                "_" + sensitive
            ):
                return True

        return False

    # ========================================================
    # Path policy
    # ========================================================

    @classmethod
    def is_sensitive_path(
        cls,
        path: str | Path,
    ) -> bool:
        raw = str(path).strip()

        if not raw:
            return False

        # Normalize separators explicitly so model-generated POSIX or
        # Windows-style paths are checked consistently.
        normalized = raw.replace("\\", "/")
        parts = [
            part.lower()
            for part in normalized.split("/")
            if part not in {"", ".", ".."}
        ]

        if not parts:
            return False

        if any(
            part in cls.SENSITIVE_DIRECTORY_NAMES
            for part in parts
        ):
            return True

        filename = parts[-1]

        if filename in cls.SAFE_ENV_FILENAMES:
            return False

        if filename == ".env" or filename.startswith(".env."):
            return True

        if filename in cls.SENSITIVE_EXACT_FILENAMES:
            return True

        if any(
            filename.endswith(suffix)
            for suffix in cls.SENSITIVE_SUFFIXES
        ):
            return True

        return False

    # ========================================================
    # Text redaction
    # ========================================================

    @classmethod
    def redact_text(
        cls,
        value: str,
    ) -> str:
        if not isinstance(value, str):
            raise TypeError("value must be a string.")

        # If the entire string is structured JSON, redact it by key.
        # This catches command output such as {"token": "..."} while
        # avoiding broad regex replacement across ordinary source code.
        structured = cls._redact_json_text(value)

        if structured is not None:
            return structured

        marker = "__CODING_AGENT_REDACTED_SECRET__"

        def replace_env_assignment(
            match: re.Match[str],
        ) -> str:
            secret_value = match.group("value")

            if (
                secret_value.lower()
                in cls.SAFE_PLACEHOLDER_VALUES
            ):
                return match.group(0)

            quote = match.group("quote")

            return (
                match.group("prefix")
                + quote
                + marker
                + quote
            )

        redacted = cls._ENV_ASSIGNMENT_PATTERN.sub(
            replace_env_assignment,
            value,
        )

        redacted = cls._BEARER_PATTERN.sub(
            "Bearer " + marker,
            redacted,
        )

        for pattern in cls._KNOWN_TOKEN_PATTERNS:
            redacted = pattern.sub(
                marker,
                redacted,
            )

        return redacted.replace(
            marker,
            cls.REDACTED,
        )

    @classmethod
    def _redact_json_text(
        cls,
        value: str,
    ) -> str | None:
        stripped = value.strip()

        if not stripped or stripped[0] not in "[{":
            return None

        try:
            parsed = json.loads(
                stripped
            )
        except json.JSONDecodeError:
            return None

        if not isinstance(
            parsed,
            (dict, list),
        ):
            return None

        sanitized = cls.redact_data(
            parsed
        )

        if sanitized == parsed:
            return value

        serialized = json.dumps(
            sanitized,
            ensure_ascii=False,
        )

        if value.endswith("\n"):
            serialized += "\n"

        return serialized

    # ========================================================
    # Recursive structured redaction
    # ========================================================

    @classmethod
    def redact_data(
        cls,
        value: Any,
        key: str | None = None,
    ) -> Any:
        if (
            key is not None
            and cls.is_sensitive_key(key)
        ):
            return cls.REDACTED

        if value is None:
            return None

        if isinstance(value, (bool, int, float)):
            return value

        if isinstance(value, str):
            return cls.redact_text(value)

        if isinstance(value, Path):
            return cls.redact_text(str(value))

        if isinstance(value, dict):
            return {
                str(item_key): cls.redact_data(
                    item_value,
                    key=str(item_key),
                )
                for item_key, item_value in value.items()
            }

        if isinstance(value, (list, tuple, set)):
            return [
                cls.redact_data(item)
                for item in value
            ]

        return cls.redact_text(str(value))
