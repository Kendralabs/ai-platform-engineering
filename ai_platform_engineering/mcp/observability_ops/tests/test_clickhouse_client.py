# Copyright 2026 CNOE
# SPDX-License-Identifier: Apache-2.0

"""
Confirms tools/clickhouse_client.py's one real invariant: caller-supplied
values (metric_name, lookback_minutes) are always passed to
clickhouse-connect as bound `parameters`, never interpolated into the raw
SQL text. Mocks clickhouse_connect entirely - no real ClickHouse
connection.
"""

from unittest.mock import MagicMock, patch

import pytest

from tools import clickhouse_client


class _FakeResult:
    def __init__(self, rows):
        self.result_rows = rows


@pytest.mark.asyncio
async def test_query_metrics_summary_binds_parameters_not_fstring(monkeypatch):
    """The metric_name value must never appear inside the SQL text itself -
    it must only ever reach clickhouse-connect via the `parameters=` kwarg."""
    monkeypatch.setenv("CAIPE_CREDENTIALS_ENABLED", "false")
    monkeypatch.setenv("CLICKHOUSE_PASSWORD", "unit-test-password")

    fake_client = MagicMock()
    fake_client.query.return_value = _FakeResult([(5, 0.1, 9.9, 3.3)])

    sentinel_metric_name = "__SENTINEL_METRIC_NAME_SHOULD_NEVER_BE_IN_SQL_TEXT__"

    with patch.object(clickhouse_client, "clickhouse_connect") as mock_cc:
        mock_cc.get_client.return_value = fake_client

        result = await clickhouse_client.query_metrics_summary(sentinel_metric_name, lookback_minutes=30)

    assert "error" not in result
    assert result["metric_name"] == sentinel_metric_name
    assert result["sample_count"] == 5

    # The real assertion: the sentinel value went through as a bound
    # parameter, not string-interpolated into the SQL.
    assert fake_client.query.call_count == 1
    called_query_text, called_kwargs = fake_client.query.call_args
    query_text = called_query_text[0]
    bound_params = called_kwargs["parameters"]

    assert sentinel_metric_name not in query_text
    assert bound_params["metric_name"] == sentinel_metric_name
    assert bound_params["lookback_seconds"] == 30 * 60
    assert "{metric_name:String}" in query_text
    assert "{lookback_seconds:UInt32}" in query_text

    fake_client.close.assert_called_once()


@pytest.mark.asyncio
async def test_query_metrics_summary_empty_result(monkeypatch):
    monkeypatch.setenv("CAIPE_CREDENTIALS_ENABLED", "false")
    monkeypatch.setenv("CLICKHOUSE_PASSWORD", "unit-test-password")

    fake_client = MagicMock()
    fake_client.query.return_value = _FakeResult([])

    with patch.object(clickhouse_client, "clickhouse_connect") as mock_cc:
        mock_cc.get_client.return_value = fake_client
        result = await clickhouse_client.query_metrics_summary("no_such_metric")

    assert result["sample_count"] == 0


@pytest.mark.asyncio
async def test_query_metrics_summary_missing_password_errors(monkeypatch):
    monkeypatch.setenv("CAIPE_CREDENTIALS_ENABLED", "false")
    monkeypatch.delenv("CLICKHOUSE_PASSWORD", raising=False)

    result = await clickhouse_client.query_metrics_summary("some_metric")

    assert "error" in result
