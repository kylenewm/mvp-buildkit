"""Phase -1 Research Runner: Executes bounded web search for research questions.

Reads research_snapshot.yaml, searches for each question, populates findings.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Set

import yaml

from .search_clients import SearchClient, SearchResult, get_search_client


@dataclass
class ResearchRunResult:
    """Result from research run."""
    success: bool
    questions_processed: int
    new_findings: int
    total_findings: int
    retrieved_at: str
    error: Optional[str] = None


# Official domains for tier1 classification
TIER1_DOMAINS: Set[str] = {
    "langchain-ai.github.io",
    "langchain.com",
    "openrouter.ai",
    "python.org",
    "docs.python.org",
    "github.com",
    "postgresql.org",
    "docs.pydantic.dev",
    "click.palletsprojects.com",
}


def _is_tier1_url(url: str) -> bool:
    """Check if URL is from an official/tier1 domain."""
    url_lower = url.lower()
    for domain in TIER1_DOMAINS:
        if domain in url_lower:
            return True
    # Check for docs.* pattern
    if "/docs/" in url_lower or url_lower.startswith("https://docs."):
        return True
    return False


def _trim_to_length(text: str, max_chars: int) -> str:
    """Trim text to max_chars, adding ellipsis if truncated."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars - 3].rsplit(" ", 1)[0] + "..."


def _build_query(question: dict) -> str:
    """Build search query from research question."""
    query = question.get("question", "")
    tags = question.get("tags", [])
    if tags:
        query += " " + " ".join(tags[:3])  # Add up to 3 tags
    return query


def _result_to_finding(
    result: SearchResult,
    finding_id: str,
    retrieved_at: str,
) -> dict:
    """Convert a SearchResult to a finding dict."""
    is_tier1 = _is_tier1_url(result.url)
    
    # Build claim from title/snippet (short, single sentence)
    claim = result.title
    if len(claim) > 200:
        claim = _trim_to_length(claim, 200)
    
    # Excerpt from snippet, trimmed
    excerpt = _trim_to_length(result.snippet, 240)
    
    return {
        "id": finding_id,
        "claim": claim,
        "source_url": result.url,
        "retrieved_at": retrieved_at,
        "excerpt": excerpt,
        "tier": "tier1_official" if is_tier1 else "tier2_reputable",
        "confidence": "high" if is_tier1 else "med",
    }


def _count_file_size(data: dict) -> tuple:
    """Estimate lines and words in YAML output."""
    yaml_str = yaml.dump(data, default_flow_style=False)
    lines = len(yaml_str.splitlines())
    words = len(yaml_str.split())
    return lines, words


def run_research(
    input_path: Path,
    output_path: Path,
    provider: str,
    max_results_per_question: int = 3,
    findings_per_question: int = 2,
    mark_sufficient: bool = False,
) -> ResearchRunResult:
    """
    Run research for all questions in research_snapshot.yaml.
    
    Args:
        input_path: Path to input research_snapshot.yaml
        output_path: Path to write updated research_snapshot.yaml
        provider: Search provider ("tavily" or "exa")
        max_results_per_question: Max search results per question
        findings_per_question: Max findings to create per question
        mark_sufficient: If True, set sufficiency.status to "sufficient"
    
    Returns:
        ResearchRunResult with summary
    """
    # Load input YAML
    try:
        with open(input_path) as f:
            data = yaml.safe_load(f)
    except Exception as e:
        return ResearchRunResult(
            success=False,
            questions_processed=0,
            new_findings=0,
            total_findings=0,
            retrieved_at="",
            error=f"Failed to load {input_path}: {e}",
        )
    
    # Validate minimal keys
    required = ["schema_version", "build_id", "state_version", "research_questions"]
    for key in required:
        if key not in data:
            return ResearchRunResult(
                success=False,
                questions_processed=0,
                new_findings=0,
                total_findings=0,
                retrieved_at="",
                error=f"Missing required key: {key}",
            )
    
    # Get search client
    try:
        client = get_search_client(provider)
    except Exception as e:
        return ResearchRunResult(
            success=False,
            questions_processed=0,
            new_findings=0,
            total_findings=0,
            retrieved_at="",
            error=str(e),
        )
    
    # Get size caps
    size_caps = data.get("size_caps", {})
    max_lines = size_caps.get("max_lines", 150)
    max_words = size_caps.get("max_words", 1200)
    
    # Current timestamp (UTC)
    now = datetime.now(timezone.utc).isoformat()
    
    # Get existing findings count for ID generation
    existing_findings = data.get("findings", []) or []
    next_finding_num = len(existing_findings) + 1
    
    # Process each research question
    new_findings: List[dict] = []
    questions_processed = 0
    
    for question in data.get("research_questions", []):
        query = _build_query(question)
        if not query:
            continue
        
        try:
            results = client.search(query, max_results=max_results_per_question)
        except Exception as e:
            # Log but continue - don't fail entire run for one question
            print(f"  ⚠️  Search failed for '{query[:50]}...': {e}")
            continue
        
        questions_processed += 1
        
        # Create findings from results (limit to findings_per_question)
        for result in results[:findings_per_question]:
            finding_id = f"F{next_finding_num}"
            finding = _result_to_finding(result, finding_id, now)
            new_findings.append(finding)
            next_finding_num += 1
    
    # Combine findings
    all_findings = existing_findings + new_findings
    
    # Update data
    data["retrieved_at"] = now
    data["state_version"] = data.get("state_version", 0) + 1
    data["findings"] = all_findings
    
    # Update sufficiency if requested
    if mark_sufficient:
        data["sufficiency"] = {
            "status": "sufficient",
            "rationale": f"Research conducted on {now}. {len(all_findings)} findings collected.",
        }
    elif data.get("sufficiency", {}).get("status") == "unknown":
        # Keep as unknown but update rationale
        data["sufficiency"]["rationale"] = (
            f"Research conducted on {now}. "
            f"{len(all_findings)} findings collected. "
            "Human review needed to determine sufficiency."
        )
    
    # Check size caps and trim if needed
    lines, words = _count_file_size(data)
    while (lines > max_lines or words > max_words) and len(data["findings"]) > len(existing_findings):
        # Remove the last new finding
        data["findings"].pop()
        lines, words = _count_file_size(data)
    
    # Write output
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
    except Exception as e:
        return ResearchRunResult(
            success=False,
            questions_processed=questions_processed,
            new_findings=len(new_findings),
            total_findings=len(all_findings),
            retrieved_at=now,
            error=f"Failed to write {output_path}: {e}",
        )
    
    return ResearchRunResult(
        success=True,
        questions_processed=questions_processed,
        new_findings=len(data["findings"]) - len(existing_findings),
        total_findings=len(data["findings"]),
        retrieved_at=now,
    )

