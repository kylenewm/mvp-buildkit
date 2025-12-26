"""Search provider clients for Phase -1 research.

Simple interface to web search APIs (Tavily).
"""

import os
import re
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
    score: float = 0.0  # Rerank score if reranked, else engine score


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
    
    Uses Tavily's advanced search with answer generation.
    After each search, `last_answer` contains Tavily's synthesized answer.
    """
    
    BASE_URL = "https://api.tavily.com/search"
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        search_depth: str = "advanced",
        topic: str = "general",
        time_range: Optional[str] = "year",
        exclude_domains: Optional[List[str]] = None,
    ):
        self.api_key = api_key or os.environ.get("TAVILY_API_KEY")
        if not self.api_key:
            raise SearchClientError(
                "TAVILY_API_KEY environment variable is required."
            )
        self.search_depth = search_depth
        self.topic = topic
        self.time_range = time_range
        self.exclude_domains = exclude_domains or ["reddit.com", "linkedin.com"]
        # Store last answer for caller to access (V0: single-threaded OK)
        self.last_answer: str = ""
    
    def search(self, query: str, max_results: int = 5) -> List[SearchResult]:
        """Search Tavily and return results.
        
        After calling, access `self.last_answer` for Tavily's synthesized answer.
        
        Args:
            query: Search query
            max_results: Number of results to return (default 5)
        
        Returns:
            List of SearchResult with Tavily's relevance scores.
        """
        payload = {
            "api_key": self.api_key,
            "query": query,
            "max_results": max_results,
            "topic": self.topic,
            "search_depth": self.search_depth,
            "include_answer": "advanced",  # Get Tavily's AI-generated answer
            "include_raw_content": False,  # Don't need full pages
            "include_images": False,
        }
        
        # Add optional parameters
        if self.time_range:
            payload["time_range"] = self.time_range
        if self.exclude_domains:
            payload["exclude_domains"] = self.exclude_domains
        
        try:
            with httpx.Client(timeout=45.0) as client:
                response = client.post(self.BASE_URL, json=payload)
                response.raise_for_status()
                data = response.json()
        except httpx.TimeoutException:
            raise SearchClientError("Tavily request timed out")
        except httpx.HTTPStatusError as e:
            raise SearchClientError(f"Tavily API error: {e}")
        except httpx.RequestError as e:
            raise SearchClientError(f"Tavily network error: {e}")
        
        # Store Tavily's answer for caller
        self.last_answer = data.get("answer", "") or ""
        
        # Parse results
        results = []
        for item in data.get("results", [])[:max_results]:
            url = item.get("url", "")
            title = item.get("title", "")
            content = item.get("content", "") or ""
            
            # Clean and trim snippet (up to 1500 chars)
            snippet = _clean_snippet(content)[:1500] if content else ""
            
            results.append(SearchResult(
                url=url,
                title=title,
                snippet=snippet,
                score=item.get("score", 0.0),
            ))
        
        return results


def _clean_snippet(text: str) -> str:
    """Remove HTML tags, scripts, styles, and navigation cruft from snippet text."""
    # Strip HTML script and style blocks entirely
    text = re.sub(r"<script[^>]*>.*?</script>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    
    # Strip all HTML tags
    text = re.sub(r"<[^>]+>", " ", text)
    
    # Decode common HTML entities
    text = text.replace("&nbsp;", " ")
    text = text.replace("&amp;", "&")
    text = text.replace("&lt;", "<")
    text = text.replace("&gt;", ">")
    text = text.replace("&quot;", '"')
    text = text.replace("&#39;", "'")
    
    # Remove markdown links but keep text: [text](url) -> text
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    
    # Remove standalone URLs
    text = re.sub(r'https?://\S+', '', text)
    
    # Remove common nav patterns
    nav_patterns = [
        r'Skip to content',
        r'Get started.*?Log in',
        r'Schedule a call',
        r'Sign up.*?Log in',
        r'Browse links',
        r'Back to Reference',
        r'Table of Contents',
        r'© \d{4}.*?Inc',
    ]
    for pattern in nav_patterns:
        text = re.sub(pattern, '', text, flags=re.IGNORECASE)
    
    # Collapse multiple newlines/whitespace
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n +', '\n', text)
    
    return text.strip()


# NOTE: ExaClient commented out for now to reduce complexity.
# Uncomment if Exa support is needed in the future.
#
# class ExaClient(SearchClient):
#     """Exa search API client.
#     
#     Docs: https://docs.exa.ai/
#     """
#     
#     BASE_URL = "https://api.exa.ai/search"
#     
#     def __init__(self, api_key: Optional[str] = None):
#         self.api_key = api_key or os.environ.get("EXA_API_KEY")
#         if not self.api_key:
#             raise SearchClientError(
#                 "EXA_API_KEY environment variable is required."
#             )
#     
#     def search(self, query: str, max_results: int = 10) -> List[SearchResult]:
#         headers = {
#             "x-api-key": self.api_key,
#             "Content-Type": "application/json",
#         }
#         
#         payload = {
#             "query": query,
#             "numResults": max_results,
#             "type": "neural",
#             "useAutoprompt": True,
#             "contents": {
#                 "text": {"maxCharacters": 2000}
#             },
#         }
#         
#         try:
#             with httpx.Client(timeout=45.0) as client:
#                 response = client.post(self.BASE_URL, headers=headers, json=payload)
#                 response.raise_for_status()
#                 data = response.json()
#         except httpx.TimeoutException:
#             raise SearchClientError("Exa request timed out")
#         except httpx.HTTPStatusError as e:
#             raise SearchClientError(f"Exa API error: {e}")
#         except httpx.RequestError as e:
#             raise SearchClientError(f"Exa network error: {e}")
#         
#         results = []
#         for item in data.get("results", [])[:max_results]:
#             snippet = item.get("text", "") or ""
#             snippet = snippet[:2000] if snippet else ""
#             
#             results.append(SearchResult(
#                 url=item.get("url", ""),
#                 title=item.get("title", ""),
#                 snippet=snippet,
#                 score=item.get("score", 0.0),
#             ))
#         
#         return results


def get_search_client(provider: str) -> SearchClient:
    """Get a search client for the specified provider.
    
    Args:
        provider: "tavily" (only supported provider for now)
    
    Returns:
        SearchClient instance
    
    Raises:
        SearchClientError: If provider unknown or API key missing
    """
    if provider == "tavily":
        return TavilyClient()
    # elif provider == "exa":
    #     return ExaClient()
    else:
        raise SearchClientError(f"Unknown provider: {provider}. Use 'tavily'.")

