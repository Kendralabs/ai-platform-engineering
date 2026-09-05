#!/usr/bin/env python3
"""Test script for the Woodpecker API client."""

import asyncio
import sys
import os
from unittest.mock import patch, AsyncMock, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from api.client import make_api_request


async def test_make_api_request():
    print("Testing make_api_request...")

    print("\n1. Testing successful GET request (list response):")
    mock_response_data = [{"id": 1, "full_name": "kendralabs/kcg"}]

    with patch('api.client.httpx.AsyncClient') as mock_client_class:
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_response_data
        mock_response.text = '[{"id": 1, "full_name": "kendralabs/kcg"}]'

        mock_client.get.return_value = mock_response

        success, data = await make_api_request("/api/user/repos", token="dummy-token")
        assert success, "Should return success=True"
        assert data == mock_response_data, "Should return correct data"
        print("✓ Successful GET request handled correctly")

    print("\n2. Testing HTTP error response:")
    with patch('api.client.httpx.AsyncClient') as mock_client_class:
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client

        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.json.return_value = {"error": "Not found"}
        mock_response.text = '{"error": "Not found"}'

        mock_client.get.return_value = mock_response

        success, data = await make_api_request("/api/repos/999", token="dummy-token")
        assert not success, "Should return success=False"
        assert "error" in data, "Should include an error key"
        print("✓ HTTP error response handled correctly")

    print("\n3. Testing missing token:")
    with patch('api.client._ENV_TOKEN', None), patch('api.client.get_request_token', return_value=None):
        success, data = await make_api_request("/api/user/repos")
        assert not success, "Should return success=False when no token is available"
        assert "error" in data
        print("✓ Missing token handled correctly")

    print("\nAll api.client tests passed.")


if __name__ == "__main__":
    asyncio.run(test_make_api_request())
