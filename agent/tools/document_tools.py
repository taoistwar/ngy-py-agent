"""Document parsing tools."""

from io import BytesIO
from typing import Dict

import PyPDF2
import requests


def parse_pdf(url: str) -> Dict:
    """
    Parse a PDF document from URL or local file
    """
    try:
        # Check if it's a local file
        if url.startswith("file://") or url.startswith("/") or url.startswith("./"):
            # Local file
            file_path = url.replace("file://", "")
            with open(file_path, "rb") as f:
                pdf_content = f.read()
        else:
            # Remote URL
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            pdf_content = response.content

        # Parse PDF
        pdf_file = BytesIO(pdf_content)
        pdf_reader = PyPDF2.PdfReader(pdf_file)

        text_content = []
        for page_num, page in enumerate(pdf_reader.pages, 1):
            text = page.extract_text()
            text_content.append(
                {
                    "page": page_num,
                    "text": text[:1000],  # Limit text per page
                }
            )

        return {
            "url": url,
            "num_pages": len(pdf_reader.pages),
            "content": text_content[:5],  # Limit to first 5 pages
            "success": True,
        }
    except Exception as e:
        return {"error": str(e), "success": False}
