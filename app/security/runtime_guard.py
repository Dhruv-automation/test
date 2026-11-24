"""Security version checks for features that handle external credentials."""

from __future__ import annotations

import sys


# These floors include the October 2026 security fixes published by python.org.
_MINIMUM_PATCH_BY_MINOR = {
    (3, 12): 16,
    (3, 13): 18,
    (3, 14): 10,
    (3, 15): 2,
}


def secure_runtime_issue(version: tuple[int, int, int] | None = None) -> str | None:
    """Return a remediation message when Python is below a patched build."""
    current = version or tuple(sys.version_info[:3])
    major, minor, patch = current
    minimum_patch = _MINIMUM_PATCH_BY_MINOR.get((major, minor))
    if minimum_patch is None or patch < minimum_patch:
        return (
            "Instagram OAuth is disabled on this Python build. Install a security-patched "
            "Python 3.12.16+, 3.13.18+, 3.14.10+, or 3.15.2+ runtime."
        )
    return None


def oauth_runtime_issue(version: tuple[int, int, int] | None = None) -> str | None:
    """Backward-compatible name for the OAuth runtime guard."""
    return secure_runtime_issue(version)
