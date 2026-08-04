"""Residential / rotating gateways (Loma и аналоги): дольше SMTP, меньше параллели."""

from __future__ import annotations

import os

from models import Proxy

_RESIDENTIAL_HOST_MARKERS = tuple(
    m.strip().lower()
    for m in (os.getenv("RESIDENTIAL_PROXY_HOST_MARKERS") or "lomaproxy,lunaproxy,922proxy,iproyal,smartproxy").split(",")
    if m.strip()
)


def is_residential_gateway(proxy: Proxy | None) -> bool:
    if not proxy:
        return False
    h = (getattr(proxy, "host", None) or "").strip().lower()
    if not h:
        return False
    return any(m in h for m in _RESIDENTIAL_HOST_MARKERS)


def residential_smtp_timeout_sec() -> int:
    return max(45, min(120, int(os.getenv("RESIDENTIAL_SMTP_TIMEOUT_SEC", "75"))))


def residential_burst_inflight() -> int:
    return max(1, min(12, int(os.getenv("RESIDENTIAL_BURST_INFLIGHT", "4"))))
