# Copyright 2026 CNOE
# SPDX-License-Identifier: Apache-2.0

"""
Tier 1 - read-only MCP tools for the platform's observability stack
(SigNoz query-service + the dedicated "signoz" ClickHouse database). Thin
wrappers over tools/signoz_client.py and tools/clickhouse_client.py - no
tool in this file ever builds a raw SQL/HTTP-query string from caller
input; both client modules already enforce fixed, parameterized query
shapes (see clickhouse_client.py's module docstring).

See signoz_client.py's module docstring: the SigNoz query-service API
shapes used here are best-effort/unverified against a live instance.
"""

from typing import Any, Dict, Optional

from . import clickhouse_client, signoz_client


async def observability_get_service_health() -> Dict[str, Any]:
    """
    Get SigNoz query-service's reported health and the list of services it
    currently sees telemetry from. Use this first to find valid
    `service_name` values for observability_query_traces/_logs.
    """
    return await signoz_client.get_service_health()


async def observability_query_traces(service_name: str, lookback_minutes: int = 60, limit: int = 20) -> Dict[str, Any]:
    """
    Query recent traces for a service from SigNoz.

    Args:
        service_name: The service name as reported by observability_get_service_health.
        lookback_minutes: How far back to look, in minutes (default 60).
        limit: Max number of trace results to return (default 20).
    """
    return await signoz_client.query_traces(service_name, lookback_minutes=lookback_minutes, limit=limit)


async def observability_query_logs(
    service_name: str,
    lookback_minutes: int = 60,
    limit: int = 50,
    query_filter: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Query recent logs for a service from SigNoz.

    Args:
        service_name: The service name to filter logs by.
        lookback_minutes: How far back to look, in minutes (default 60).
        limit: Max number of log lines to return (default 50).
        query_filter: Optional free-text filter, matched against the log
            body as a "contains" filter by query-service itself - never
            interpolated into a raw query string by this tool.
    """
    return await signoz_client.query_logs(
        service_name,
        lookback_minutes=lookback_minutes,
        limit=limit,
        query_filter=query_filter,
    )


async def observability_query_metrics(metric_name: str, lookback_minutes: int = 60) -> Dict[str, Any]:
    """
    Get a summary (count, min, max, avg) of a metric's sample values from
    the signoz ClickHouse database over a lookback window. Uses a single
    fixed, parameterized query template - see
    clickhouse_client.query_metrics_summary's docstring.

    Args:
        metric_name: The metric name to summarize.
        lookback_minutes: How far back to look, in minutes (default 60).
    """
    return await clickhouse_client.query_metrics_summary(metric_name, lookback_minutes=lookback_minutes)
