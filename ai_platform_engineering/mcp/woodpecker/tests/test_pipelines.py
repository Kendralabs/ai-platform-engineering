#!/usr/bin/env python3
"""Test script for the Woodpecker pipeline tools."""

import asyncio
import sys
import os
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from tools import pipelines


async def test_get_latest_pipeline_picks_newest():
    print("Testing get_latest_pipeline...")

    mock_pipelines = [
        {"number": 1, "branch": "main", "created": 100, "status": "success"},
        {"number": 3, "branch": "main", "created": 300, "status": "failure"},
        {"number": 2, "branch": "staging", "created": 500, "status": "success"},
    ]

    with patch('tools.pipelines.make_api_request', return_value=(True, mock_pipelines)):
        latest_any = await pipelines.get_latest_pipeline(repo_id=1)
        assert latest_any["number"] == 2, f"Expected the globally newest pipeline (500), got {latest_any}"

        latest_main = await pipelines.get_latest_pipeline(repo_id=1, branch="main")
        assert latest_main["number"] == 3, f"Expected the newest main pipeline (300), got {latest_main}"
        print("✓ get_latest_pipeline picks the newest pipeline, with and without a branch filter")

    print("\nTesting get_latest_pipeline with no matches:")
    with patch('tools.pipelines.make_api_request', return_value=(True, mock_pipelines)):
        result = await pipelines.get_latest_pipeline(repo_id=1, branch="nonexistent")
        assert "error" in result, f"Expected an error dict, got {result}"
        print("✓ get_latest_pipeline reports an error when no pipeline matches the branch filter")

    print("\nTesting get_latest_pipeline on request failure:")
    with patch('tools.pipelines.make_api_request', return_value=(False, {"error": "boom"})):
        result = await pipelines.get_latest_pipeline(repo_id=1)
        assert result == {"error": "boom"}, f"Expected the upstream error to propagate, got {result}"
        print("✓ get_latest_pipeline propagates request failures")

    print("\nAll pipelines tool tests passed.")


if __name__ == "__main__":
    asyncio.run(test_get_latest_pipeline_picks_newest())
