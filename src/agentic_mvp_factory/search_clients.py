"""Search provider clients for Phase -1 research.

Simple interface to web search APIs (Tavily, Exa).
"""

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional

import httpx


@dataclass
class SearchResult:
    """A single search result."""
    url: str
    title: str
    snippet: str


class SearchClientError(Exception):
    """Error from search client operations."""
    pass


class SearchClient(ABC):
    """Abstract interface for search clients."""
    
    @abstractmethod
    def search(self, query: str, max_results: int = 3) -> List[SearchResult]:
        """
        Execute a search query.
        
        Args:
            query: Search query string
            max_results: Maximum results to return
        
        Returns:
            List of SearchResult
        
        Raises:
            SearchClientError: On API or network errors
        """
        pass


class TavilyClient(SearchClient):
    """Tavily search API client.
    
    Docs: https://docs.tavily.com/
    """
    
    BASE_URL = "https://api.tavily.com/search"
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("TAVILY_API_KEY")
        if not self.api_key:
            raise SearchClientError(
                "TAVILY_API_KEY environment variable is required."
            )
    
    def search(self, query: str, max_results: int = 3) -> List[SearchResult]:
        payload = {
            "api_key": self.api_key,
            "query": query,
            "max_results": max_results,
            "include_answer": False,
            "include_raw_content": False,
        }
        
        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(self.BASE_URL, json=payload)
                response.raise_for_status()
                data = response.json()
        except httpx.TimeoutException:
            raise SearchClientError("Tavily request timed out")
        except httpx.HTTPStatusError as e:
            raise SearchClientError(f"Tavily API error: {e}")
        except httpx.RequestError as e:
            raise SearchClientError(f"Tavily network error: {e}")
        
        results = []
        for item in data.get("results", [])[:max_results]:
            results.append(SearchResult(
                url=item.get("url", ""),
                title=item.get("title", ""),
                snippet=item.get("content", "")[:500],  # Trim long snippets
            ))
        
        return results


class ExaClient(SearchClient):
    """Exa search API client.
    
    Docs: https://docs.exa.ai/
    """
    
    BASE_URL = "https://api.exa.ai/search"
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("EXA_API_KEY")
        if not self.api_key:
            raise SearchClientError(
                "EXA_API_KEY environment variable is required."
            )
    
    def search(self, query: str, max_results: int = 3) -> List[SearchResult]:
        headers = {
            "x-api-key": self.api_key,
            "Content-Type": "application/json",
        }
        
        payload = {
            "query": query,
            "numResults": max_results,
            "type": "neural",
            "useAutoprompt": True,
        }
        
        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(self.BASE_URL, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
        except httpx.TimeoutException:
            raise SearchClientError("Exa request timed out")
        except httpx.HTTPStatusError as e:
            raise SearchClientError(f"Exa API error: {e}")
        except httpx.RequestError as e:
            raise SearchClientError(f"Exa network error: {e}")
        
        results = []
        for item in data.get("results", [])[:max_results]:
            results.append(SearchResult(
                url=item.get("url", ""),
                title=item.get("title", ""),
                snippet=item.get("text", "")[:500] if item.get("text") else "",
            ))
        
        return results


def get_search_client(provider: str) -> SearchClient:
    """Get a search client for the specified provider.
    
    Args:
        provider: "tavily" or "exa"
    
    Returns:
        SearchClient instance
    
    Raises:
        SearchClientError: If provider unknown or API key missing
    """
    if provider == "tavily":
        return TavilyClient()
    elif provider == "exa":
        return ExaClient()
    else:
        raise SearchClientError(f"Unknown provider: {provider}. Use 'tavily' or 'exa'.")

