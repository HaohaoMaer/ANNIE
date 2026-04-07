"""Image Reader Tool - Reads images and extracts text using OCR.

Used for reading clue images in murder mystery scenarios.
"""

from __future__ import annotations

import logging
import warnings
from pathlib import Path
from typing import Any

from annie.npc.tools.base_tool import BaseTool

logger = logging.getLogger(__name__)

# Suppress PyTorch pin_memory warning at the module level so it doesn't fire
# for every DataLoader batch inside easyocr.readtext().
warnings.filterwarnings("ignore", category=UserWarning, message=".*pin_memory.*")

_ocr_reader = None


def _get_ocr_reader():
    """Lazy load OCR reader to avoid slow startup (shared across all tool instances)."""
    global _ocr_reader
    if _ocr_reader is None:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            import easyocr
            _ocr_reader = easyocr.Reader(['ch_sim', 'en'], gpu=False, verbose=False)
    return _ocr_reader


class ImageReaderTool(BaseTool):
    """Tool for reading images and extracting text content using OCR."""

    name = "image_reader"
    description = (
        "Reads images (jpg/png) and extracts text content using OCR. "
        "Supports Chinese and English text. "
        "Can read single image or batch read entire folder. "
        "Use this tool when you need to extract text from clue images."
    )

    def __init__(self) -> None:
        self._reader = None

    @property
    def reader(self):
        """Lazy load OCR reader."""
        if self._reader is None:
            self._reader = _get_ocr_reader()
        return self._reader

    def execute(self, context: dict) -> dict:
        """Execute image reading operation.

        Args:
            context: Dict with keys:
                - 'task': str, the task description
                - 'npc_name': str, the NPC's name
                - 'image_path': str (optional), path to single image
                - 'folder_path': str (optional), path to folder of images
                - 'recursive': bool (optional), search subfolders (default: False)

        Returns:
            Dict with:
                - 'success': bool
                - 'text': str, extracted text
                - 'images_processed': int, number of images processed
                - 'results': list, detailed results per image
                - 'error': str (if failed)
        """
        image_path = context.get("image_path")
        folder_path = context.get("folder_path")
        recursive = context.get("recursive", False)

        if image_path:
            return self._read_single_image(image_path)
        elif folder_path:
            return self._read_folder(folder_path, recursive)
        else:
            return self._error_result("No image path or folder path provided")

    def _read_single_image(self, image_path: str) -> dict:
        """Read a single image file."""
        path = Path(image_path)
        if not path.exists():
            return self._error_result(f"Image file not found: {image_path}")

        if path.suffix.lower() not in [".jpg", ".jpeg", ".png"]:
            return self._error_result(f"Unsupported image format: {path.suffix}")

        try:
            results = self.reader.readtext(str(path))
            text_lines = [item[1] for item in results if item[1].strip()]
            extracted_text = "\n".join(text_lines)

            return {
                "success": True,
                "text": extracted_text,
                "images_processed": 1,
                "results": [{
                    "file": path.name,
                    "text": extracted_text,
                    "confidence": sum(item[2] for item in results) / len(results) if results else 0.0,
                }],
            }

        except Exception as e:
            return self._error_result(f"Failed to read image: {str(e)}")

    def _read_folder(self, folder_path: str, recursive: bool = False) -> dict:
        """Read all images in a folder."""
        path = Path(folder_path)
        if not path.exists():
            return self._error_result(f"Folder not found: {folder_path}")

        if recursive:
            image_files = list(path.rglob("*.jpg")) + list(path.rglob("*.jpeg")) + list(path.rglob("*.png"))
        else:
            image_files = list(path.glob("*.jpg")) + list(path.glob("*.jpeg")) + list(path.glob("*.png"))

        image_files = sorted(set(image_files))

        if not image_files:
            return self._error_result(f"No image files found in: {folder_path}")

        all_results = []
        all_text = []

        for img_path in image_files:
            try:
                results = self.reader.readtext(str(img_path))
                text_lines = [item[1] for item in results if item[1].strip()]
                extracted_text = "\n".join(text_lines)

                all_results.append({
                    "file": img_path.name,
                    "path": str(img_path),
                    "text": extracted_text,
                    "confidence": sum(item[2] for item in results) / len(results) if results else 0.0,
                })

                if extracted_text.strip():
                    all_text.append(f"=== {img_path.name} ===\n{extracted_text}")

            except Exception as e:
                all_results.append({
                    "file": img_path.name,
                    "path": str(img_path),
                    "error": str(e),
                })

        return {
            "success": True,
            "text": "\n\n".join(all_text),
            "images_processed": len(all_results),
            "results": all_results,
        }

    def _error_result(self, error: str) -> dict[str, Any]:
        """Create an error result dict."""
        return {
            "success": False,
            "text": "",
            "images_processed": 0,
            "results": [],
            "error": error,
        }

    def get_image_info(self, image_path: str) -> dict[str, Any]:
        """Get basic information about an image without OCR.

        Args:
            image_path: Path to the image.

        Returns:
            Dict with image metadata.
        """
        from PIL import Image

        path = Path(image_path)
        if not path.exists():
            return {"error": "File not found"}

        try:
            with Image.open(path) as img:
                return {
                    "file": path.name,
                    "format": img.format,
                    "size": img.size,
                    "mode": img.mode,
                    "file_size": path.stat().st_size,
                }
        except Exception as e:
            return {"error": str(e)}
