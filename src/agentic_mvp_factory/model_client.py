"""Model client interface and OpenRouter implementation."""

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx


# =============================================================================
# TOKEN BUDGET POLICY (V0)
# =============================================================================

DRAFT_BASE = {
    "plan": 20000,
    "spec": 10000,
    "invariants": 8000,
    "tracker": 16000,
    "prompts": 14000,
    "cursor_rules": 6000,
    "triage": 6000,  # Small for triage calls
}

# Hard safety clamp (V0) - prevents requesting more than providers can deliver
MAX_OUTPUT_TOKENS = 60000


def compute_token_budget(stage: str, role: str, n_models: int) -> int:
    """
    Compute max_output_tokens for a council call.
    
    Args:
        stage: Council stage (plan, spec, invariants, tracker, prompts, cursor_rules)
        role: Role in council (draft, critique, chair)
        n_models: Number of drafter models in the run
    
    Returns:
        Derived token budget, clamped to MAX_OUTPUT_TOKENS
    """
    base = DRAFT_BASE.get(stage, 4000)
    
    if role == "draft":
        return base
    
    if role == "critique":
        # Critique sees all drafts, so needs more headroom
        mult = 2 if n_models == 2 else (3 if n_models >= 3 else 1)
        return min(base * mult, MAX_OUTPUT_TOKENS)
    
    if role == "chair":
        # Chair sees drafts + critiques, needs most headroom
        mult = 3 if n_models == 2 else (4 if n_models >= 3 else 1)
        return min(base * mult, MAX_OUTPUT_TOKENS)
    
    return base


# =============================================================================
# DATA CLASSES
# =============================================================================

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
        max_tokens: Optional[int] = None,
        include_reasoning: bool = False,
    ) -> CompletionResult:
        """
        Execute a chat completion.
        
        Args:
            messages: List of chat messages
            model: Model identifier
            timeout: Request timeout in seconds
            max_tokens: Maximum output tokens (if None, use model default)
            include_reasoning: Whether to request reasoning (hidden, not returned)
        
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
    
    def _make_request(
        self,
        payload: dict,
        headers: dict,
        timeout: float,
    ) -> dict:
        """Make HTTP request to OpenRouter API."""
        with httpx.Client(timeout=timeout) as client:
            response = client.post(
                self.BASE_URL,
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            return response.json()
    
    def complete(
        self,
        messages: List[Message],
        model: str,
        timeout: float = 30.0,
        max_tokens: Optional[int] = None,
        include_reasoning: bool = False,
        reasoning_effort: str = "low",
    ) -> CompletionResult:
        """
        Execute a chat completion via OpenRouter.
        
        Args:
            messages: List of chat messages
            model: Model identifier (e.g., "openai/gpt-4o-mini", "anthropic/claude-sonnet-4.5")
            timeout: Request timeout in seconds
            max_tokens: Maximum output tokens (if None, use model default)
            include_reasoning: Whether to request reasoning (hidden, not returned)
            reasoning_effort: Reasoning effort level ("low", "medium", "high")
        
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
        
        # Add max_tokens if specified
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        
        # Add reasoning config (hidden, not returned in output)
        if include_reasoning:
            payload["include_reasoning"] = True
            payload["reasoning"] = {"effort": reasoning_effort, "exclude": True}
        
        # Debug logging (env-gated)
        if os.environ.get("COUNCIL_DEBUG_TOKENS"):
            print(f"[DEBUG] model={model}, max_tokens={max_tokens}, reasoning={include_reasoning}")
        
        try:
            # Try with reasoning first (if requested)
            data = self._make_request(payload, headers, timeout)
        
        except httpx.HTTPStatusError as e:
            # Check if reasoning was rejected (4xx mentioning reasoning)
            if include_reasoning and e.response.status_code == 400:
                try:
                    error_text = e.response.text.lower()
                    if "reasoning" in error_text or "unknown" in error_text:
                        # Retry ONCE without reasoning
                        if os.environ.get("COUNCIL_DEBUG_TOKENS"):
                            print(f"[DEBUG] Reasoning unsupported for {model}, retrying without")
                        payload.pop("include_reasoning", None)
                        payload.pop("reasoning", None)
                        try:
                            data = self._make_request(payload, headers, timeout)
                        except httpx.HTTPStatusError as e2:
                            error_data = e2.response.json()
                            error_msg = error_data.get("error", {}).get("message", str(e2))
                            raise ModelClientError(f"API error: {error_msg}")
                    else:
                        raise
                except Exception:
                    raise
            else:
                # Extract error message from response if available
                try:
                    error_data = e.response.json()
                    error_msg = error_data.get("error", {}).get("message", str(e))
                except Exception:
                    error_msg = str(e)
                raise ModelClientError(f"API error: {error_msg}")
        
        except httpx.TimeoutException:
            raise ModelClientError(
                f"Request timed out after {timeout}s. "
                "Try again or use a faster model."
            )
        except httpx.RequestError as e:
            raise ModelClientError(f"Network error: {e}")
        
        # Extract response content
        try:
            choices = data.get("choices", [])
            if not choices:
                raise ModelClientError("No choices in API response")
            
            message = choices[0].get("message", {})
            content = message.get("content", "")
            
            # NOTE: We explicitly do NOT capture message.get("reasoning")
            # per the policy: "Never store or return reasoning text"
            
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
    # Token budget params (V0 guardrails)
    stage: Optional[str] = None,
    role: Optional[str] = None,
    n_models: int = 3,
    include_reasoning: bool = True,
) -> CompletionResult:
    """
    Wrapper that adds LangSmith tracing and token budget guardrails.
    
    This creates a traced span for each model call with:
    - Descriptive name: "{phase}_{model}"
    - Input: messages as JSON-serializable dicts
    - Output: content, model, usage as dict
    - Metadata: phase, model, run_id for filtering
    
    Token Budget:
    - If stage/role provided, computes max_tokens from DRAFT_BASE policy
    - If not provided, falls back to phase as stage and role
    
    Args:
        client: OpenRouter client instance
        messages: List of chat messages
        model: Model identifier
        timeout: Request timeout in seconds
        phase: Phase of the workflow (draft, critique, chair) - used for tracing
        run_id: Run ID for filtering in LangSmith
        stage: Council stage (plan, spec, etc.) - used for token budget
        role: Role in council (draft, critique, chair) - used for token budget
        n_models: Number of drafter models in the run
        include_reasoning: Whether to request reasoning (hidden, not returned)
        
    Returns:
        CompletionResult from the model
    """
    from langsmith import traceable
    
    # Derive stage/role from phase if not explicitly provided
    effective_stage = stage or "plan"  # Default to plan if not specified
    effective_role = role or phase  # Use phase as role fallback
    
    # Compute token budget
    max_tokens = compute_token_budget(effective_stage, effective_role, n_models)
    
    # Derive reasoning effort from role (chair gets medium, others get low)
    reasoning_effort = "medium" if effective_role == "chair" else "low"
    
    # Debug logging (env-gated)
    if os.environ.get("COUNCIL_DEBUG_TOKENS"):
        print(f"[DEBUG] traced_complete: stage={effective_stage}, role={effective_role}, n={n_models}, max_tokens={max_tokens}")
    
    # Convert to JSON-serializable input for tracing
    messages_dict = [{"role": m.role, "content": m.content} for m in messages]
    
    # Create trace name (replace / with _ for cleaner display)
    trace_name = f"{phase}_{model.replace('/', '_')}"
    
    @traceable(
        name=trace_name,
        run_type="llm",
        metadata={
            "phase": phase,
            "model": model,
            "run_id": run_id,
            "stage": effective_stage,
            "role": effective_role,
            "n_models": n_models,
            "max_tokens": max_tokens,
        },
    )
    def _traced_call(messages_input: List[dict], model_name: str) -> dict:
        # Convert back to Message objects for the actual call
        msg_objects = [Message(role=m["role"], content=m["content"]) for m in messages_input]
        
        result = client.complete(
            messages=msg_objects,
            model=model_name,
            timeout=timeout,
            max_tokens=max_tokens,
            include_reasoning=include_reasoning,
            reasoning_effort=reasoning_effort,
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
