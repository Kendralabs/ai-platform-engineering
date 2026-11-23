# Copyright 2026 CNOE
# SPDX-License-Identifier: Apache-2.0

"""
Thin typed wrapper around SigNoz query-service's HTTP API.

*** VERIFY BEFORE PRODUCTION USE ***
The endpoint paths and payload shapes below (`/api/v1/health`,
`/api/v1/services`, `/api/v3/query_range`) are written against SigNoz's
*documented* v3/v4 query-range API shape, as best-effort - this server has
never been pointed at a live SigNoz query-service instance (see
`charts/observability/values.yaml` in the infra repo for the target:
query-service on port 8080, in the `observability` namespace). Treat every
request/response shape here as unverified until it has been exercised
against a real deployment. Do not trust this module's output in production
without first confirming the actual API contract.

Same error-return convention as other agents' API wrappers (e.g.
argocd/tools/api_v1_applications.py's `make_api_request`): on any failure
this module returns a plain dict shaped like `{"error": "..."}` rather than
raising, so a calling MCP tool can hand the error straight back to the
caller without a try/except at every call site.
"""

import logging
import os
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)

HTTP_TIMEOUT = float(os.getenv("OBSERVABILITY_OPS_HTTP_TIMEOUT", "30"))


def _base_url() -> Optional[str]:
    url = os.getenv("SIGNOZ_QUERY_SERVICE_URL")
    return url.rstrip("/") if url else None


async def _get(path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    base_url = _base_url()
    if not base_url:
        return {"error": "SIGNOZ_QUERY_SERVICE_URL is not configured"}

    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            response = await client.get(f"{base_url}{path}", params=params)
            response.raise_for_status()
            return {"data": response.json()}
    except httpx.HTTPStatusError as e:
        logger.error(f"SigNoz query-service GET {path} failed: {e}")
        return {"error": f"SigNoz query-service returned {e.response.status_code}: {e.response.text}"}
    except httpx.HTTPError as e:
        logger.error(f"SigNoz query-service GET {path} failed: {e}")
        return {"error": f"SigNoz query-service request failed: {e}"}


async def _post(path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    base_url = _base_url()
    if not base_url:
        return {"error": "SIGNOZ_QUERY_SERVICE_URL is not configured"}

    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            response = await client.post(f"{base_url}{path}", json=payload)
            response.raise_for_status()
            return {"data": response.json()}
    except httpx.HTTPStatusError as e:
        logger.error(f"SigNoz query-service POST {path} failed: {e}")
        return {"error": f"SigNoz query-service returned {e.response.status_code}: {e.response.text}"}
    except httpx.HTTPError as e:
        logger.error(f"SigNoz query-service POST {path} failed: {e}")
        return {"error": f"SigNoz query-service request failed: {e}"}


async def get_service_health() -> Dict[str, Any]:
    """
    Hit query-service's health endpoint and the services list endpoint,
    returning both. Best-effort - see module docstring.
    """
    health = await _get("/api/v1/health")
    if "error" in health:
        return health

    services = await _get("/api/v1/services")
    return {
        "health": health.get("data"),
        "services": services.get("data") if "error" not in services else None,
        "services_error": services.get("error"),
    }


def _lookback_window_ms(lookback_minutes: int) -> Dict[str, int]:
    import time

    end_ms = int(time.time() * 1000)
    start_ms = end_ms - (lookback_minutes * 60 * 1000)
    return {"start": start_ms, "end": end_ms}


async def query_traces(service_name: str, lookback_minutes: int = 60, limit: int = 20) -> Dict[str, Any]:
    """
    Query recent traces for a service via query-service's v3 query_range
    API. Best-effort payload shape - see module docstring.

    Args:
        service_name: The service name as reported by `get_service_health`.
        lookback_minutes: How far back to look, in minutes.
        limit: Max number of trace results to return.
    """
    window = _lookback_window_ms(lookback_minutes)
    payload = {
        "start": window["start"],
        "end": window["end"],
        "compositeQuery": {
            "queryType": "traces",
            "panelType": "list",
            "builderQueries": {
                "A": {
                    "dataSource": "traces",
                    "queryName": "A",
                    "filters": {
                        "op": "AND",
                        "items": [{"key": {"key": "serviceName"}, "op": "=", "value": service_name}],
                    },
                    "limit": limit,
                }
            },
        },
    }
    return await _post("/api/v3/query_range", payload)


async def query_logs(
    service_name: str,
    lookback_minutes: int = 60,
    limit: int = 50,
    query_filter: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Query recent logs for a service via query-service's v3 query_range API.
    Best-effort payload shape - see module docstring.

    Args:
        service_name: The service name to filter logs by.
        lookback_minutes: How far back to look, in minutes.
        limit: Max number of log lines to return.
        query_filter: Optional free-text filter passed through to
            query-service as an additional "contains" filter on the log
            body. Never built into a raw SQL/shell string - query-service
            itself turns this structured filter object into its own
            ClickHouse query.
    """
    window = _lookback_window_ms(lookback_minutes)
    filter_items = [{"key": {"key": "service.name"}, "op": "=", "value": service_name}]
    if query_filter:
        filter_items.append({"key": {"key": "body"}, "op": "contains", "value": query_filter})

    payload = {
        "start": window["start"],
        "end": window["end"],
        "compositeQuery": {
            "queryType": "logs",
            "panelType": "list",
            "builderQueries": {
                "A": {
                    "dataSource": "logs",
                    "queryName": "A",
                    "filters": {"op": "AND", "items": filter_items},
                    "limit": limit,
                }
            },
        },
    }
    return await _post("/api/v3/query_range", payload)
