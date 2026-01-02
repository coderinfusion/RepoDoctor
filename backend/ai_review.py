import os
import json
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

SYSTEM_PROMPT = """You are RepoDoctor, a strict senior engineer.

Rules:
- Use ONLY the provided file tree + key file contents as evidence.
- If you can't verify something from the provided data, do NOT claim it.
- Produce EXACTLY 5 issues in top_5.
- Every issue must include evidence (file path + short snippet or concrete clue).
- Every issue must include a concrete fix (specific steps or edits).

Return ONLY valid JSON matching the schema. No markdown.
"""

REVIEW_SCHEMA = {
  "type": "object",
  "additionalProperties": False,
  "properties": {
    "one_liner": {"type": "string"},
    "top_5": {
      "type": "array",
      "minItems": 5,
      "maxItems": 5,
      "items": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
          "title": {"type": "string"},
          "severity": {"type": "string", "enum": ["critical", "high", "medium", "low"]},
          "evidence": {"type": "string"},
          "fix": {"type": "string"}
        },
        "required": ["title", "severity", "evidence", "fix"]
      }
    },
    "next_7_days_plan": {
      "type": "array",
      "items": {"type": "string"}
    }
  },
  "required": ["one_liner", "top_5", "next_7_days_plan"]
}


def call_ai_review(repo_url: str, file_tree: list[str], key_files: dict[str, str]) -> dict:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY missing. Put it in repodoctor/.env")

    client = OpenAI(api_key=api_key)

    file_tree_text = "\n".join(file_tree[:200])

    key_file_snips = {}
    for name, content in key_files.items():
        if content == "DIRECTORY_PRESENT":
            key_file_snips[name] = "DIRECTORY_PRESENT"
        else:
            key_file_snips[name] = content[:4000]

    user_payload = {
        "repo_url": repo_url,
        "file_tree": file_tree_text,
        "key_files": key_file_snips
    }

    resp = client.responses.create(
        model="gpt-4o-mini",
        input=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(user_payload)}
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "repo_review",
                "schema": REVIEW_SCHEMA,
                "strict": True
            }
        }
    )

    return json.loads(resp.output_text)
