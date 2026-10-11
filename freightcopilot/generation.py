from collections.abc import Iterator
from functools import lru_cache

from google import genai
from google.genai import types

from freightcopilot.config import GENERATION_MODEL, get_gemini_api_key
from freightcopilot.schemas import RetrievedChunk


@lru_cache(maxsize=1)
def get_gemini_client() -> genai.Client:
    return genai.Client(api_key=get_gemini_api_key())


def build_rag_prompt(question: str, evidence: list[RetrievedChunk]) -> str:
    evidence_text = "\n\n".join(
        f"[{chunk.source_id}]\n{chunk.content}" for chunk in evidence
    )
    return f"""Answer using only the evidence below.
Cite factual claims with the matching source ID in square brackets.
If the evidence does not answer the question, say so.
Do not invent facts or citations.

Evidence:
{evidence_text}

Question: {question}
"""


def stream_answer(prompt: str) -> Iterator[str]:
    stream = get_gemini_client().models.generate_content_stream(
        model=GENERATION_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                disable=True
            )
        ),
    )
    for chunk in stream:
        if chunk.text:
            yield chunk.text


def generate_answer(prompt: str) -> str:
    response = get_gemini_client().models.generate_content(
        model=GENERATION_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                disable=True
            )
        ),
    )
    return response.text or ""
