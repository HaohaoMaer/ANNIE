"""PDF Reader Tool - Reads and extracts content from PDF script files.

Used by NPCs to read their character scripts and related materials.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pypdf import PdfReader

from annie.npc.tools.base_tool import BaseTool


class PDFReaderTool(BaseTool):
    """Tool for reading PDF files, particularly script documents."""

    name = "pdf_reader"
    description = (
        "Reads and extracts text content from PDF files. "
        "Can read entire document, specific pages, or search for keywords. "
        "Use this tool when you need to access script content or document information."
    )

    def __init__(self) -> None:
        self._cached_content: dict[str, str] = {}

    def execute(self, context: dict) -> dict:
        """Execute PDF reading operation.

        Args:
            context: Dict with keys:
                - 'task': str, the task description
                - 'npc_name': str, the NPC's name
                - 'pdf_path': str (optional), path to PDF file
                - 'operation': str (optional), one of 'full', 'pages', 'search'
                - 'page_start': int (optional), start page for 'pages' operation
                - 'page_end': int (optional), end page for 'pages' operation
                - 'keywords': list[str] (optional), keywords for 'search' operation

        Returns:
            Dict with:
                - 'success': bool
                - 'content': str, extracted text
                - 'page_count': int, total pages in document
                - 'operation': str, operation performed
                - 'error': str (if failed)
        """
        pdf_path = context.get("pdf_path")
        operation = context.get("operation", "full")

        if not pdf_path:
            return self._error_result("No PDF path provided")

        path = Path(pdf_path)
        if not path.exists():
            return self._error_result(f"PDF file not found: {pdf_path}")

        try:
            reader = PdfReader(path)
            page_count = len(reader.pages)

            if operation == "full":
                content = self._read_full(reader)
            elif operation == "pages":
                page_start = context.get("page_start", 0)
                page_end = context.get("page_end", page_count)
                content = self._read_pages(reader, page_start, page_end)
            elif operation == "search":
                keywords = context.get("keywords", [])
                content = self._search_keywords(reader, keywords)
            else:
                return self._error_result(f"Unknown operation: {operation}")

            return {
                "success": True,
                "content": content,
                "page_count": page_count,
                "operation": operation,
                "pdf_path": str(path),
            }

        except Exception as e:
            return self._error_result(f"Failed to read PDF: {str(e)}")

    def _read_full(self, reader: PdfReader) -> str:
        """Read entire PDF content."""
        pages = []
        for i, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            pages.append(f"--- Page {i + 1} ---\n{text}")
        return "\n\n".join(pages)

    def _read_pages(self, reader: PdfReader, start: int, end: int) -> str:
        """Read specific page range."""
        pages = []
        for i in range(max(0, start), min(end, len(reader.pages))):
            text = reader.pages[i].extract_text() or ""
            pages.append(f"--- Page {i + 1} ---\n{text}")
        return "\n\n".join(pages)

    def _search_keywords(self, reader: PdfReader, keywords: list[str]) -> str:
        """Search for keywords and return matching pages."""
        if not keywords:
            return "No keywords provided for search"

        matches = []
        keywords_lower = [k.lower() for k in keywords]

        for i, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            text_lower = text.lower()

            found_keywords = []
            for kw, kw_lower in zip(keywords, keywords_lower):
                if kw_lower in text_lower:
                    found_keywords.append(kw)

            if found_keywords:
                matches.append(
                    f"--- Page {i + 1} (found: {', '.join(found_keywords)}) ---\n{text}"
                )

        if not matches:
            return f"No matches found for keywords: {', '.join(keywords)}"

        return "\n\n".join(matches)

    def _error_result(self, error: str) -> dict[str, Any]:
        """Create an error result dict."""
        return {
            "success": False,
            "content": "",
            "page_count": 0,
            "operation": "error",
            "error": error,
        }

    def get_toc(self, pdf_path: str) -> list[dict[str, Any]]:
        """Get table of contents if available.

        Args:
            pdf_path: Path to PDF file.

        Returns:
            List of TOC entries with 'title' and 'page' keys.
        """
        path = Path(pdf_path)
        if not path.exists():
            return []

        try:
            reader = PdfReader(path)
            toc = reader.outline

            if not toc:
                return []

            result = []
            for item in toc:
                if isinstance(item, list):
                    continue
                if hasattr(item, "title") and hasattr(item, "page"):
                    result.append(
                        {
                            "title": item.title,
                            "page": reader.get_destination_page_number(item) + 1,
                        }
                    )

            return result

        except Exception:
            return []
