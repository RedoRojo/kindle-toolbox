"""
Reflowable EPUB3 e-book generator optimized for E-Ink displays and Kindle devices.
Builds EPUB packages with editorial typographic stylesheets, dual navigation
(NCX and EPUB3 Nav), high-resolution cover artwork, and embedded image assets.
"""

from html import escape as html_escape
import io
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

from ebooklib import epub
from PIL import Image, ImageDraw, ImageFont

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def _esc(value: Optional[str]) -> str:
    """Safely escapes plain text for valid XML/XHTML interpolation."""
    return html_escape(value or "", quote=True)


def clean_filename(title: str, author: Optional[str] = None, max_len: int = 100) -> str:
    """
    Generates a filesystem-safe, human-readable filename for the output EPUB.
    """
    clean_t = title.strip() if title else "Article"
    clean_t = re.sub(r'[\\/*?:"<>|]', " - ", clean_t)
    clean_t = re.sub(r"\s+", " ", clean_t).strip(" -_")

    clean_a = ""
    unknown_authors = {
        "unknown author",
        "unknown",
        "autor desconocido",
        "desconocido",
        "none",
        "null",
    }
    if author and author.strip() and author.lower() not in unknown_authors:
        ca = re.sub(r'[\\/*?:"<>|]', "", author.strip())
        ca = re.sub(r"\s+", " ", ca).strip(" -_")
        if ca:
            clean_a = f" - {ca}"

    full_name = f"{clean_t}{clean_a}"
    if len(full_name) > max_len:
        truncated = full_name[:max_len]
        if " " in truncated:
            full_name = truncated.rsplit(" ", 1)[0].strip(" -_")
        else:
            full_name = truncated.strip(" -_")

    if not full_name:
        full_name = "Article"

    return f"{full_name}.epub"


def get_available_font(font_type: str = "serif", size: int = 40) -> ImageFont.ImageFont:
    """
    Locates an installed system TrueType font with a safe default fallback.
    """
    candidates = []
    if font_type == "serif":
        candidates = [
            "/usr/share/fonts/noto/NotoSerif-Bold.ttf",
            "/usr/share/fonts/noto/NotoSerif-Regular.ttf",
            "/usr/share/fonts/TTF/DejaVuSerif-Bold.ttf",
            "/usr/share/fonts/TTF/DejaVuSerif.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
        ]
    elif font_type == "sans":
        candidates = [
            "/usr/share/fonts/noto/NotoSans-Bold.ttf",
            "/usr/share/fonts/noto/NotoSans-Regular.ttf",
            "/usr/share/fonts/TTF/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]

    for c in candidates:
        if os.path.isfile(c):
            try:
                return ImageFont.truetype(c, size)
            except Exception:
                pass

    try:
        return ImageFont.load_default(size=size)
    except Exception:
        return ImageFont.load_default()


def generate_cover_image(title: str, author: str, sitename: str = "") -> bytes:
    """
    Generates a classic, restrained 1200x1800 px (2:3 ratio) cover image for e-readers.
    Warm ivory background (#FAF7F2), double hairline frame with corner ornaments,
    tracked uppercase author header, centered serif title, and sober footer.
    """
    width, height = 1200, 1800
    img = Image.new("RGB", (width, height), color="#FAF7F2")
    draw = ImageDraw.Draw(img)

    # Outer editorial border
    outer_m = 50
    draw.rectangle(
        [(outer_m, outer_m), (width - outer_m, height - outer_m)],
        outline="#2C2C2C",
        width=4,
    )

    # Inner hairline frame
    inner_m = 65
    draw.rectangle(
        [(inner_m, inner_m), (width - inner_m, height - inner_m)],
        outline="#777777",
        width=1,
    )

    # Corner ornaments
    ornament_size = 14
    for cx in (inner_m + 8, width - inner_m - 8 - ornament_size):
        for cy in (inner_m + 8, height - inner_m - 8 - ornament_size):
            draw.rectangle([(cx, cy), (cx + ornament_size, cy + ornament_size)], outline="#555555", width=1)

    author_font = get_available_font("sans", size=34)
    title_font = get_available_font("serif", size=68)
    footer_font = get_available_font("sans", size=24)

    # 1. Author header
    author_clean = author.strip() if author else "UNKNOWN AUTHOR"
    author_display = "  ".join(w.upper() for w in author_clean.split())
    author_bbox = draw.textbbox((0, 0), author_display, font=author_font)
    author_w = author_bbox[2] - author_bbox[0]
    author_x = (width - author_w) // 2
    author_y = 220
    draw.text((author_x, author_y), author_display, fill="#2C2C2C", font=author_font)

    # Subtle rule below author
    line_author_y = author_y + 60
    draw.line([(width // 2 - 80, line_author_y), (width // 2 + 80, line_author_y)], fill="#777777", width=1)

    # 2. Centered title wrapped across lines
    max_text_width = width - (inner_m * 2 + 140)
    words = title.split()
    lines = []
    curr_line = []

    for word in words:
        test_line = " ".join(curr_line + [word])
        bbox = draw.textbbox((0, 0), test_line, font=title_font)
        if (bbox[2] - bbox[0]) <= max_text_width:
            curr_line.append(word)
        else:
            if curr_line:
                lines.append(" ".join(curr_line))
            curr_line = [word]
    if curr_line:
        lines.append(" ".join(curr_line))

    # Cap at 7 lines on cover
    lines = lines[:7]
    line_spacing = 28
    line_heights = [
        draw.textbbox((0, 0), line, font=title_font)[3] - draw.textbbox((0, 0), line, font=title_font)[1]
        for line in lines
    ] or [68]
    total_title_height = sum(line_heights) + max(0, len(lines) - 1) * line_spacing

    y_start = int((height * 0.46) - (total_title_height / 2))
    for idx, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=title_font)
        w = bbox[2] - bbox[0]
        x = (width - w) // 2
        draw.text((x, y_start), line, fill="#111111", font=title_font)
        y_start += line_heights[idx] + line_spacing

    # Ornamental divider under title
    sep_y = y_start + 45
    draw.line([(width // 2 - 140, sep_y), (width // 2 + 140, sep_y)], fill="#333333", width=2)
    draw.line([(width // 2 - 80, sep_y + 6), (width // 2 + 80, sep_y + 6)], fill="#777777", width=1)

    # 3. Footer caption
    footer_text = sitename.upper() if sitename else "KINDLE TOOLBOX • DIGITAL EDITION"
    footer_display = "  ".join(footer_text.split())
    footer_bbox = draw.textbbox((0, 0), footer_display, font=footer_font)
    footer_w = footer_bbox[2] - footer_bbox[0]
    draw.text(((width - footer_w) // 2, height - outer_m - 90), footer_display, fill="#555555", font=footer_font)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92, optimize=True)
    return buf.getvalue()


def build_epub_css(paragraph_style: str = "book") -> str:
    """
    Returns an E-Ink optimized typographic stylesheet tailored for Kindle and EPUB3 readers.
    """
    if paragraph_style == "article":
        p_style = """
p {
  margin-top: 0;
  margin-bottom: 1.15em;
  text-indent: 0;
}
"""
    else:  # Standard editorial book style
        p_style = """
p {
  margin-top: 0;
  margin-bottom: 0;
  text-indent: 1.5em;
  text-align: justify;
  line-height: 1.45;
}
p.no-indent,
.chapter-header + p,
h1 + p, h2 + p, h3 + p, h4 + p, h5 + p, h6 + p,
blockquote + p, figure + p, table + p {
  text-indent: 0 !important;
}
"""

    return f"""@charset "utf-8";

@page {{
  margin: 5pt;
}}

body {{
  font-family: "Bookerly", "Charter", "Georgia", "Sitka Text", serif;
  font-size: 1.05em;
  line-height: 1.48;
  color: #111111;
  text-align: justify;
  text-justify: inter-word;
  hyphens: auto;
  -webkit-hyphens: auto;
  -epub-hyphens: auto;
  margin: 0;
  padding: 0;
}}

/* Cover and Front Matter Layout */
.no-margin {{
  margin: 0 !important;
  padding: 0 !important;
}}

.cover-page {{
  text-align: center;
  padding: 0;
  margin: 0;
  height: 100%;
}}

.cover-page img {{
  height: 100%;
  max-height: 100vh;
  max-width: 100%;
  width: auto;
  margin: 0 auto;
  object-fit: contain;
}}

.half-title {{
  text-align: center;
  margin-top: 15%;
  margin-bottom: 20%;
}}

.half-title-author {{
  font-family: "Amazon Ember", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  font-size: 1.25em;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: #333333;
  margin-bottom: 2.2em;
}}

.half-title-title {{
  font-family: "Bookerly", "Charter", "Georgia", serif;
  font-size: 2.2em;
  font-weight: 700;
  line-height: 1.22;
  margin-bottom: 0.8em;
  color: #000000;
}}

.half-title-subtitle {{
  font-size: 1.1em;
  font-style: italic;
  color: #555555;
  margin-bottom: 2em;
}}

.half-title-brand {{
  font-family: "Amazon Ember", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  font-size: 0.85em;
  letter-spacing: 0.25em;
  color: #666666;
  margin-top: 5em;
}}

.info-page {{
  font-family: "Bookerly", "Charter", "Georgia", serif;
  font-size: 0.92em;
  line-height: 1.6;
  color: #222222;
  margin: 12% 8%;
}}

.info-title {{
  font-family: "Amazon Ember", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  font-size: 1.3em;
  font-weight: bold;
  margin-bottom: 0.4em;
  color: #000000;
}}

.info-author {{
  font-size: 1.05em;
  color: #444444;
  margin-bottom: 1.5em;
}}

.info-small {{
  font-size: 0.85em;
  color: #666666;
}}

.spacer-sm {{
  margin-top: 1em;
}}

.spacer-lg {{
  margin-top: 2.5em;
}}

/* Section Subtitles (e.g., I, II, III) inside Chapters */
.section-subtitle {{
  font-family: "Amazon Ember", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  font-size: 1.35em;
  font-weight: 700;
  text-align: center;
  margin-top: 2.2em;
  margin-bottom: 1.2em;
  letter-spacing: 0.12em;
  color: #111111;
  page-break-after: avoid;
  break-after: avoid;
}}

.section-subtitle + p {{
  text-indent: 0 !important;
}}

.chapter-part {{
  font-family: "Amazon Ember", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  font-size: 0.95em;
  font-weight: 600;
  letter-spacing: 0.15em;
  text-transform: uppercase;
  color: #555555;
  margin-top: 0;
  margin-bottom: 0.5em;
  text-indent: 0 !important;
}}

.signature-date {{
  margin-top: 1.8em;
  margin-bottom: 0.3em;
  text-align: right;
  font-style: italic;
  color: #444444;
  text-indent: 0 !important;
}}

.signature-note {{
  margin-top: 0.2em;
  margin-bottom: 2em;
  text-align: right;
  font-size: 0.88em;
  color: #666666;
  text-indent: 0 !important;
}}

.asterism {{
  text-align: center;
  font-size: 1.2em;
  margin: 1.8em 0;
  letter-spacing: 0.3em;
  color: #666666;
  text-indent: 0 !important;
}}

{p_style}

.chapter-header {{
  margin-top: 1.5em;
  margin-bottom: 2em;
  text-align: left;
  page-break-after: avoid;
  break-after: avoid;
}}

.chapter-title {{
  font-family: "Amazon Ember", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  font-size: 1.85em;
  font-weight: 700;
  line-height: 1.22;
  margin-top: 0;
  margin-bottom: 0.6em;
  color: #000000;
  text-align: left;
}}

.chapter-meta {{
  font-family: "Amazon Ember", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  font-size: 0.88em;
  color: #444444;
  margin-bottom: 1.2em;
  line-height: 1.4;
}}

.chapter-meta p {{
  margin: 0.2em 0;
  text-indent: 0 !important;
}}

.header-divider {{
  border: 0;
  border-top: 1px solid #777777;
  margin: 1.5em 0 2em 0;
}}

h1, h2, h3, h4, h5, h6 {{
  font-family: "Amazon Ember", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  font-weight: 700;
  color: #000000;
  page-break-after: avoid;
  break-after: avoid;
  line-height: 1.25;
  text-align: left;
}}

h1 {{
  font-size: 1.6em;
  margin-top: 2em;
  margin-bottom: 0.6em;
  page-break-before: always;
  break-before: page;
}}

h2 {{
  font-size: 1.35em;
  margin-top: 1.8em;
  margin-bottom: 0.5em;
  border-bottom: 1px solid #bbbbbb;
  padding-bottom: 0.25em;
}}

h3 {{
  font-size: 1.18em;
  margin-top: 1.5em;
  margin-bottom: 0.4em;
}}

h4 {{
  font-size: 1.05em;
  margin-top: 1.3em;
  margin-bottom: 0.35em;
}}

blockquote {{
  margin: 1.3em 1.5em;
  padding-left: 1em;
  border-left: 3px solid #666666;
  font-style: italic;
  color: #222222;
}}

blockquote p {{
  text-indent: 0 !important;
  margin-bottom: 0.6em;
}}

pre, code {{
  font-family: "Courier New", Courier, monospace;
  font-size: 0.9em;
}}

pre {{
  white-space: pre-wrap;
  word-wrap: break-word;
  background-color: #f1f1f1;
  border: 1px solid #cccccc;
  padding: 0.8em;
  margin: 1.3em 0;
}}

code {{
  background-color: #f1f1f1;
  padding: 0.1em 0.3em;
}}

img {{
  max-width: 100%;
  height: auto;
  display: block;
  margin: 1.4em auto;
  page-break-inside: avoid;
  break-inside: avoid;
}}

figure {{
  margin: 1.5em 0;
  text-align: center;
  page-break-inside: avoid;
  break-inside: avoid;
}}

figcaption {{
  font-size: 0.85em;
  color: #555555;
  font-style: italic;
  margin-top: 0.4em;
  text-align: center;
}}

table {{
  width: 100%;
  border-collapse: collapse;
  margin: 1.4em 0;
  font-size: 0.92em;
  page-break-inside: avoid;
  break-inside: avoid;
}}

th, td {{
  border: 1px solid #999999;
  padding: 0.45em 0.6em;
  text-align: left;
}}

th {{
  background-color: #e6e6e6;
  font-weight: bold;
}}

ul, ol {{
  margin-top: 0.6em;
  margin-bottom: 1em;
  padding-left: 1.8em;
}}

li {{
  margin-bottom: 0.35em;
}}

.chapter-footer {{
  margin-top: 3em;
  padding-top: 1em;
  border-top: 1px solid #cccccc;
  font-size: 0.82em;
  color: #555555;
  page-break-inside: avoid;
  break-inside: avoid;
}}

.chapter-footer p {{
  text-indent: 0 !important;
}}

a {{
  color: #111111;
  text-decoration: underline;
}}

/* Kindle & EPUB3 Popup Footnote Styles */
.footnote-ref {{
  font-size: 0.75em;
  vertical-align: super;
  text-decoration: none;
  font-weight: bold;
  color: #111111;
  padding: 0 0.15em;
}}

.footnotes-section {{
  margin-top: 2.5em;
  padding-top: 1em;
  border-top: 1px solid #bbbbbb;
  font-size: 0.88em;
  line-height: 1.4;
  page-break-inside: avoid;
}}

.footnotes-title {{
  font-size: 1.1em;
  margin-bottom: 0.8em;
  font-family: "Amazon Ember", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  font-weight: bold;
}}

.footnotes-list {{
  padding-left: 1.5em;
  margin: 0;
}}

.footnote-item {{
  margin-bottom: 0.6em;
  text-align: justify;
}}

.footnote-backref {{
  text-decoration: none;
  font-size: 0.9em;
  color: #555555;
  margin-left: 0.3em;
}}
"""


def format_xhtml_content(
    title: str,
    author: str,
    date: str,
    sitename: str,
    url: str,
    body_html: str,
    lang: str = "en",
) -> str:
    """
    Formats extracted article HTML into a valid EPUB3 XHTML document.
    """
    safe_title = _esc(title)
    safe_lang = _esc(lang or "en")

    author_line = f'<p class="chapter-author"><strong>Author:</strong> {_esc(author)}</p>' if author else ""
    date_line = f'<p class="chapter-date"><strong>Date:</strong> {_esc(date)}</p>' if date else ""
    source_line = f'<p class="chapter-source"><strong>Published in:</strong> {_esc(sitename)}</p>' if sitename else ""

    meta_block = ""
    if author_line or date_line or source_line:
        meta_block = f"""
    <div class="chapter-meta">
      {author_line}
      {date_line}
      {source_line}
    </div>
"""

    safe_url = _esc(url)
    footer_block = (
        f"""
  <footer class="chapter-footer">
    <p>Original article: <a href="{safe_url}">{safe_url}</a></p>
  </footer>"""
        if url
        else ""
    )

    return f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="{safe_lang}" lang="{safe_lang}">
<head>
  <meta charset="utf-8" />
  <title>{safe_title}</title>
  <link rel="stylesheet" type="text/css" href="style/epub.css" />
</head>
<body>
  <header class="chapter-header">
    <h1 class="chapter-title">{safe_title}</h1>
    {meta_block}
    <hr class="header-divider" />
  </header>
  <div class="chapter-body">
    {body_html}
  </div>{footer_block}
</body>
</html>"""


def create_epub_book(
    article_data: Dict[str, Any],
    paragraph_style: str = "book",
    generate_cover: bool = True,
) -> Dict[str, Any]:
    """
    Creates a single-article EPUB3 file with complete metadata, E-Ink CSS,
    embedded local images, and generated cover artwork.
    Returns generated file details (filename, filepath, filesize).
    """
    title = (article_data.get("title") or "Web Article").strip()
    author = (article_data.get("author") or "Unknown Author").strip()
    date = (article_data.get("date") or "").strip()
    sitename = (article_data.get("sitename") or "").strip()
    url = (article_data.get("url") or "").strip()
    lang = (article_data.get("language") or "en").strip() or "en"
    body_html = article_data.get("html_body") or "<p></p>"
    images = article_data.get("images", [])

    book = epub.EpubBook()

    # Book metadata
    book_id = str(uuid.uuid4())
    book.set_identifier(f"urn:uuid:{book_id}")
    book.set_title(title)
    book.set_language(lang)
    book.add_author(author)

    book.add_metadata("DC", "date", date or datetime.now().strftime("%Y-%m-%d"))
    book.add_metadata("DC", "publisher", sitename or "Kindle Toolbox")
    book.add_metadata(
        "DC",
        "description",
        f"Converted for E-Ink/Kindle reading from {url}" if url else "Converted for E-Ink/Kindle reading",
    )

    # Cover image
    if generate_cover:
        try:
            cover_bytes = generate_cover_image(title, author, sitename)
            book.set_cover("cover.jpg", cover_bytes)
        except Exception:
            pass

    # Stylesheet
    css_content = build_epub_css(paragraph_style=paragraph_style)
    css_item = epub.EpubItem(
        uid="style_epub",
        file_name="style/epub.css",
        media_type="text/css",
        content=css_content.encode("utf-8"),
    )
    book.add_item(css_item)

    # Embedded image assets
    for img in images:
        img_item = epub.EpubItem(
            uid=img["id"],
            file_name=img["rel_path"],
            media_type=img["media_type"],
            content=img["content"],
        )
        book.add_item(img_item)

    # Main article chapter
    xhtml_doc = format_xhtml_content(
        title=title,
        author=author,
        date=date,
        sitename=sitename,
        url=url,
        body_html=body_html,
        lang=lang,
    )

    chapter = epub.EpubHtml(
        title=title,
        file_name="chap_01.xhtml",
        lang=lang,
    )
    chapter.content = xhtml_doc.encode("utf-8")
    chapter.add_item(css_item)
    book.add_item(chapter)

    # Table of contents & dual navigation
    book.toc = (epub.Link("chap_01.xhtml", title, "chap_01"),)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    # Reading spine
    book.spine = ["nav", chapter]

    out_filename = clean_filename(title, author)
    out_path = OUTPUT_DIR / out_filename

    counter = 2
    base_stem = out_path.stem
    while out_path.exists():
        out_filename = f"{base_stem} ({counter}).epub"
        out_path = OUTPUT_DIR / out_filename
        counter += 1

    epub.write_epub(str(out_path), book, {})
    filesize = out_path.stat().st_size

    return {
        "filename": out_filename,
        "filepath": str(out_path),
        "filesize": filesize,
        "title": title,
        "author": author,
    }


def create_multi_chapter_epub(
    book_data: Dict[str, Any],
    chapters: List[Dict[str, Any]],
    paragraph_style: str = "book",
    generate_cover: bool = True,
) -> Dict[str, Any]:
    """
    Creates a multi-chapter reflowable EPUB3 book from structured PDF content.
    Generates front matter (cover, half-title, credits), full TOC (NCX + Nav),
    and E-Ink optimized typographic stylesheets.
    """
    title = (book_data.get("title") or "Digital Book").strip()
    author = (book_data.get("author") or "Unknown Author").strip()
    date = (book_data.get("date") or "").strip()
    sitename = (book_data.get("sitename") or "Kindle Toolbox").strip()
    lang = (book_data.get("language") or "en").strip() or "en"
    images = book_data.get("images", [])

    safe_title = _esc(title)
    safe_author = _esc(author)
    safe_lang = _esc(lang)

    book = epub.EpubBook()
    book_id = str(uuid.uuid4())
    book.set_identifier(f"urn:uuid:{book_id}")
    book.set_title(title)
    book.set_language(lang)
    book.add_author(author)

    book.add_metadata("DC", "date", date or datetime.now().strftime("%Y-%m-%d"))
    book.add_metadata("DC", "publisher", sitename or "Kindle Toolbox")
    book.add_metadata("DC", "description", "Converted from PDF document for E-Ink/Kindle reading")

    css_content = build_epub_css(paragraph_style=paragraph_style)
    css_item = epub.EpubItem(
        uid="style_epub",
        file_name="style/epub.css",
        media_type="text/css",
        content=css_content.encode("utf-8"),
    )
    book.add_item(css_item)

    # 1. Cover page (cover.jpg + full-bleed cover.xhtml)
    cover_item = None
    if generate_cover:
        try:
            cover_bytes = generate_cover_image(title, author, sitename)
            book.set_cover("cover.jpg", cover_bytes, create_page=False)

            cover_doc = f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="{safe_lang}" lang="{safe_lang}">
<head>
  <meta charset="utf-8" />
  <title>Cover</title>
  <link rel="stylesheet" type="text/css" href="style/epub.css" />
</head>
<body class="no-margin">
  <div class="cover-page">
    <img alt="Cover" src="cover.jpg" />
  </div>
</body>
</html>"""
            cover_item = epub.EpubHtml(
                title="Cover",
                file_name="cover.xhtml",
                lang=lang,
            )
            cover_item.content = cover_doc.encode("utf-8")
            cover_item.add_item(css_item)
            book.add_item(cover_item)
        except Exception:
            pass

    # 2. Half-title page (title.xhtml)
    title_doc = f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="{safe_lang}" lang="{safe_lang}">
<head>
  <meta charset="utf-8" />
  <title>{safe_title}</title>
  <link rel="stylesheet" type="text/css" href="style/epub.css" />
</head>
<body>
  <div class="half-title">
    <p class="half-title-author">{safe_author}</p>
    <h1 class="half-title-title">{safe_title}</h1>
    <p class="half-title-brand">KINDLE TOOLBOX</p>
  </div>
</body>
</html>"""
    title_item = epub.EpubHtml(
        title=title,
        file_name="title.xhtml",
        lang=lang,
    )
    title_item.content = title_doc.encode("utf-8")
    title_item.add_item(css_item)
    book.add_item(title_item)

    # 3. Edition info & credits page (credits.xhtml)
    edition_info = book_data.get("edition_info", "")
    credits_doc = f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="{safe_lang}" lang="{safe_lang}">
<head>
  <meta charset="utf-8" />
  <title>Credits</title>
  <link rel="stylesheet" type="text/css" href="style/epub.css" />
</head>
<body>
  <div class="info-page">
    <h2 class="info-title">{safe_title}</h2>
    <p class="info-author"><strong>Author:</strong> {safe_author}</p>
    <div class="spacer-sm"></div>
    {edition_info}
    <div class="spacer-lg"></div>
    <p class="info-small">Digital edition generated with <strong>Kindle Toolbox</strong>.</p>
  </div>
</body>
</html>"""
    credits_item = epub.EpubHtml(
        title="Credits",
        file_name="credits.xhtml",
        lang=lang,
    )
    credits_item.content = credits_doc.encode("utf-8")
    credits_item.add_item(css_item)
    book.add_item(credits_item)

    # Image assets
    for img in images:
        img_item = epub.EpubItem(
            uid=img["id"],
            file_name=img["rel_path"],
            media_type=img["media_type"],
            content=img["content"],
        )
        book.add_item(img_item)

    # Narrative chapters
    epub_chapters = []
    toc_links = []

    for idx, chap in enumerate(chapters):
        c_title = chap.get("title") or f"Chapter {idx + 1}"
        c_part = (chap.get("part") or "").strip()
        c_html = chap.get("html_body") or "<p></p>"
        file_name = f"chap_{idx + 1:02d}.xhtml"

        safe_c_title = _esc(c_title)
        part_header_html = f'    <p class="chapter-part">{_esc(c_part)}</p>\n' if c_part else ""

        xhtml_doc = f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="{safe_lang}" lang="{safe_lang}">
<head>
  <meta charset="utf-8" />
  <title>{safe_c_title}</title>
  <link rel="stylesheet" type="text/css" href="style/epub.css" />
</head>
<body>
  <header class="chapter-header">
{part_header_html}    <h1 class="chapter-title">{safe_c_title}</h1>
    <hr class="header-divider" />
  </header>
  <div class="chapter-body">
    {c_html}
  </div>
</body>
</html>"""

        c_item = epub.EpubHtml(
            title=c_title,
            file_name=file_name,
            lang=lang,
        )
        c_item.content = xhtml_doc.encode("utf-8")
        c_item.add_item(css_item)
        book.add_item(c_item)

        epub_chapters.append(c_item)
        toc_links.append(epub.Link(file_name, c_title, f"chap_{idx + 1:02d}"))

    # Table of contents & dual navigation
    front_matter_links = []
    if cover_item:
        front_matter_links.append(epub.Link("cover.xhtml", "Cover", "cover_page"))
    front_matter_links.append(epub.Link("title.xhtml", title, "title_page"))
    front_matter_links.append(epub.Link("credits.xhtml", "Credits", "credits_page"))

    book.toc = tuple(front_matter_links + toc_links)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    # Reading spine
    front_matter_spine = []
    if cover_item:
        front_matter_spine.append(cover_item)
    front_matter_spine.extend([title_item, credits_item])

    book.spine = ["nav"] + front_matter_spine + epub_chapters

    out_filename = clean_filename(title, author)
    out_path = OUTPUT_DIR / out_filename

    counter = 2
    base_stem = out_path.stem
    while out_path.exists():
        out_filename = f"{base_stem} ({counter}).epub"
        out_path = OUTPUT_DIR / out_filename
        counter += 1

    epub.write_epub(str(out_path), book, {})
    filesize = out_path.stat().st_size

    return {
        "filename": out_filename,
        "filepath": str(out_path),
        "filesize": filesize,
        "title": title,
        "author": author,
        "chapters_count": len(chapters),
    }
