"""Extract metadata (topic, keywords) from text chunks using Claude Haiku."""

import json

from langsmith import traceable

from services.llm import Task, complete

EXTRACTION_PROMPT = """Extract metadata from the following text chunk.
Return ONLY valid JSON with exactly these fields:
- "topic": a short phrase (2-5 words) describing the main topic
- "keywords": a list of 3-8 relevant keywords (lowercase)

Text chunk:
{chunk}"""


@traceable(name="extract_metadata", run_type="chain")
def extract_metadata(chunk: str) -> dict:
    """Extract topic and keywords from a chunk using Claude Haiku."""
    response = complete(
        task=Task.METADATA,
        messages=[{"role": "user", "content": EXTRACTION_PROMPT.format(chunk=chunk)}],
        max_tokens=256,
    )

    try:
        text = response.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        result = json.loads(text)
        return {
            "topic": str(result.get("topic", "unknown")),
            "keywords": [str(k).lower() for k in result.get("keywords", [])],
        }
    except (json.JSONDecodeError, IndexError, KeyError):
        return {"topic": "unknown", "keywords": []}
