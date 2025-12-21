"""Model client interface and OpenRouter implementation."""

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx


@dataclass
class Message:
    """A chat message."""
    role: str  # "system", "user", "assistant"
    content: str


@dataclass
class CompletionResult:
    """Result from a model completion call."""
    content: str
    model: str
    usage: Optional[Dict[str, Any]] = None
    raw_response: Optional[Dict[str, Any]] = None


class ModelClient(ABC):
    """Abstract interface for model clients."""
    
    @abstractmethod
    def complete(
        self,
        messages: List[Message],
        model: str,
        timeout: float = 30.0,
    ) -> CompletionResult:
        """
        Execute a chat completion.
        
        Args:
            messages: List of chat messages
            model: Model identifier
            timeout: Request timeout in seconds
        
        Returns:
            CompletionResult with content and metadata
        
        Raises:
            ModelClientError: On API or network errors
        """
        pass


class ModelClientError(Exception):
    """Error from model client operations."""
    pass


class OpenRouterClient(ModelClient):
    """OpenRouter API client.
    
    Uses the OpenRouter chat completions endpoint.
    API docs: https://openrouter.ai/docs
    """
    
    BASE_URL = "https://openrouter.ai/api/v1/chat/completions"
    
    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize OpenRouter client.
        
        Args:
            api_key: OpenRouter API key. If not provided, reads from
                     OPENROUTER_API_KEY environment variable.
        """
        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY")
        if not self.api_key:
            raise ModelClientError(
                "OPENROUTER_API_KEY environment variable is required."
            )
    
    def complete(
        self,
        messages: List[Message],
        model: str,
        timeout: float = 30.0,
    ) -> CompletionResult:
        """
        Execute a chat completion via OpenRouter.
        
        Args:
            messages: List of chat messages
            model: Model identifier (e.g., "openai/gpt-4o-mini", "anthropic/claude-sonnet-4.5", "google/gemini-2.5-flash-lite")
            timeout: Request timeout in seconds
        
        Returns:
            CompletionResult with content and usage metadata
        
        Raises:
            ModelClientError: On API or network errors
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/council-cli",
            "X-Title": "Council CLI",
        }
        
        payload = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
        }
        
        try:
            with httpx.Client(timeout=timeout) as client:
                response = client.post(
                    self.BASE_URL,
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
        
        except httpx.TimeoutException:
            raise ModelClientError(
                f"Request timed out after {timeout}s. "
                "Try again or use a faster model."
            )
        except httpx.HTTPStatusError as e:
            # Extract error message from response if available
            try:
                error_data = e.response.json()
                error_msg = error_data.get("error", {}).get("message", str(e))
            except Exception:
                error_msg = str(e)
            raise ModelClientError(f"API error: {error_msg}")
        except httpx.RequestError as e:
            raise ModelClientError(f"Network error: {e}")
        
        # Extract response content
        try:
            choices = data.get("choices", [])
            if not choices:
                raise ModelClientError("No choices in API response")
            
            content = choices[0].get("message", {}).get("content", "")
            if not content:
                raise ModelClientError("Empty content in API response")
            
            # Extract usage metadata if present
            usage = data.get("usage")
            
            return CompletionResult(
                content=content,
                model=data.get("model", model),
                usage=usage,
                raw_response=data,
            )
        
        except KeyError as e:
            raise ModelClientError(f"Unexpected API response format: missing {e}")


def get_openrouter_client() -> OpenRouterClient:
    """Get an OpenRouter client instance."""
    return OpenRouterClient()


def traced_complete(
    client: OpenRouterClient,
    messages: List[Message],
    model: str,
    timeout: float = 30.0,
    # Tracing metadata
    phase: str = "unknown",  # "draft", "critique", "chair"
    run_id: str = "",
) -> CompletionResult:
    """
    Wrapper that adds LangSmith tracing to model calls.
    
    This creates a traced span for each model call with:
    - Descriptive name: "{phase}_{model}"
    - Input: messages as JSON-serializable dicts
    - Output: content, model, usage as dict
    - Metadata: phase, model, run_id for filtering
    
    Args:
        client: OpenRouter client instance
        messages: List of chat messages
        model: Model identifier
        timeout: Request timeout in seconds
        phase: Phase of the workflow (draft, critique, chair)
        run_id: Run ID for filtering in LangSmith
        
    Returns:
        CompletionResult from the model
    """
    from langsmith import traceable
    
    # Convert to JSON-serializable input for tracing
    messages_dict = [{"role": m.role, "content": m.content} for m in messages]
    
    # Create trace name (replace / with _ for cleaner display)
    trace_name = f"{phase}_{model.replace('/', '_')}"
    
    @traceable(
        name=trace_name,
        run_type="llm",
        metadata={"phase": phase, "model": model, "run_id": run_id},
    )
    def _traced_call(messages_input: List[dict], model_name: str) -> dict:
        # Convert back to Message objects for the actual call
        msg_objects = [Message(role=m["role"], content=m["content"]) for m in messages_input]
        
        result = client.complete(
            messages=msg_objects,
            model=model_name,
            timeout=timeout,
        )
        
        # Return JSON-serializable output for tracing
        return {
            "content": result.content,
            "model": result.model,
            "usage": result.usage,
        }
    
    # Execute the traced call
    output = _traced_call(messages_dict, model)
    
    # Convert back to CompletionResult
    return CompletionResult(
        content=output["content"],
        model=output["model"],
        usage=output.get("usage"),
    )

