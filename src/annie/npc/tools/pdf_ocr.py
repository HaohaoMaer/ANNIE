"""PDF OCR Tool - Reads image-based PDFs using OCR.

Many Chinese PDFs are image-based, not text-based.
This tool converts PDF pages to images and uses OCR to extract text.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from annie.npc.tools.base_tool import BaseTool
from annie.npc.tools.image_reader import _get_ocr_reader  # shared singleton

logger = logging.getLogger(__name__)


class PDFOCRTool(BaseTool):
    """Tool for reading image-based PDFs using OCR."""

    name = "pdf_ocr"
    description = (
        "Reads image-based PDF files using OCR. "
        "Use this when the PDF contains images of text rather than selectable text. "
        "Supports Chinese and English text extraction."
    )

    def __init__(self) -> None:
        pass  # EasyOCR reader is a shared singleton from image_reader

    @property
    def ocr_reader(self):
        """Return the shared EasyOCR reader singleton."""
        return _get_ocr_reader()

    def execute(self, context: dict) -> dict:
        """Execute PDF OCR reading operation.

        Args:
            context: Dict with keys:
                - 'task': str, the task description
                - 'npc_name': str, the NPC's name
                - 'pdf_path': str, path to PDF file

        Returns:
            Dict with:
                - 'success': bool
                - 'content': str, extracted text
                - 'page_count': int, total pages
                - 'error': str (if failed)
        """
        pdf_path = context.get("pdf_path")

        if not pdf_path:
            return self._error_result("No PDF path provided")

        path = Path(pdf_path)
        if not path.exists():
            return self._error_result(f"PDF file not found: {pdf_path}")

        try:
            reader = PdfReader(path)
            page_count = len(reader.pages)

            text_content = reader.pages[0].extract_text() or ""
            
            if text_content.strip() and len(text_content) > 50:
                logger.info(f"PDF has text content, using standard extraction")
                pages = []
                for i, page in enumerate(reader.pages):
                    text = page.extract_text() or ""
                    if text.strip():
                        pages.append(f"--- Page {i + 1} ---\n{text}")
                content = "\n\n".join(pages)
                
                return {
                    "success": True,
                    "content": content,
                    "page_count": page_count,
                    "method": "text_extraction",
                }

            logger.info(f"PDF is image-based, using OCR")
            return self._ocr_pdf(path, reader)

        except Exception as e:
            return self._error_result(f"Failed to read PDF: {str(e)}")

    def _ocr_pdf(self, path: Path, reader: PdfReader) -> dict:
        """Convert PDF pages to images and perform OCR."""
        try:
            import pdf2image
        except ImportError:
            logger.warning("pdf2image not installed, trying alternative method")
            return self._ocr_pdf_alternative(path, reader)

        try:
            pages_text = []
            page_count = len(reader.pages)

            logger.info(f"Converting {page_count} PDF pages to images...")

            images = pdf2image.convert_from_path(
                str(path),
                dpi=200,
                first_page=1,
                last_page=page_count,
            )

            for i, image in enumerate(images):
                logger.info(f"OCR processing page {i + 1}/{page_count}")
                
                import numpy as np
                img_array = np.array(image)
                
                results = self.ocr_reader.readtext(img_array)
                text_lines = [item[1] for item in results if item[1].strip()]
                page_text = "\n".join(text_lines)
                
                if page_text.strip():
                    pages_text.append(f"--- Page {i + 1} ---\n{page_text}")

            content = "\n\n".join(pages_text)

            return {
                "success": True,
                "content": content,
                "page_count": page_count,
                "method": "ocr",
            }

        except Exception as e:
            logger.error(f"OCR failed: {e}")
            return self._error_result(f"OCR failed: {str(e)}")

    def _ocr_pdf_alternative(self, path: Path, reader: PdfReader) -> dict:
        """Alternative OCR method using fitz (PyMuPDF)."""
        try:
            import fitz
        except ImportError:
            return self._error_result(
                "Neither pdf2image nor fitz is installed. "
                "Please install: pip install pdf2image PyMuPDF"
            )

        try:
            doc = fitz.open(str(path))
            pages_text = []
            page_count = len(doc)

            logger.info(f"Using fitz to OCR {page_count} pages...")

            for page_num in range(page_count):
                page = doc[page_num]
                
                pix = page.get_pixmap(dpi=200)
                img_data = pix.tobytes("png")
                
                import io
                from PIL import Image
                img = Image.open(io.BytesIO(img_data))
                
                import numpy as np
                img_array = np.array(img)
                
                results = self.ocr_reader.readtext(img_array)
                text_lines = [item[1] for item in results if item[1].strip()]
                page_text = "\n".join(text_lines)
                
                if page_text.strip():
                    pages_text.append(f"--- Page {page_num + 1} ---\n{page_text}")

            doc.close()
            content = "\n\n".join(pages_text)

            return {
                "success": True,
                "content": content,
                "page_count": page_count,
                "method": "ocr_fitz",
            }

        except Exception as e:
            logger.error(f"Alternative OCR failed: {e}")
            return self._error_result(f"OCR failed: {str(e)}")

    def _error_result(self, error: str) -> dict[str, Any]:
        """Create an error result dict."""
        return {
            "success": False,
            "content": "",
            "page_count": 0,
            "error": error,
        }
