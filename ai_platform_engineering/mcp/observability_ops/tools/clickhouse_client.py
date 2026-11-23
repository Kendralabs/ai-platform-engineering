# Copyright 2026 CNOE
# SPDX-License-Identifier: Apache-2.0

"""
Read-only ClickHouse client for the dedicated "signoz" database (see
`charts/observability/values.yaml` in the infra repo: host
`clickhouse.observability:9000`, database `signoz`, user `signoz`, password
in the Secret named by `clickhouseSecretName`).

Design principle (restated from jenkins_ci_ops/README.md's "agents should
never get raw shell/SQL passthrough"): this module exposes ONLY fixed,
parameterized query templates. It never accepts, builds, or executes a raw
SQL string from caller input. Every caller-supplied value (`metric_name`,
etc.) is passed through clickhouse-connect's `parameters=` binding, never
f-string/`.format()`-interpolated into the query text - that is the one
invariant this module exists to enforce, and it is covered by
tests/test_clickhouse_client.py.

Connection params come from CLICKHOUSE_HOST/CLICKHOUSE_PORT/
CLICKHOUSE_DATABASE/CLICKHOUSE_USER env vars. The password is resolved via
the same credential-exchange pattern as every other kendralabs-only agent
(see jenkins_ci_ops/tools/credential_client.py): CLICKHOUSE_PASSWORD_REF
when CAIPE_CREDENTIALS_ENABLED=true, or the CLICKHOUSE_PASSWORD env var
directly otherwise.
"""

import logging
import os
from typing import Any, Dict

import clickhouse_connect

from .credential_client import CredentialClientError, create_client_from_env, credentials_enabled

logger = logging.getLogger(__name__)

CLICKHOUSE_PASSWORD_REF = os.getenv("CLICKHOUSE_PASSWORD_REF", "observability-ops/clickhouse-password")

# Fixed table name allow-list for query_metrics_summary. Never built from
# caller input - metric_name is a WHERE-clause parameter, not a table or
# column name, so it can never cause a different table to be queried.
_METRICS_SAMPLES_TABLE = "signoz_metrics.distributed_samples_v4"


class ClickHouseConfigError(RuntimeError):
    """Raised when required ClickHouse config is missing or the connection fails."""


async def _resolve_password() -> str:
    if not credentials_enabled():
        password = os.getenv("CLICKHOUSE_PASSWORD")
        if not password:
            raise ClickHouseConfigError(
                "CAIPE_CREDENTIALS_ENABLED is false but CLICKHOUSE_PASSWORD is not set"
            )
        return password
    try:
        client = create_client_from_env()
        return await client.retrieve_secret(CLICKHOUSE_PASSWORD_REF)
    except CredentialClientError as e:
        raise ClickHouseConfigError(f"Failed to resolve CLICKHOUSE_PASSWORD via credential exchange: {e}") from e


def _get_client(password: str):
    host = os.getenv("CLICKHOUSE_HOST", "clickhouse.observability")
    port = int(os.getenv("CLICKHOUSE_PORT", "9000"))
    database = os.getenv("CLICKHOUSE_DATABASE", "signoz")
    user = os.getenv("CLICKHOUSE_USER", "signoz")
    # clickhouse-connect's native client talks the ClickHouse HTTP
    # interface; `port` here is kept as the native TCP port value from
    # values.yaml for operator familiarity, but clickhouse-connect itself
    # expects the HTTP interface port. Operators pointing this at a real
    # cluster should set CLICKHOUSE_PORT to that instance's HTTP port
    # (commonly 8123) - see README.md "Known gaps".
    return clickhouse_connect.get_client(
        host=host,
        port=port,
        username=user,
        password=password,
        database=database,
    )


async def query_metrics_summary(metric_name: str, lookback_minutes: int = 60) -> Dict[str, Any]:
    """
    Fixed-template-only query: returns a summary (count, min, max, avg) of
    sample values for one metric name over a lookback window, from
    ClickHouse's `signoz_metrics` database.

    This is the ONLY query shape this module supports. `metric_name` is
    always passed as a bound parameter (clickhouse-connect `parameters=`),
    never interpolated into the SQL text, so no caller input can change
    the query's shape or target table - see module docstring.

    Args:
        metric_name: The metric name to summarize (e.g. "otelcol_exporter_sent_spans").
        lookback_minutes: How far back to look, in minutes.
    """
    try:
        password = await _resolve_password()
    except ClickHouseConfigError as e:
        return {"error": str(e)}

    query = f"""
        SELECT
            count() AS sample_count,
            min(value) AS min_value,
            max(value) AS max_value,
            avg(value) AS avg_value
        FROM {_METRICS_SAMPLES_TABLE}
        WHERE metric_name = {{metric_name:String}}
          AND unix_milli >= (toUnixTimestamp(now()) - {{lookback_seconds:UInt32}}) * 1000
    """

    try:
        client = _get_client(password)
        try:
            result = client.query(
                query,
                parameters={
                    "metric_name": metric_name,
                    "lookback_seconds": lookback_minutes * 60,
                },
            )
        finally:
            client.close()
    except Exception as e:  # clickhouse-connect raises its own exception hierarchy
        logger.error(f"ClickHouse query_metrics_summary failed: {e}")
        return {"error": f"ClickHouse query failed: {e}"}

    rows = result.result_rows
    if not rows:
        return {"metric_name": metric_name, "lookback_minutes": lookback_minutes, "sample_count": 0}

    sample_count, min_value, max_value, avg_value = rows[0]
    return {
        "metric_name": metric_name,
        "lookback_minutes": lookback_minutes,
        "sample_count": sample_count,
        "min_value": min_value,
        "max_value": max_value,
        "avg_value": avg_value,
    }
