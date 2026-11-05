"""Build the English PDF manuals from checked-in Markdown sources.

Run from the checkout root: uv run --group docs python tools/build_docs.py
No network access, browser, or paid software is required.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import textwrap
from datetime import date
from html import escape
from pathlib import Path

from reportlab import rl_config
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Flowable,
    Frame,
    HRFlowable,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Preformatted,
    Spacer,
)
from reportlab.platypus.tableofcontents import TableOfContents

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
OUTPUT = DOCS / "pdf"
NAVY = colors.HexColor("#10253B")
TEAL = colors.HexColor("#087D83")
GRAY = colors.HexColor("#485567")
LIGHT = colors.HexColor("#E7EEF2")
FILES = [
    ("setup-and-operations.md", "01-setup-and-operations.pdf"),
    ("code-explained.md", "02-code-explained.pdf"),
    ("scrapers/bet365.md", "03-bet365-scraper-setup.pdf"),
    ("scrapers/stake.md", "04-stake-scraper-setup.pdf"),
    ("scrapers/1xbet.md", "05-1xbet-scraper-setup.pdf"),
    ("scrapers/marathonbet.md", "06-marathonbet-scraper-setup.pdf"),
    ("scrapers/bet105.md", "07-bet105-scraper-setup.pdf"),
]


def font_names() -> tuple[str, str, str, str]:
    candidates = [Path("/usr/share/fonts/truetype/dejavu"), ROOT / "tools" / "fonts"]
    for folder in candidates:
        paths = [folder / f"DejaVuSans{suffix}.ttf" for suffix in ("", "-Bold", "-Oblique")]
        mono = folder / "DejaVuSansMono.ttf"
        if all(p.exists() for p in paths) and mono.exists():
            for name, path in zip(("GuideSans", "GuideSans-Bold", "GuideSans-Italic", "GuideMono"), [*paths, mono]):
                pdfmetrics.registerFont(TTFont(name, str(path)))
            pdfmetrics.registerFontFamily("GuideSans", normal="GuideSans", bold="GuideSans-Bold", italic="GuideSans-Italic", boldItalic="GuideSans-Bold")
            return "GuideSans", "GuideSans-Bold", "GuideSans-Italic", "GuideMono"
    return "Helvetica", "Helvetica-Bold", "Helvetica-Oblique", "Courier"


REGULAR, BOLD, ITALIC, MONO = font_names()


def styles():
    result = getSampleStyleSheet()
    result.add(ParagraphStyle(name="GuideBody", fontName=REGULAR, fontSize=9.3, leading=14.2, spaceAfter=7, textColor=NAVY, allowWidows=0, allowOrphans=0))
    result.add(ParagraphStyle(name="GuideBullet", parent=result["GuideBody"], leftIndent=12, firstLineIndent=-9, spaceAfter=5))
    result.add(ParagraphStyle(name="GuideH1", fontName=BOLD, fontSize=18, leading=23, spaceBefore=19, spaceAfter=10, textColor=NAVY, keepWithNext=True))
    result.add(ParagraphStyle(name="GuideH2", fontName=BOLD, fontSize=12, leading=17, spaceBefore=13, spaceAfter=7, textColor=TEAL, keepWithNext=True))
    result.add(ParagraphStyle(name="GuideH3", fontName=BOLD, fontSize=10.3, leading=15, spaceBefore=10, spaceAfter=6, textColor=NAVY, keepWithNext=True))
    result.add(ParagraphStyle(name="GuideCode", fontName=MONO, fontSize=7.3, leading=10.6, leftIndent=9, rightIndent=9, spaceBefore=5, spaceAfter=10, backColor=colors.HexColor("#F1F5F7"), borderPadding=8))
    result.add(ParagraphStyle(name="GuideSmall", parent=result["GuideBody"], fontSize=8, leading=12, textColor=GRAY))
    result.add(ParagraphStyle(name="GuideCover", fontName=BOLD, fontSize=29, leading=36, textColor=NAVY, spaceAfter=18))
    result.add(ParagraphStyle(name="GuideSubtitle", fontName=REGULAR, fontSize=12, leading=19, textColor=GRAY, spaceAfter=15))
    result.add(ParagraphStyle(name="GuideTOC", fontName=REGULAR, fontSize=9.3, leading=15, leftIndent=0, firstLineIndent=0, spaceBefore=5, textColor=NAVY))
    result.add(ParagraphStyle(name="GuideTOC2", parent=result["GuideTOC"], leftIndent=14, fontSize=8.5, leading=13, spaceBefore=2))
    return result


STYLES = styles()


def inline(value: str) -> str:
    # Protect code spans first, then escape all user-controlled markup. Only the
    # deliberately generated ReportLab tags below may reach Paragraph.
    segments = re.split(r"(`[^`]+`)", value)
    output = []
    for segment in segments:
        if segment.startswith("`") and segment.endswith("`"):
            output.append(f'<font name="{MONO}" size="8.2">{escape(segment[1:-1])}</font>')
            continue
        safe = escape(segment)
        safe = re.sub(r"\[([^\]]+)\]\((https?://[^\s)]+)\)", r'<link href="\2" color="#087D83">\1</link>', safe)
        safe = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", safe)
        output.append(safe)
    return "".join(output)


class GuideDocument(BaseDocTemplate):
    def __init__(self, filename: str, title: str):
        super().__init__(filename, pagesize=A4, leftMargin=21 * mm, rightMargin=21 * mm, topMargin=21 * mm, bottomMargin=21 * mm, title=title, author="Arbitrage Finder", subject="English development and operating manual")
        self.guide_title = title
        self.heading_index = 0
        frame = Frame(self.leftMargin, self.bottomMargin, self.width, self.height, id="normal", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
        self.addPageTemplates([PageTemplate(id="guide", frames=[frame], onPage=self.decorate)])

    def decorate(self, canvas, doc):
        canvas.saveState()
        if doc.page > 1:
            canvas.setStrokeColor(LIGHT)
            canvas.line(doc.leftMargin, A4[1] - 15.8 * mm, A4[0] - doc.rightMargin, A4[1] - 15.8 * mm)
            canvas.setFont(REGULAR, 7.4)
            canvas.setFillColor(GRAY)
            canvas.drawString(doc.leftMargin, A4[1] - 13.7 * mm, "ARBITRAGE FINDER")
            title = self.guide_title
            while pdfmetrics.stringWidth(title, REGULAR, 7.4) > 120 * mm:
                title = title[:-5] + "..."
            canvas.drawRightString(A4[0] - doc.rightMargin, A4[1] - 13.7 * mm, title)
        canvas.setFont(REGULAR, 7.4)
        canvas.setFillColor(GRAY)
        canvas.drawString(doc.leftMargin, 12 * mm, "Local, manual pre-match scanner | English edition")
        canvas.drawRightString(A4[0] - doc.rightMargin, 12 * mm, str(doc.page))
        canvas.restoreState()

    def afterFlowable(self, flowable):
        if isinstance(flowable, Paragraph) and flowable.style.name in ("GuideH1", "GuideH2"):
            text = flowable.getPlainText()
            level = 0 if flowable.style.name == "GuideH1" else 1
            key = getattr(flowable, "bookmark_key", None)
            if key:
                self.canv.bookmarkPage(key)
                self.canv.addOutlineEntry(text, key, level, closed=False)
                self.notify("TOCEntry", (level, text, self.page, key))


def code_blocks(lines: list[str]) -> list[Flowable]:
    # Wrap long source lines before Preformatted, whose default does not wrap.
    # Split long blocks into small chunks so ReportLab can place them safely.
    wrapped = []
    for line in lines:
        wrapped.extend(textwrap.wrap(line.expandtabs(4), width=90, replace_whitespace=False, drop_whitespace=False, break_long_words=True, break_on_hyphens=False) or [""])
    blocks = []
    for i in range(0, len(wrapped), 23):
        blocks.append(Preformatted("\n".join(wrapped[i:i + 23]), STYLES["GuideCode"]))
    return blocks


def markdown_story(source: str, source_path: Path) -> tuple[str, list[Flowable]]:
    lines = source.splitlines()
    title = next((line[2:].strip() for line in lines if line.startswith("# ")), source_path.stem)
    digest = hashlib.sha256(source.encode()).hexdigest()[:12]
    story: list[Flowable] = [Spacer(1, 29 * mm), Paragraph("ARBITRAGE FINDER", STYLES["GuideH2"]), Paragraph(inline(title), STYLES["GuideCover"]), HRFlowable(width="25%", thickness=4, color=TEAL, spaceAfter=20, hAlign="LEFT"), Paragraph("A practical guide to the software delivered in this repository.", STYLES["GuideSubtitle"]), Paragraph("Edition: 0.1.1 · 5 November 2026 · English", STYLES["GuideSmall"]), Paragraph(f"Source: docs/{escape(str(source_path.relative_to(DOCS)))}<br/>Content fingerprint: {digest}", STYLES["GuideSmall"]), Spacer(1, 12 * mm), Paragraph("Read the support status and limitations before using live odds. A working demo and parser tests do not establish that a bookmaker feed is currently accessible.", STYLES["GuideBody"]), PageBreak(), Paragraph("Contents", STYLES["GuideH1"])]
    toc = TableOfContents()
    toc.levelStyles = [STYLES["GuideTOC"], STYLES["GuideTOC2"]]
    toc.dotsMinLevel = 0
    story += [toc, PageBreak()]
    body: list[str] = []
    code: list[str] = []
    in_code = False
    skipped_title = False
    heading_number = 0

    def flush():
        if body:
            story.append(Paragraph(inline(" ".join(body)), STYLES["GuideBody"]))
            body.clear()

    for line in lines:
        if line.startswith("```"):
            flush()
            if in_code:
                story.extend(code_blocks(code))
                code.clear()
            in_code = not in_code
            continue
        if in_code:
            code.append(line)
            continue
        if not line.strip():
            flush()
            continue
        if line.startswith("# ") and not skipped_title:
            skipped_title = True
            continue
        match = re.match(r"^(#{1,4})\s+(.+)$", line)
        if match:
            flush()
            level = len(match.group(1))
            style = "GuideH1" if level <= 2 else "GuideH2" if level == 3 else "GuideH3"
            paragraph = Paragraph(inline(match.group(2)), STYLES[style])
            paragraph.bookmark_key = f"section-{heading_number}"
            heading_number += 1
            story.append(paragraph)
            continue
        if line.strip() == "---":
            flush()
            story.append(HRFlowable(width="100%", thickness=0.5, color=LIGHT, spaceBefore=8, spaceAfter=10))
            continue
        match = re.match(r"^\s*(?:[-*]\s+|([0-9]+)\.\s+)(.+)$", line)
        if match:
            flush()
            prefix = f"{match.group(1)}. " if match.group(1) else "• "
            story.append(Paragraph(inline(prefix + match.group(2)), STYLES["GuideBullet"]))
            continue
        body.append(line.strip())
    flush()
    if code:
        story.extend(code_blocks(code))
    return title, story


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", help="Build a PDF whose output filename contains this text")
    args = parser.parse_args()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    rl_config.warnOnMissingFontGlyphs = 1
    for source_name, output_name in FILES:
        if args.only and args.only not in output_name:
            continue
        source_path = DOCS / source_name
        title, story = markdown_story(source_path.read_text(encoding="utf-8"), source_path)
        destination = OUTPUT / output_name
        doc = GuideDocument(str(destination), title)
        doc.multiBuild(story)
        print(f"Built {destination.relative_to(ROOT)} ({destination.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
