"""SSL verification for httpx (Windows cert store + certifi fallback)."""

from __future__ import annotations

import ssl

import certifi

_truststore_injected = False


def _inject_truststore() -> bool:
    global _truststore_injected
    if _truststore_injected:
        return True
    try:
        import truststore

        truststore.inject_into_ssl()
        _truststore_injected = True
        return True
    except ImportError:
        return False


def ssl_verify() -> bool | str:
    if _inject_truststore():
        return True
    return certifi.where()


def default_ssl_context() -> ssl.SSLContext:
    _inject_truststore()
    return ssl.create_default_context()
