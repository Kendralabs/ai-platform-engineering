# Copyright 2026 CNOE
# SPDX-License-Identifier: Apache-2.0

"""API client for making requests to the Woodpecker CI REST API."""

import os
import logging
from typing import Optional, Dict, Tuple, Any
import httpx
from mcp_agent_auth.token import get_request_token

API_URL = os.getenv("WOODPECKER_API_URL")

if not API_URL:
    raise ValueError("WOODPECKER_API_URL environment variable is not set.")

logger = logging.getLogger("mcp_woodpecker")

_ENV_TOKEN = os.getenv("WOODPECKER_API_TOKEN")
if not _ENV_TOKEN:
    logger.warning("WOODPECKER_API_TOKEN is not set; token must be supplied via Authorization: Bearer header")


async def make_api_request(
    path: str,
    method: str = "GET",
    token: Optional[str] = None,
    params: Dict[str, Any] = {},
    data: Dict[str, Any] = {},
    timeout: int = 30,
) -> Tuple[bool, Any]:
    """
    Make a request to the Woodpecker API.

    Args:
        path: API path to request (without base URL)
        method: HTTP method (default: GET)
        token: API token (defaults to WOODPECKER_API_TOKEN)
        params: Query parameters for the request (optional)
        data: JSON data for POST/PATCH/PUT requests (optional)
        timeout: Request timeout in seconds (default: 30)

    Returns:
        Tuple of (success, data) where data is either the response JSON or an error dict
    """
    logger.debug(f"Making {method} request to {path}")

    if not token:
        token = get_request_token("WOODPECKER_API_TOKEN")
    if not token:
        token = _ENV_TOKEN

    if not token:
        logger.error("No token available - neither provided nor found in environment")
        return (
            False,
            {"error": "Token is required. Please set the WOODPECKER_API_TOKEN environment variable."},
        )

    try:
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        logger.debug("Request headers prepared (Authorization header masked)")
        logger.debug(f"Request parameters: {params}")
        if data:
            logger.debug(f"Request data: {data}")

        async with httpx.AsyncClient(timeout=timeout) as client:
            url = f"{API_URL}{path}"
            logger.info(f"Full request URL: {url}")

            method_map = {
                "GET": client.get,
                "POST": client.post,
                "PATCH": client.patch,
                "DELETE": client.delete,
            }

            if method not in method_map:
                logger.error(f"Unsupported HTTP method: {method}")
                return (False, {"error": f"Unsupported method: {method}"})

            request_kwargs = {"headers": headers, "params": params}
            if method in ["POST", "PATCH"]:
                request_kwargs["json"] = data

            response = await method_map[method](url, **request_kwargs)
            logger.debug(f"Response status code: {response.status_code}")

            if response.status_code in [200, 201, 202, 204]:
                if response.status_code == 204:
                    return (True, {"status": "success"})
                try:
                    return (True, response.json())
                except ValueError:
                    return (True, {"status": "success", "raw_response": response.text})
            else:
                error_message = f"API request failed: {response.status_code}"
                logger.error(error_message)
                try:
                    error_data = response.json()
                    logger.error(f"Error details: {error_data}")
                    return (False, {"error": error_message, "details": error_data})
                except ValueError:
                    error_text = response.text[:200] if response.text else ""
                    logger.error(f"Error response (not JSON): {error_text}")
                    return (False, {"error": f"{error_message} - {error_text}"})
    except httpx.TimeoutException:
        logger.error(f"Request timed out after {timeout} seconds")
        return (False, {"error": f"Request timed out after {timeout} seconds"})
    except httpx.RequestError as e:
        error_message = str(e)
        if token and token in error_message:
            error_message = error_message.replace(token, "[REDACTED]")
        logger.error(f"Request error: {error_message}")
        return (False, {"error": f"Request error: {error_message}"})
    except Exception as e:
        error_message = str(e)
        if token and token in error_message:
            error_message = error_message.replace(token, "[REDACTED]")
        logger.error(f"Unexpected error: {error_message}")
        return (False, {"error": f"Unexpected error: {error_message}"})
