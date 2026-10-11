import json
import re
from dataclasses import dataclass
from pathlib import Path

from freightcopilot.config import DATA_DIR


@dataclass(frozen=True)
class SourceDocument:
    document_id: str
    source_id: str
    content: str


def extract_source_id(content: str) -> str:
    match = re.search(r"^Document ID:\s*(\S+)", content, flags=re.MULTILINE)
    if not match:
        raise ValueError("Document is missing a 'Document ID:' line")
    return match.group(1)


def load_documents(data_dir: Path = DATA_DIR) -> list[SourceDocument]:
    documents = []
    for path in sorted(data_dir.glob("*.md")):
        content = path.read_text(encoding="utf-8-sig")
        documents.append(
            SourceDocument(
                document_id=path.stem,
                source_id=extract_source_id(content),
                content=content,
            )
        )
    return documents


def load_questions(data_dir: Path = DATA_DIR) -> list[dict[str, str]]:
    path = data_dir / "questions.json"
    return json.loads(path.read_text(encoding="utf-8-sig"))
