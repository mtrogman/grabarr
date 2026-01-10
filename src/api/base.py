"""
Base API client with async HTTP, retry logic, and proper error handling.

Features:
- Async HTTP with aiohttp
- Exponential backoff retry
- Proper timeout handling
- Structured error responses
- API key in headers (not query params)
"""

import asyncio
from abc import ABC
from typing import Any, Optional

import aiohttp

from ..logging_config import get_logger

logger = get_logger(__name__)


class APIError(Exception):
    """API error with status code and response details."""

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        response_body: Optional[str] = None
    ):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class APIClient(ABC):
    """
    Base async API client with retry logic and proper error handling.

    All API keys are passed via X-Api-Key header, never in query params.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout: int = 15,
        max_retries: int = 3,
        retry_delay: float = 1.0
    ):
        """
        Initialize API client.

        Args:
            base_url: Base URL for API (e.g., "http://localhost:8989/api/v3")
            api_key: API key for authentication
            timeout: Request timeout in seconds
            max_retries: Maximum number of retry attempts
            retry_delay: Initial delay between retries (doubles each retry)
        """
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self._session: Optional[aiohttp.ClientSession] = None

    @property
    def _headers(self) -> dict[str, str]:
        """Default headers with API key."""
        return {
            "X-Api-Key": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=self.timeout,
                headers=self._headers
            )
        return self._session

    async def close(self) -> None:
        """Close the HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def _request(
        self,
        method: str,
        endpoint: str,
        data: Optional[dict] = None,
        params: Optional[dict] = None,
        retry_count: int = 0
    ) -> Any:
        """
        Make HTTP request with retry logic.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE)
            endpoint: API endpoint (e.g., "/movie")
            data: Request body for POST/PUT
            params: Query parameters
            retry_count: Current retry attempt (internal)

        Returns:
            Parsed JSON response

        Raises:
            APIError: On request failure after all retries
        """
        url = f"{self.base_url}{endpoint}"
        session = await self._get_session()

        try:
            async with session.request(
                method,
                url,
                json=data,
                params=params
            ) as response:
                response_text = await response.text()

                if response.ok:
                    if response_text:
                        return await response.json()
                    return None

                # Handle specific error codes
                if response.status == 401:
                    raise APIError(
                        "Authentication failed - check API key",
                        status_code=401,
                        response_body=response_text
                    )
                elif response.status == 404:
                    raise APIError(
                        f"Resource not found: {endpoint}",
                        status_code=404,
                        response_body=response_text
                    )
                elif response.status >= 500:
                    # Server errors are retryable
                    raise aiohttp.ServerConnectionError(
                        f"Server error {response.status}: {response_text}"
                    )
                else:
                    raise APIError(
                        f"API request failed: {response.status}",
                        status_code=response.status,
                        response_body=response_text
                    )

        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            # Retry on connection/timeout errors
            if retry_count < self.max_retries:
                delay = self.retry_delay * (2 ** retry_count)
                logger.warning_structured(
                    f"Request failed, retrying in {delay}s",
                    url=url,
                    method=method,
                    retry=retry_count + 1,
                    max_retries=self.max_retries,
                    error=str(e)
                )
                await asyncio.sleep(delay)
                return await self._request(method, endpoint, data, params, retry_count + 1)

            logger.error_structured(
                "Request failed after all retries",
                url=url,
                method=method,
                error=str(e)
            )
            raise APIError(f"Request failed after {self.max_retries} retries: {e}")

    async def get(self, endpoint: str, params: Optional[dict] = None) -> Any:
        """Make GET request."""
        return await self._request("GET", endpoint, params=params)

    async def post(self, endpoint: str, data: Optional[dict] = None) -> Any:
        """Make POST request."""
        return await self._request("POST", endpoint, data=data)

    async def put(self, endpoint: str, data: Optional[dict] = None) -> Any:
        """Make PUT request."""
        return await self._request("PUT", endpoint, data=data)

    async def delete(self, endpoint: str) -> Any:
        """Make DELETE request."""
        return await self._request("DELETE", endpoint)

    async def health_check(self) -> bool:
        """
        Check if API is reachable and authenticated.

        Returns:
            True if API is healthy, False otherwise
        """
        try:
            await self.get("/system/status")
            return True
        except APIError:
            return False

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()
