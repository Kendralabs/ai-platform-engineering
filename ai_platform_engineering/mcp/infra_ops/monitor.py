# Copyright 2026 CNOE
# SPDX-License-Identifier: Apache-2.0

"""
Infra Ops health-check loop.

Alert-only: polls the same tools exposed over MCP (tools/health.py) on an
interval and posts a webhook message when a threshold is crossed. Never
takes remediation action itself - that stays a human (or an explicit
infra_container_action call) in the loop.

Detects three signatures:
  - disk usage above DISK_THRESHOLD_PERCENT
  - 1-minute load average above LOAD_THRESHOLD
  - a container whose reported uptime stays below one poll interval across
    CRASH_LOOP_CONSECUTIVE_CHECKS consecutive polls (i.e. it keeps
    restarting faster than we're polling)

Each alert key has its own cooldown so a sustained condition doesn't spam
the webhook on every poll.
"""

import asyncio
import logging
import os
import re
import time
from typing import Dict, Optional

import httpx
from dotenv import load_dotenv

from tools import health

logger = logging.getLogger(__name__)

CHECK_INTERVAL_SECONDS = int(os.getenv("INFRA_OPS_CHECK_INTERVAL_SECONDS", "60"))
DISK_THRESHOLD_PERCENT = int(os.getenv("INFRA_OPS_DISK_THRESHOLD_PERCENT", "90"))
LOAD_THRESHOLD = float(os.getenv("INFRA_OPS_LOAD_THRESHOLD", "6.0"))
CRASH_LOOP_CONSECUTIVE_CHECKS = int(os.getenv("INFRA_OPS_CRASH_LOOP_CHECKS", "3"))
ALERT_COOLDOWN_SECONDS = int(os.getenv("INFRA_OPS_ALERT_COOLDOWN_SECONDS", "1800"))
ALERT_WEBHOOK_URL = os.getenv("INFRA_OPS_ALERT_WEBHOOK_URL", "")

_DISK_USE_REGEX = re.compile(r"(\d+)%")
_LOAD_AVG_REGEX = re.compile(r"load average:\s*([\d.]+)")
_UPTIME_SECONDS_REGEX = re.compile(r"Up (?:Less than a )?(\d+)?\s*(second|minute|hour|day)")

_UNIT_SECONDS = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}

# name -> consecutive short-uptime poll count
_crash_loop_streak: Dict[str, int] = {}
# alert key -> last time it fired
_last_alert_at: Dict[str, float] = {}


def _parse_disk_percent(df_stdout: str) -> Optional[int]:
    match = _DISK_USE_REGEX.search(df_stdout)
    return int(match.group(1)) if match else None


def _parse_load1(uptime_stdout: str) -> Optional[float]:
    match = _LOAD_AVG_REGEX.search(uptime_stdout)
    return float(match.group(1)) if match else None


def _parse_uptime_seconds(status_field: str) -> Optional[int]:
    match = _UPTIME_SECONDS_REGEX.search(status_field)
    if not match:
        return None
    count = int(match.group(1)) if match.group(1) else 1
    return count * _UNIT_SECONDS[match.group(2)]


async def _send_alert(key: str, message: str) -> None:
    now = time.monotonic()
    last = _last_alert_at.get(key, 0.0)
    if now - last < ALERT_COOLDOWN_SECONDS:
        logger.info("infra-ops monitor: suppressing alert (cooldown active): %s", key)
        return
    _last_alert_at[key] = now

    logger.warning("infra-ops monitor ALERT: %s", message)

    if not ALERT_WEBHOOK_URL:
        logger.warning("INFRA_OPS_ALERT_WEBHOOK_URL not set - alert logged only, not delivered")
        return

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(ALERT_WEBHOOK_URL, json={"text": message})
    except Exception as e:
        logger.error("infra-ops monitor: failed to deliver alert webhook: %s", e)


async def _check_once() -> None:
    health_result = await health.infra_health()

    disk_stdout = health_result.get("disk", {}).get("stdout", "")
    disk_percent = _parse_disk_percent(disk_stdout)
    if disk_percent is not None and disk_percent >= DISK_THRESHOLD_PERCENT:
        await _send_alert(
            "disk_threshold",
            f"[infra-ops] Disk usage at {disk_percent}% (threshold {DISK_THRESHOLD_PERCENT}%)",
        )

    uptime_stdout = health_result.get("uptime", {}).get("stdout", "")
    load1 = _parse_load1(uptime_stdout)
    if load1 is not None and load1 >= LOAD_THRESHOLD:
        await _send_alert(
            "load_threshold",
            f"[infra-ops] 1-minute load average at {load1} (threshold {LOAD_THRESHOLD})",
        )

    containers_result = await health.infra_list_containers()
    seen_this_poll = set()
    if containers_result.get("success"):
        for line in containers_result["stdout"].splitlines():
            fields = line.split("\t")
            if len(fields) < 2:
                continue
            name, status = fields[0], fields[1]
            seen_this_poll.add(name)

            uptime_seconds = _parse_uptime_seconds(status)
            is_short_lived = uptime_seconds is not None and uptime_seconds < CHECK_INTERVAL_SECONDS

            if is_short_lived:
                _crash_loop_streak[name] = _crash_loop_streak.get(name, 0) + 1
            else:
                _crash_loop_streak[name] = 0

            if _crash_loop_streak[name] >= CRASH_LOOP_CONSECUTIVE_CHECKS:
                await _send_alert(
                    f"crash_loop:{name}",
                    f"[infra-ops] Container '{name}' looks like it's crash-looping "
                    f"(status: {status!r} across {_crash_loop_streak[name]} consecutive checks)",
                )

    # Drop streak-tracking for containers that no longer exist.
    for stale_name in list(_crash_loop_streak):
        if stale_name not in seen_this_poll:
            del _crash_loop_streak[stale_name]


async def run_forever() -> None:
    logger.info(
        "infra-ops monitor starting: interval=%ss disk_threshold=%s%% load_threshold=%s "
        "crash_loop_checks=%s webhook_configured=%s",
        CHECK_INTERVAL_SECONDS, DISK_THRESHOLD_PERCENT, LOAD_THRESHOLD,
        CRASH_LOOP_CONSECUTIVE_CHECKS, bool(ALERT_WEBHOOK_URL),
    )
    while True:
        try:
            await _check_once()
        except Exception as e:
            logger.error("infra-ops monitor: check failed: %s", e, exc_info=True)
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


def main() -> None:
    load_dotenv()
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_forever())


if __name__ == "__main__":
    main()
