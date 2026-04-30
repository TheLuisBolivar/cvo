"""
PDF parser: converts a CV PDF into the standard JSON schema (same shape as
examples/cv_example.json).

Pipeline:
    PDF → raw text (pypdf) → LLM (structures the text) → dict JSON

The LLM client is duck-typed: any object with .call_json() works
(ClaudeClient or DeepSeekClient today, any future provider tomorrow).

Programmatic usage:
    from cv_optimizer import parse_pdf_to_cv, DeepSeekClient
    client = DeepSeekClient()
    cv_dict = parse_pdf_to_cv("my_cv.pdf", client)

CLI usage: see pdf_to_cv.py at the project root.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

from .prompts import CV_PARSER_PROMPT, CV_PARSER_SYSTEM


# Char limit on the text we send to the LLM.
# A typical CV is 5–15k chars; 60k covers long CVs without blowing tokens.
MAX_PDF_CHARS = 60_000


class _LLMClient(Protocol):
    """Any client with call_json works (Claude, DeepSeek, …)."""
    def call_json(
        self,
        user_prompt: str,
        system: str | None = ...,
        max_tokens: int = ...,
        temperature: float = ...,
    ) -> dict[str, Any]: ...


def extract_pdf_text(pdf_path: str | Path) -> str:
    """Extract plain text from a PDF, page by page."""
    try:
        from pypdf import PdfReader
    except ImportError as e:
        raise RuntimeError(
            "Missing dependency 'pypdf'. Install it with: pip install pypdf"
        ) from e

    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF does not exist: {pdf_path}")
    if pdf_path.suffix.lower() != ".pdf":
        raise ValueError(f"File does not look like a PDF: {pdf_path}")

    reader = PdfReader(str(pdf_path))
    pages: list[str] = []
    for i, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception as e:
            text = f"[error extracting page {i}: {e}]"
        pages.append(text.strip())

    full_text = "\n\n".join(p for p in pages if p)
    if not full_text.strip():
        raise ValueError(
            f"Could not extract text from PDF {pdf_path}. "
            "It may be a scanned PDF (would need OCR) or password-protected."
        )
    return full_text


def text_to_cv_json(text: str, client: _LLMClient) -> dict[str, Any]:
    """Send raw text to the LLM and return the structured CV dict."""
    text = text.strip()
    if len(text) > MAX_PDF_CHARS:
        text = text[:MAX_PDF_CHARS]

    prompt = CV_PARSER_PROMPT.format(pdf_text=text)
    return client.call_json(
        prompt,
        system=CV_PARSER_SYSTEM,
        max_tokens=8000,
        temperature=0.1,
    )


def parse_pdf_to_cv(
    pdf_path: str | Path,
    client: _LLMClient,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    """
    Full pipeline: PDF → CV JSON dict. If output_path is given, also writes
    the JSON to disk with indent=2 and utf-8 encoding.
    """
    text = extract_pdf_text(pdf_path)
    cv_dict = text_to_cv_json(text, client)

    if output_path is not None:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(cv_dict, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    return cv_dict
