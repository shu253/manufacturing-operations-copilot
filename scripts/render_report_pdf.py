from __future__ import annotations

import json
import sys
import unicodedata
from io import BytesIO
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


def register_chinese_font() -> str:
    font_name = "ReportChinese"
    font_candidates = [
        Path("C:/Windows/Fonts/simhei.ttf"),
        Path("C:/Windows/Fonts/Deng.ttf"),
        Path("C:/Windows/Fonts/simfang.ttf"),
    ]
    for font_path in font_candidates:
        if font_path.exists():
            pdfmetrics.registerFont(TTFont(font_name, str(font_path)))
            return font_name
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    return "STSong-Light"


def wrap_text(text: str, max_units: int = 84) -> list[str]:
    if not text:
        return [""]
    wrapped: list[str] = []
    current: list[str] = []
    units = 0
    for character in text:
        width = 2 if unicodedata.east_asian_width(character) in {"W", "F", "A"} else 1
        if current and units + width > max_units:
            wrapped.append("".join(current))
            current = []
            units = 0
        current.append(character)
        units += width
    if current:
        wrapped.append("".join(current))
    return wrapped


def render(title: str, lines: list[str]) -> bytes:
    output = BytesIO()
    font_name = register_chinese_font()
    page_width, page_height = A4
    pdf = canvas.Canvas(output, pagesize=A4, pageCompression=1)
    pdf.setTitle(title)
    left_margin = 52
    top_margin = 54
    bottom_margin = 50

    def start_page() -> float:
        pdf.setFont(font_name, 9)
        pdf.setFillColorRGB(0.42, 0.49, 0.56)
        pdf.drawRightString(page_width - left_margin, 28, f"第 {pdf.getPageNumber()} 页")
        return page_height - top_margin

    y = start_page()
    pdf.setFillColorRGB(0.08, 0.20, 0.31)
    pdf.setFont(font_name, 18)
    pdf.drawString(left_margin, y, title)
    y -= 34

    for line in lines:
        is_section = line in {"核心指标", "管理动作"}
        font_size = 13 if is_section else 11
        line_height = 24 if is_section else 20
        if is_section:
            y -= 4
        for wrapped_line in wrap_text(line):
            if y < bottom_margin:
                pdf.showPage()
                y = start_page()
            pdf.setFillColorRGB(0.08, 0.20, 0.31)
            pdf.setFont(font_name, font_size)
            pdf.drawString(left_margin, y, wrapped_line)
            y -= line_height

    pdf.save()
    return output.getvalue()


def main() -> None:
    payload = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    sys.stdout.buffer.write(render(payload["title"], payload["lines"]))


if __name__ == "__main__":
    main()
