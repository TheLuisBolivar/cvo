"""cv-optimizer: tailor your CV to a specific job offer using LLMs."""

from .client import ClaudeClient
from .deepseek_client import DeepSeekClient
from .openai_client import OpenAIClient
from .gemini_client import GeminiClient
from .models import CV, Experience
from .providers import (
    LLMClient,
    PROVIDERS,
    PROVIDER_ORDER,
    has_api_key,
    make_client,
    provider_meta,
    resolve_active_provider,
)
from .analyzer import analyze_offer
from .aligner import align_experience, align_all
from .summary import generate_summary, reorder_skills
from .generator import generate_markdown, generate_report, build_optimized_cv_dict
from .exporters import export_all, parse_format_list, SUPPORTED_FORMATS
from .pdf_parser import parse_pdf_to_cv, extract_pdf_text, text_to_cv_json
from .docx_parser import parse_docx_to_cv, extract_docx_text
from .setup_wizard import run_wizard, ensure_provider_configured

__all__ = [
    "ClaudeClient",
    "DeepSeekClient",
    "OpenAIClient",
    "GeminiClient",
    "CV",
    "Experience",
    "LLMClient",
    "PROVIDERS",
    "PROVIDER_ORDER",
    "has_api_key",
    "make_client",
    "provider_meta",
    "resolve_active_provider",
    "analyze_offer",
    "align_experience",
    "align_all",
    "generate_summary",
    "reorder_skills",
    "generate_markdown",
    "generate_report",
    "build_optimized_cv_dict",
    "export_all",
    "parse_format_list",
    "SUPPORTED_FORMATS",
    "parse_pdf_to_cv",
    "extract_pdf_text",
    "text_to_cv_json",
    "parse_docx_to_cv",
    "extract_docx_text",
    "run_wizard",
    "ensure_provider_configured",
]
