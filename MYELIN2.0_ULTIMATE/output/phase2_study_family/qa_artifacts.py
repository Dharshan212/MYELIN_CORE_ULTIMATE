"""Read-only visual and structural QA for the synthetic deliverables."""
from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parent
sheet = pymupdf.open(ROOT / "MYELIN_Phase2_Analytics_Sheet_SYNTHETIC.pdf")
poster = pymupdf.open(ROOT / "MYELIN_Phase2_Poster_A3_SYNTHETIC.pdf")
print("Analytics pages:", len(sheet))
print("Analytics TOC:", sheet.get_toc())
assert any("SECANT" in row[1] for row in sheet.get_toc())
assert any("COSECANT" in row[1] for row in sheet.get_toc())
assert all("SYNTHETIC VALIDATION FIXTURE" in page.get_text() for page in sheet)
assert all(abs(page.rect.width - 595.28) < 1 and abs(page.rect.height - 841.89) < 1 for page in sheet)
for number, page in enumerate(sheet, 1):
    for x0, y0, x1, y1, word, *_ in page.get_text("words"):
        assert x0 >= 0 and y0 >= 0 and x1 <= page.rect.width and y1 <= page.rect.height, (number, word)

cols = 3
thumb_w = 310
thumb_h = 440
rows = (len(sheet) + cols - 1) // cols
contact = Image.new("RGB", (cols * thumb_w, rows * (thumb_h + 26)), "#161d28")
draw = ImageDraw.Draw(contact)
for i, page in enumerate(sheet):
    pix = page.get_pixmap(matrix=pymupdf.Matrix(0.5, 0.5), alpha=False)
    image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    image.thumbnail((thumb_w - 12, thumb_h - 12))
    x = (i % cols) * thumb_w + (thumb_w - image.width) // 2
    y = (i // cols) * (thumb_h + 26) + 3
    contact.paste(image, (x, y))
    draw.text(((i % cols) * thumb_w + 8, y + thumb_h), f"Page {i + 1}", fill="white")
    text = page.get_text()
    if "STUDY MODE / Study Context" in text or "SECANT episode records" in text or "COSECANT break records" in text:
        pix = page.get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5), alpha=False)
        pix.save(ROOT / f"qa_analytics_page_{i + 1}.png")
contact.save(ROOT / "qa_analytics_contact.png")

assert len(poster) == 1
print("Poster PDF MediaBox:", tuple(round(v, 1) for v in poster[0].rect))
assert abs(poster[0].rect.width - 1190.55) < 1 and abs(poster[0].rect.height - 841.89) < 1
pix = poster[0].get_pixmap(matrix=pymupdf.Matrix(1.0, 1.0), alpha=False)
pix.save(ROOT / "qa_poster_pdf.png")
with Image.open(ROOT / "MYELIN_Phase2_Poster_300DPI_SYNTHETIC.jpg") as jpg:
    print("Poster JPG:", jpg.size, jpg.info.get("dpi"))
    assert jpg.size == (4961, 3508)
with Image.open(ROOT / "MYELIN_Phase2_Poster_1600x850_SYNTHETIC.png") as png:
    assert png.size == (1600, 850)
