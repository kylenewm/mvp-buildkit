"""Phase -1 Research Runner: Executes bounded web search for research questions.

Reads research_snapshot.yaml, searches for each question, populates findings.
"""

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import yaml

from .constants import DEFAULT_TRIAGE_MODEL, DEFAULT_TRIAGE_TIMEOUT_S
from .model_client import Message, OpenRouterClient, ModelClientError, traced_complete
from .search_clients import SearchClient, SearchResult, SearchResponse, get_search_client


# ---------------------------------------------------------------------------
# Triage prompts
# ---------------------------------------------------------------------------
TRIAGE_SYSTEM_PROMPT = """You classify evidence snippets into buckets so humans can skim high-signal items first. Do NOT rewrite or invent facts."""

TRIAGE_USER_TEMPLATE = """research_question: {question}
page_title: {page_title}
source_url: {source_url}
evidence_snippet: {evidence_snippet}

Classify into ONE bucket:
- "high": Concrete facts/metrics/definitions that directly answer the question.
- "normal": Relevant but partial/tangential or requires inference.
- "low": Weak signal, generic, ambiguous, but not junk.
- "junk": Cookies/privacy, nav/footer, login/signup, ads, TOC, marketing fluff, scraped UI chrome, unrelated docs.

Please keep the reason under 120 characters. 

Return JSON ONLY (no fences): {{"bucket": "high"|"normal"|"low"|"junk", "reason": "<120 chars>"}}"""


@dataclass
class TriageResult:
    """Result from triage LLM call."""
    bucket: str  # "high", "normal", "low", "junk"
    reason: str


def _default_triage() -> TriageResult:
    """Return default triage result for failures."""
    return TriageResult(
        bucket="normal",
        reason="triage_failed",
    )


def _parse_triage_response(content: str) -> TriageResult:
    """Parse LLM JSON response into TriageResult."""
    content = content.strip()
    if content.startswith("```"):
        lines = content.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        content = "\n".join(lines)
    
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return _default_triage()
    
    bucket = data.get("bucket", "normal")
    if bucket not in ("high", "normal", "low", "junk"):
        bucket = "normal"
    
    reason = str(data.get("reason", ""))[:150]
    
    return TriageResult(bucket=bucket, reason=reason)


def _triage_finding(
    client: OpenRouterClient,
    question: str,
    page_title: str,
    source_url: str,
    evidence_snippet: str,
    run_id: str = "",
) -> TriageResult:
    """
    Run LLM triage on a single finding via traced_complete.
    
    Returns TriageResult with verdict. On failure, returns safe defaults.
    """
    user_prompt = TRIAGE_USER_TEMPLATE.format(
        question=question,
        page_title=page_title,
        source_url=source_url,
        evidence_snippet=evidence_snippet[:1500],  # Cap snippet length
    )
    
    messages = [
        Message(role="system", content=TRIAGE_SYSTEM_PROMPT),
        Message(role="user", content=user_prompt),
    ]
    
    try:
        result = traced_complete(
            client=client,
            messages=messages,
            model=DEFAULT_TRIAGE_MODEL,
            timeout=DEFAULT_TRIAGE_TIMEOUT_S,
            phase="triage",
            run_id=run_id,
        )
        return _parse_triage_response(result.content)
    except ModelClientError:
        return _default_triage()
    except Exception:
        return _default_triage()


def _get_triage_client() -> Optional[OpenRouterClient]:
    """Get OpenRouter client for triage, or None if not configured."""
    try:
        return OpenRouterClient()
    except ModelClientError:
        return None


def _bucket_sort_key(finding: dict, original_idx: int) -> tuple:
    """Sort key: high=0, normal=1, low=2, junk=3, then original index."""
    bucket = finding.get("triage_bucket", "normal")
    rank = {"high": 0, "normal": 1, "low": 2, "junk": 3}.get(bucket, 1)
    return (rank, original_idx)


def _sort_findings_by_triage(findings: List[dict]) -> List[dict]:
    """
    Sort findings by triage_bucket within each rq_id.
    Order: high → normal → low → junk. Stable within bucket.
    """
    from collections import OrderedDict
    by_rq: Dict[str, List[tuple]] = OrderedDict()
    
    for idx, finding in enumerate(findings):
        rq_id = finding.get("rq_id", "")
        if rq_id not in by_rq:
            by_rq[rq_id] = []
        by_rq[rq_id].append((idx, finding))
    
    sorted_findings = []
    for rq_id, items in by_rq.items():
        sorted_items = sorted(items, key=lambda x: _bucket_sort_key(x[1], x[0]))
        sorted_findings.extend([item[1] for item in sorted_items])
    
    return sorted_findings


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


def _derive_claim_label(snippet: str, fallback_title: str, max_len: int = 160) -> str:
    """
    Derive a scannable claim label from the evidence snippet.
    
    V1 TODO: For strict claim verification, fetch page HTML and extract
    sentence-level quotes anchored to spans.
    V0 intentionally stores only Tavily snippets for human review.
    """
    if not snippet or not snippet.strip():
        return fallback_title[:max_len] if fallback_title else ""
    
    # Split snippet into lines and find first meaningful line
    lines = snippet.split("\n")
    for line in lines:
        # Clean the line
        cleaned = line.strip()
        if not cleaned:
            continue
        
        # Remove markdown heading prefix: ^#+\s+
        cleaned = re.sub(r'^#+\s+', '', cleaned)
        
        # Remove list markers: ^[-*•]\s+ or ^\d+\.\s+
        cleaned = re.sub(r'^[-*•]\s+', '', cleaned)
        cleaned = re.sub(r'^\d+\.\s+', '', cleaned)
        
        # Collapse internal whitespace
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        
        if cleaned:
            # Truncate if too long
            if len(cleaned) > max_len:
                return cleaned[:max_len - 1] + "…"
            return cleaned
    
    # No usable line found
    return fallback_title[:max_len] if fallback_title else ""


def _result_to_finding(
    result: SearchResult,
    finding_id: str,
    retrieved_at: str,
    rq_id: Optional[str] = None,
    triage: Optional[TriageResult] = None,
) -> dict:
    """Convert a SearchResult to a finding dict with proper V0 semantics."""
    is_tier1 = _is_tier1_url(result.url)
    
    # evidence_snippet = the actual Tavily snippet (up to 1500 chars)
    evidence_snippet = result.snippet.strip() if result.snippet else ""
    
    # claim = derived label for scanning (NOT just title)
    claim = _derive_claim_label(evidence_snippet, result.title)
    
    finding = {
        "id": finding_id,
        "claim": claim,
        "evidence_snippet": evidence_snippet,
        "page_title": result.title,
        "source_url": result.url,
        "retrieved_at": retrieved_at,
        "tier": "tier1_official" if is_tier1 else "tier2_reputable",
        "confidence": "high" if is_tier1 else "med",
    }
    
    # Add rq_id if provided (trace back to research question)
    if rq_id:
        finding["rq_id"] = rq_id
    
    # Add triage fields if available
    if triage:
        finding["triage_bucket"] = triage.bucket
        finding["triage_reason"] = triage.reason
    
    return finding


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
    max_results_per_question: int = 8,
    findings_per_question: int = 3,
    mark_sufficient: bool = False,
) -> ResearchRunResult:
    """
    Run research for all questions in research_snapshot.yaml.
    
    Calls Tavily once per question, stores answer_summary + top findings.
    
    Args:
        input_path: Path to input research_snapshot.yaml
        output_path: Path to write updated research_snapshot.yaml
        provider: Search provider ("tavily")
        max_results_per_question: Max search results to fetch (default 5)
        findings_per_question: Max findings to keep per question (default 5)
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
    
    # Get triage client (optional - triage is advisory)
    triage_client = _get_triage_client()
    build_id = data.get("build_id", "")
    
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
    new_answers: List[dict] = []
    questions_processed = 0
    
    for question in data.get("research_questions", []):
        rq_id = question.get("id", "")
        query = _build_query(question)
        question_text = question.get("question", "")
        if not query:
            continue
        
        try:
            response: SearchResponse = client.search(query, max_results=max_results_per_question)
        except Exception as e:
            # Log but continue - don't fail entire run for one question
            print(f"  ⚠️  Search failed for '{query[:50]}...': {e}")
            continue
        
        questions_processed += 1
        
        # Store per-question answer_summary (Tavily's AI synthesis)
        # No sources here - findings is the source of truth for evidence
        new_answers.append({
            "rq_id": rq_id,
            "question": question_text,
            "answer_summary": response.answer_summary or "",
        })
        
        # Create findings from top results (with non-empty snippets)
        count = 0
        for result in response.results:
            if count >= findings_per_question:
                break
            # Only filter completely empty snippets
            if not result.snippet or not result.snippet.strip():
                continue
            
            # Run triage if client available
            triage = None
            if triage_client:
                triage = _triage_finding(
                    client=triage_client,
                    question=question_text,
                    page_title=result.title,
                    source_url=result.url,
                    evidence_snippet=result.snippet,
                    run_id=build_id,
                )
            
            finding_id = f"F{next_finding_num}"
            finding = _result_to_finding(result, finding_id, now, rq_id=rq_id, triage=triage)
            new_findings.append(finding)
            next_finding_num += 1
            count += 1
    
    # Combine findings
    all_findings = existing_findings + new_findings
    
    # Sort new findings by triage within each RQ (keep=true first, then high→normal→low)
    if triage_client and new_findings:
        all_findings = existing_findings + _sort_findings_by_triage(new_findings)
    
    # Store answers (replace any existing)
    data["answers"] = new_answers
    
    # Update data
    data["retrieved_at"] = now
    data["state_version"] = data.get("state_version", 0) + 1
    data["findings"] = all_findings
    
    # Update sufficiency if requested
    if mark_sufficient:
        data["sufficiency"] = {
            "status": "sufficient",
            "rationale": f"Research conducted on {now}. {len(new_answers)} answers, {len(all_findings)} findings.",
        }
    elif data.get("sufficiency", {}).get("status") == "unknown":
        # Keep as unknown but update rationale
        data["sufficiency"]["rationale"] = (
            f"Research conducted on {now}. "
            f"{len(new_answers)} answers, {len(all_findings)} findings. "
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

