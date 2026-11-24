# -*- coding: utf-8 -*-
"""macOS key-source layer (Phase 0 of the Mac helper project).

Public surface:

* :mod:`contract`   — helper output contract, key masking, error codes
* :mod:`providers`  — pluggable providers (currently: user-supplied helper)
* :mod:`adapter`    — strategy adapter producing ``{salt: 64hex}``
* :mod:`diagnostics`— read-only environment snapshot for the setup wizard

Deliberately free of Win32 / Flask imports. See
``docs/superpowers/specs/2026-11-24-mac-key-helper-design.md``.
"""
from .contract import (  # noqa: F401
    KeyCandidate,
    ProviderResult,
    mask_key,
    parse_helper_output,
)
from .adapter import extract_keys_via_mac_provider  # noqa: F401

__all__ = [
    "KeyCandidate",
    "ProviderResult",
    "mask_key",
    "parse_helper_output",
    "extract_keys_via_mac_provider",
]
