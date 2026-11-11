"""
Versatile PDF-to-EPUB extraction engine for Kindle Toolbox.
Handles complex multi-column layouts, automatic word de-hyphenation,
surgical line-level footnote extraction and EPUB3 popup hyperlinking,
margin header/footer removal, and structured chapter segmentation.
"""

from html import escape as html_escape
import re
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional

import pymupdf


HEADING_REGEX = re.compile(
    r"^(PREFACE|PREFACES|FOREWORD|PROLOGUE|INTRODUCTION|EPILOGUE|APPENDIX|"
    r"PREFACIO|PREFACIOS|PR[ÓO]LOGO|INTRODUCCI[ÓO]N|EP[ÍI]LOGO|AP[ÉE]NDICE|ÍNDICE|INDICE|"
    r"CONTENTS|TABLE\s+OF\s+CONTENTS|"
    r"PART\s+(?:ONE|TWO|THREE|FOUR|FIVE|SIX|\d+|[IVXLCDM]+)|"
    r"(?:FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH)\s+PART|"
    r"(?:PRIMERA|SEGUNDA|TERCERA|CUARTA|QUINTA|SEXTA)\s+PARTE|"
    r"[IVXLCDM]+\.\s+[A-ZÁÉÍÓÚÑ]|"
    r"(?:CHAPTER|CAP[ÍI]TULO)\s+[IVXLCDM\d]+)",
    re.IGNORECASE,
)

PART_REGEX = re.compile(
    r"^(?:(?:PRIMERA|SEGUNDA|TERCERA|CUARTA|QUINTA|SEXTA)\s+PARTE|"
    r"(?:FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH)\s+PART|"
    r"PART\s+(?:ONE|TWO|THREE|FOUR|FIVE|SIX|\d+|[IVXLCDM]+))\b",
    re.IGNORECASE,
)

DATE_SIG_REGEX = re.compile(
    r"^(?:"
    r"[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+,\s+\d{1,2}\s+de\s+[a-záéíóúñ]+\s+de\s+\d{4}|"
    r"[A-Z][a-zA-Z\.\s]+,\s+(?:[A-Z][a-z]+\s+\d{1,2},|\d{1,2}\s+[A-Z][a-z]+)\s+\d{4}"
    r")"
)


def clean_pdf_text_artifacts(text: str) -> str:
    """
    Sanitizes common encoding artifacts found in Ghostscript/PDFCreator PDFs:
    - Converts control glyphs \\x02 and \\x15 to uppercase 'N'.
    - Strips non-printable ASCII control characters.
    """
    if not text:
        return ""
    t = text.replace("\x02", "N").replace("\x15", "N")
    t = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x14\x16-\x1f]", "", t)
    return t


def detect_pdf_language(lines: List[Dict[str, Any]]) -> str:
    """
    Infers the primary language ('en' or 'es') from extracted document lines.
    """
    sample_text = " ".join(l.get("text", "") for l in lines[:120]).lower()
    sample = f" {sample_text} "
    es_hits = sum(sample.count(w) for w in (" de ", " la ", " el ", " los ", " las ", " que ", " por ", " para "))
    en_hits = sum(sample.count(w) for w in (" the ", " and ", " of ", " to ", " in ", " that ", " for ", " with "))
    if es_hits > en_hits and es_hits >= 6:
        return "es"
    return "en"


def clean_title_and_author(raw_title: str, raw_author: str, filename: str = "") -> Tuple[str, str]:
    """
    Cleans extracted PDF title and author metadata, stripping common archive/download tags
    such as (z-library.sk, 1lib.sk, z-lib.sk), (libgen), [b-ok], etc., and inferring
    clean values from the PDF filename when metadata is missing or generic.
    """
    junk_pattern = re.compile(
        r"\s*[\(\[](?:z-library|1lib|z-lib|b-ok|libgen|oceanofpdf|dokumen)[\w\.\s,-]*[\)\]]",
        re.IGNORECASE,
    )
    generic_titles = {"document", "documento", "microsoft word", "untitled", "sin título", "sin titulo"}
    generic_authors = {
        "unknown author",
        "unknown",
        "autor desconocido",
        "desconocido",
        "usuario",
        "user",
        "admin",
        "none",
        "",
    }

    t = clean_pdf_text_artifacts(raw_title or "").strip()
    a = clean_pdf_text_artifacts(raw_author or "").strip()
    fn = Path(filename).stem if filename else ""

    t = junk_pattern.sub("", t).strip()
    fn_clean = junk_pattern.sub("", fn).strip()

    # Fallback to filename if title metadata is missing or generic
    if not t or len(t) < 3 or t.lower() in generic_titles:
        t = fn_clean

    # Parse "Title (Author)" filename convention
    if "(" in t and ")" in t:
        m = re.match(r"^([^(]+)\s*\(([^)]+)\)\s*$", t)
        if m:
            candidate_title = m.group(1).strip()
            candidate_author = m.group(2).strip()
            if len(candidate_author) > 2 and not junk_pattern.search(f"({candidate_author})"):
                t = candidate_title
                if not a or a.lower() in generic_authors:
                    a = candidate_author

    # Infer author from original filename if metadata author is still generic
    if (not a or a.lower() in generic_authors) and "(" in fn_clean:
        m = re.match(r"^([^(]+)\s*\(([^)]+)\)", fn_clean)
        if m:
            candidate_author = m.group(2).strip()
            if not junk_pattern.search(f"({candidate_author})"):
                a = candidate_author
                if not t:
                    t = m.group(1).strip()

    a = junk_pattern.sub("", a).strip()
    if not a or a.lower() in generic_authors:
        a = "Unknown Author"

    t = re.sub(r"\s+", " ", t).strip(" -_")
    a = re.sub(r"\s+", " ", a).strip(" -_")

    return t or "Digital Book", a or "Unknown Author"


def is_title_credits_page(page: pymupdf.Page) -> bool:
    """
    Detects whether an opening PDF page is a title/half-title or publisher credits page.
    Matches pages with relatively short text containing editorial metadata keywords.
    """
    text = clean_pdf_text_artifacts(page.get_text("text")).strip()
    if not text or len(text) > 750:
        return False

    keywords = (
        "edition:",
        "language:",
        "digitized",
        "distributed",
        "publisher",
        "press",
        "isbn",
        "translation:",
        "translated by",
        "copyright",
        "all rights reserved",
        "published by",
        "printed in",
        "edición:",
        "edicion:",
        "lengua:",
        "digitalización:",
        "digitalizacion:",
        "distribución:",
        "distribucion:",
        "editorial",
        "traducción:",
        "traduccion:",
        "todos los derechos",
        "publicado por",
        "impreso en",
    )
    text_low = text.lower()
    matches = sum(1 for kw in keywords if kw in text_low)
    return matches >= 2 or (len(text) < 300 and matches >= 1)


def extract_p1_info(page: pymupdf.Page) -> Tuple[str, str, str]:
    """
    Extracts title, author, and formatted edition credits HTML from an opening credits page.
    Returns (detected_title, detected_author, credits_html).
    """
    text = clean_pdf_text_artifacts(page.get_text("text")).strip()
    lines = [clean_pdf_text_artifacts(l).strip() for l in text.splitlines() if l.strip()]

    title_candidate = ""
    author_candidate = ""
    credits_lines = []

    credit_kws = (
        "edition:",
        "language:",
        "digitized",
        "distributed",
        "publisher",
        "isbn",
        "translation:",
        "translated by",
        "copyright",
        "published by",
        "edición:",
        "edicion:",
        "lengua:",
        "digitalización:",
        "digitalizacion:",
        "distribución:",
        "distribucion:",
        "editorial",
        "traducción:",
        "traduccion:",
    )

    for l in lines:
        l_low = l.lower()
        if any(kw in l_low for kw in credit_kws):
            credits_lines.append(l)
        elif not title_candidate and len(l) > 3 and not any(kw in l_low for kw in ("http:", "https:", "www.")):
            title_candidate = l
        elif title_candidate and not author_candidate and len(l) > 2 and not any(kw in l_low for kw in ("http:", "https:", "www.")):
            author_candidate = l
        else:
            credits_lines.append(l)

    credits_html = "".join(f"<p>{html_escape(cl, quote=False)}</p>" for cl in credits_lines) if credits_lines else ""
    return title_candidate, author_candidate, credits_html


def is_printed_toc_page(page: pymupdf.Page) -> bool:
    """
    Detects whether a PDF page is a legacy printed table of contents with dot leaders
    and print page numbers (e.g., 'Chapter 1 ....... 15'), so it can be omitted from the
    narrative body (EPUB navigation is handled natively via nav.xhtml / toc.ncx).
    """
    text = clean_pdf_text_artifacts(page.get_text("text"))
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if not lines:
        return False

    has_toc_header = bool(
        re.search(r"^\s*(CONTENTS|TABLE\s+OF\s+CONTENTS|ÍNDICE|INDICE|TABLA\s+DE\s+CONTENIDO)\b", text, re.I)
    )

    dotted_lines = sum(
        1
        for l in lines
        if re.search(r"(\.{3,}|\…|\.\s*\.\s*\.)\s*\d+\s*$", l) or re.search(r"(\.{3,}|\…)", l)
    )

    if has_toc_header and (dotted_lines >= 3 or len(lines) < 25):
        return True

    if dotted_lines >= 5:
        return True

    return False


def detect_page_columns(page: pymupdf.Page, top_margin: float = 56.0, bottom_margin: float = 802.0) -> Tuple[int, float]:
    """
    Automatically detects 1-column vs 2-column layout by analyzing horizontal block distribution.
    Returns (num_columns, gutter_mid_x).
    """
    page_w = page.rect.width
    mid_x = page_w / 2.0

    blocks = page.get_text("blocks")
    useful_blocks = [
        b for b in blocks if b[4].strip() and b[3] > top_margin and b[1] < bottom_margin
    ]

    if not useful_blocks:
        return 1, mid_x

    left_count = 0
    right_count = 0
    gutter_left = mid_x - 30
    gutter_right = mid_x + 30

    for b in useful_blocks:
        x0, _y0, x1, _y1 = b[:4]
        if x0 < gutter_left and x1 > gutter_right:
            continue
        elif x1 <= mid_x + 15:
            left_count += 1
        elif x0 >= mid_x - 15:
            right_count += 1

    if left_count >= 1 and right_count >= 1:
        return 2, mid_x

    return 1, mid_x


def extract_block_footnotes(
    block: Dict[str, Any],
    dominant_size: float = 11.0,
    page_height: float = 842.0,
) -> Tuple[Optional[Dict[str, Any]], Dict[str, str]]:
    """
    Inspects individual lines inside a PyMuPDF text block to isolate footnotes
    (numbered lines in smaller type or located near the bottom of the page).
    Prevents footnotes placed adjacent to signatures or short footers from leaking into body text.
    Returns (filtered_body_block_or_None, {note_number: note_text}).
    """
    lines = block.get("lines", [])
    if not lines:
        return None, {}

    body_lines = []
    footnotes = {}
    curr_fn_num = None
    curr_fn_lines = []

    for l in lines:
        spans = l.get("spans", [])
        if not spans:
            continue
        line_t = clean_pdf_text_artifacts("".join(s["text"] for s in spans)).strip()
        if not line_t:
            continue

        first_span = spans[0]
        sz = round(first_span.get("size", dominant_size), 1)
        y = l.get("bbox", (0, 0, 0, 0))[1]

        # Check whether the line starts a footnote entry
        m = re.match(r"^(\d{1,3})\s+([A-ZÁÉÍÓÚÑ\(\"“].*)", line_t)
        is_fn_start = False
        if m:
            if sz < dominant_size - 0.7 or y > (page_height * 0.60):
                is_fn_start = True

        if is_fn_start:
            if curr_fn_num and curr_fn_lines:
                footnotes[curr_fn_num] = " ".join(curr_fn_lines)
            curr_fn_num = m.group(1)
            curr_fn_lines = [line_t]
        elif curr_fn_num is not None:
            # Continue footnote block while lines retain smaller font or lower vertical band
            if sz < dominant_size - 0.4 or y > (page_height * 0.65):
                curr_fn_lines.append(line_t)
            else:
                footnotes[curr_fn_num] = " ".join(curr_fn_lines)
                curr_fn_num = None
                curr_fn_lines = []
                body_lines.append(l)
        else:
            body_lines.append(l)

    if curr_fn_num and curr_fn_lines:
        footnotes[curr_fn_num] = " ".join(curr_fn_lines)

    if not body_lines:
        return None, footnotes

    new_b = dict(block)
    new_b["lines"] = body_lines
    line_boxes = [l["bbox"] for l in body_lines if "bbox" in l]
    if line_boxes:
        new_b["bbox"] = (
            min(bx[0] for bx in line_boxes),
            min(bx[1] for bx in line_boxes),
            max(bx[2] for bx in line_boxes),
            max(bx[3] for bx in line_boxes),
        )
    return new_b, footnotes


def extract_page_elements(
    page: pymupdf.Page,
    col_mode: str = "auto",
    dominant_font: str = "TimesNewRoman",
    dominant_size: float = 11.0,
    top_margin: float = 56.0,
    bottom_margin: float = 802.0,
) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    """
    Extracts page text blocks in natural reading order:
    - Excludes running headers and bottom margin page numbers.
    - Reads 2-column pages strictly column by column (left column first, then right column).
    - Separates detected footnotes out of the narrative flow.
    """
    page_w = page.rect.width
    page_h = page.rect.height

    if col_mode == "auto":
        cols, mid_x = detect_page_columns(page, top_margin, bottom_margin)
    elif col_mode == "2":
        cols, mid_x = 2, page_w / 2.0
    else:
        cols, mid_x = 1, page_w / 2.0

    text_dict = page.get_text("dict")
    raw_blocks = text_dict.get("blocks", [])

    body_blocks = []
    page_footnotes = {}

    for b in raw_blocks:
        if b.get("type") != 0:
            continue

        bbox = b.get("bbox", (0, 0, 0, 0))
        if bbox[3] <= top_margin or bbox[1] >= bottom_margin:
            continue

        new_b, b_fns = extract_block_footnotes(b, dominant_size=dominant_size, page_height=page_h)
        if b_fns:
            page_footnotes.update(b_fns)

        if new_b is not None:
            body_blocks.append(new_b)

    if cols == 1:
        body_blocks.sort(key=lambda b: (b["bbox"][1], b["bbox"][0]))
        return body_blocks, page_footnotes

    col_left = []
    col_right = []
    spanning_top = []
    spanning_bottom = []

    gutter_left = mid_x - 30
    gutter_right = mid_x + 30

    for b in body_blocks:
        x0, y0, x1, _y1 = b["bbox"]
        if x0 < gutter_left and x1 > gutter_right:
            if y0 < page_h * 0.35:
                spanning_top.append(b)
            else:
                spanning_bottom.append(b)
        elif (x0 + x1) / 2.0 < mid_x:
            col_left.append(b)
        else:
            col_right.append(b)

    spanning_top.sort(key=lambda b: b["bbox"][1])
    col_left.sort(key=lambda b: b["bbox"][1])
    col_right.sort(key=lambda b: b["bbox"][1])
    spanning_bottom.sort(key=lambda b: b["bbox"][1])

    ordered = spanning_top + col_left + col_right + spanning_bottom
    return ordered, page_footnotes


def is_section_subtitle(text: str, prev_text: str = "", next_text: str = "") -> bool:
    """
    Detects standalone Roman numeral section dividers ('I', 'II', 'III', etc.)
    between paragraphs or prefaces.
    """
    t = text.strip()
    if not re.match(r"^[IVXLCDM]{1,6}\.?$", t):
        return False
    if not next_text or not re.match(r"^[A-ZÁÉÍÓÚÑ\"“]", next_text.strip()):
        return False
    if not prev_text:
        return True
    is_terminal = bool(re.search(r"[\.!?:\)\]\"”\x15]\s*$", prev_text.strip()))
    is_short = len(prev_text.strip()) < 50
    return is_terminal or is_short


def reassemble_lines_and_dehyphenate(lines_raw: List[Dict[str, Any]]) -> List[str]:
    """
    Reconstructs clean paragraphs from raw lines and rejoins hyphenated words broken across lines.
    Marks internal Roman section dividers (__SUBTITLE__) and asterisms (__ASTERISM__).
    """
    paragraphs = []
    current_para = []

    for idx, line_obj in enumerate(lines_raw):
        text = line_obj["text"].strip()
        if not text:
            continue

        text = clean_pdf_text_artifacts(text)

        prev_text = current_para[-1] if current_para else (paragraphs[-1] if paragraphs else "")
        next_text = ""
        for next_idx in range(idx + 1, min(idx + 6, len(lines_raw))):
            cand = clean_pdf_text_artifacts(lines_raw[next_idx]["text"]).strip()
            if cand:
                next_text = cand
                break

        # 1. Standalone Roman numeral section subtitle
        if is_section_subtitle(text, prev_text, next_text):
            if current_para:
                paragraphs.append(" ".join(current_para))
                current_para = []
            paragraphs.append(f"__SUBTITLE__{text.rstrip('.')}")
            continue

        # 2. Ornamental separator / asterism
        if re.match(r"^(\*{3,}|—{3,}|_{3,}|\*\s+\*\s+\*)$", text):
            if current_para:
                paragraphs.append(" ".join(current_para))
                current_para = []
            paragraphs.append("__ASTERISM__")
            continue

        if not current_para:
            current_para.append(text)
            continue

        prev_text = current_para[-1]

        # Dehyphenate split words across line breaks (preserving explicit dashes/hyphens)
        if prev_text.endswith("-") and not prev_text.endswith(("--", " -")):
            if text and (text[0].islower() or text[0] in "áéíóúñ"):
                current_para[-1] = prev_text[:-1] + text
            else:
                current_para[-1] = prev_text + text
        else:
            is_prev_terminal = bool(re.search(r"[\.!?:\)\]\"”']\s*$", prev_text))
            is_curr_indented = line_obj.get("is_indented", False)
            is_curr_sig = bool(DATE_SIG_REGEX.match(text))

            if (is_prev_terminal and (is_curr_indented or len(prev_text) < 45)) or is_curr_sig:
                paragraphs.append(" ".join(current_para))
                current_para = [text]
            else:
                current_para.append(text)

    if current_para:
        paragraphs.append(" ".join(current_para))

    return paragraphs


def is_heading_line(line_text: str, font_name: str, font_size: float, dominant_size: float) -> bool:
    """Detects whether a line represents a chapter or major part heading."""
    clean_t = clean_pdf_text_artifacts(line_text).strip()
    if not clean_t or len(clean_t) > 95:
        return False

    # Ignore printed index lines containing dot leaders (e.g., "Preface ....... 1")
    if re.search(r"\.{3,}|\…|\.\s*\.\s*\.", clean_t):
        return False

    is_bold = "bold" in font_name.lower() or font_size >= dominant_size + 1.5
    if is_bold and HEADING_REGEX.search(clean_t):
        return True

    if (is_bold or clean_t.isupper()) and PART_REGEX.match(clean_t):
        return True

    return False


def link_footnotes_in_text(text: str, footnotes: Dict[str, str], linked_set: Optional[set] = None) -> str:
    """
    Converts numeric footnote callouts in paragraph text into EPUB3/ARIA popup anchors
    (epub:type="noteref" role="doc-noteref") for native floating popups on Kindle.
    """
    for num in sorted(footnotes.keys(), key=lambda n: int(n) if n.isdigit() else 999, reverse=True):
        pattern = re.compile(rf"(?:\b|(?<=[a-zA-ZáéíóúÁÉÍÓÚñÑ,\.\)\"”’])){num}(?=[\s,\.;:\)\"”’]|$)", re.UNICODE)
        if pattern.search(text):
            if linked_set is not None:
                linked_set.add(num)
            replacement = (
                rf'<a href="#note-{num}" id="ref-{num}" class="footnote-ref" '
                rf'epub:type="noteref" role="doc-noteref"><sup>{num}</sup></a>'
            )
            text = pattern.sub(replacement, text, count=1)
    return text


def build_footnotes_section_html(footnotes: Dict[str, str], linked_set: Optional[set] = None) -> str:
    """
    Builds the EPUB3 chapter endnotes section using semantic <aside epub:type="footnote">
    elements so Amazon Kindle, Apple Books, and modern e-readers open them as inline popups.
    """
    if not footnotes:
        return ""

    items_html = []
    sorted_keys = sorted(footnotes.keys(), key=lambda k: int(k) if k.isdigit() else 999)

    for num in sorted_keys:
        raw_text = footnotes[num]
        cleaned_text = re.sub(rf"^\s*{num}\s+", "", raw_text).strip()
        safe_body = html_escape(cleaned_text, quote=False)
        backlink = (
            f'<a href="#ref-{num}" class="footnote-backref" role="doc-backlink" title="Back to text">{num}.</a> '
            if (linked_set is None or num in linked_set)
            else f"<strong>{num}.</strong> "
        )
        items_html.append(
            f'<aside id="note-{num}" class="footnote-item" epub:type="footnote" role="doc-footnote">\n'
            f"  <p>{backlink}<span>{safe_body}</span></p>\n"
            f"</aside>"
        )

    return f"""
    <section class="footnotes-section" epub:type="footnotes" role="doc-endnotes">
      <hr class="footnotes-divider" />
      <h4 class="footnotes-title">Notes</h4>
      {"".join(items_html)}
    </section>
"""


def extract_structured_pdf(pdf_path: str, col_mode: str = "auto") -> Dict[str, Any]:
    """
    End-to-end PDF analysis and extraction pipeline:
    - Cleans metadata and extracts front-matter credits while skipping printed TOC pages.
    - Detects dominant fonts, font sizes, and multi-column layouts.
    - Reconstructs paragraphs in natural reading order with de-hyphenation.
    - Isolates and links footnotes per page/chapter scope.
    - Segments content into navigable chapters with Part awareness.
    """
    path_obj = Path(pdf_path)
    if not path_obj.exists():
        raise FileNotFoundError(f"File not found: {pdf_path}")

    with pymupdf.open(str(path_obj)) as doc:
        total_pages = len(doc)

        # 1. Clean base metadata
        meta = doc.metadata or {}
        raw_title = (meta.get("title") or "").strip()
        raw_author = (meta.get("author") or "").strip()
        title, author = clean_title_and_author(raw_title, raw_author, filename=path_obj.name)

        # 1.1 Inspect first page for title/credits info
        edition_info = ""
        start_pno = 0
        if total_pages > 0 and is_title_credits_page(doc[0]):
            p1_title, p1_author, p1_credits = extract_p1_info(doc[0])
            if p1_title and (not title or title == path_obj.stem or len(title) > len(p1_title)):
                cleaned_p1_t, _ = clean_title_and_author(p1_title, author, filename=path_obj.name)
                if cleaned_p1_t:
                    title = cleaned_p1_t
            if p1_author and (not author or author == "Unknown Author"):
                _, cleaned_p1_a = clean_title_and_author(title, p1_author, filename=path_obj.name)
                if cleaned_p1_a:
                    author = cleaned_p1_a
            edition_info = p1_credits
            start_pno = 1

        # 1.2 Skip printed table-of-contents pages from the narrative body
        while start_pno < min(5, total_pages) and is_printed_toc_page(doc[start_pno]):
            start_pno += 1

        # 2. Sample pages to identify dominant font, font size, and column mode
        sample_pages = min(15, total_pages - start_pno) if total_pages > start_pno else 1
        fonts_counter: Dict[str, int] = {}
        sizes_counter: Dict[float, int] = {}
        col_detections: List[int] = []

        for pno in range(start_pno, min(start_pno + sample_pages, total_pages)):
            page = doc[pno]
            cols, _ = detect_page_columns(page)
            col_detections.append(cols)

            td = page.get_text("dict")
            for b in td.get("blocks", []):
                if b.get("type") == 0:
                    for l in b.get("lines", []):
                        for s in l.get("spans", []):
                            f = s.get("font", "")
                            sz = round(s.get("size", 11.0), 1)
                            if f:
                                fonts_counter[f] = fonts_counter.get(f, 0) + len(s.get("text", ""))
                            sizes_counter[sz] = sizes_counter.get(sz, 0) + len(s.get("text", ""))

        dominant_font = max(fonts_counter.keys(), key=lambda k: fonts_counter[k]) if fonts_counter else "TimesNewRoman"
        dominant_size = max(sizes_counter.keys(), key=lambda k: sizes_counter[k]) if sizes_counter else 11.0
        dominant_cols = 2 if col_detections.count(2) > col_detections.count(1) else 1

        # 3. Extract narrative pages
        raw_document_lines: List[Dict[str, Any]] = []
        all_footnotes: Dict[str, str] = {}
        page_footnotes_map: Dict[int, Dict[str, str]] = {}

        for pno in range(start_pno, total_pages):
            page = doc[pno]
            ordered_blocks, page_fns = extract_page_elements(
                page,
                col_mode=col_mode,
                dominant_font=dominant_font,
                dominant_size=dominant_size,
            )

            p_num = pno + 1
            page_footnotes_map[p_num] = page_fns
            all_footnotes.update(page_fns)

            for b in ordered_blocks:
                for line in b.get("lines", []):
                    spans = line.get("spans", [])
                    if not spans:
                        continue
                    line_text = "".join(s["text"] for s in spans)
                    first_span = spans[0]
                    font_name = first_span.get("font", "")
                    font_size = first_span.get("size", dominant_size)
                    bbox = line.get("bbox", (0, 0, 0, 0))

                    is_indented = (bbox[0] % 250) > 8.0

                    raw_document_lines.append(
                        {
                            "text": line_text,
                            "font": font_name,
                            "size": font_size,
                            "is_indented": is_indented,
                            "page": p_num,
                        }
                    )

    language = detect_pdf_language(raw_document_lines)

    # 4. Segment document into chapters
    def make_chapter_entry(cid: str, ctitle: str, cpart: str, clines: List[Dict[str, Any]]) -> Dict[str, Any]:
        paras = reassemble_lines_and_dehyphenate(clines)
        cpages = {l["page"] for l in clines if "page" in l}
        cfns = {}
        for p in sorted(cpages):
            if p in page_footnotes_map:
                cfns.update(page_footnotes_map[p])
        return {
            "id": cid,
            "title": ctitle,
            "part": cpart,
            "paragraphs": paras,
            "footnotes": cfns,
        }

    chapters = []
    current_chap_title = ""
    current_part_title = ""
    current_chap_lines: List[Dict[str, Any]] = []
    chap_counter = 1

    for line_obj in raw_document_lines:
        t = line_obj["text"].strip()
        f = line_obj["font"]
        sz = line_obj["size"]

        if is_heading_line(t, f, sz, dominant_size):
            clean_head = clean_pdf_text_artifacts(t).strip()

            # Check if this heading is a top-level Part banner (e.g., "PART ONE. PHILOSOPHY")
            if PART_REGEX.match(clean_head):
                if current_chap_lines:
                    if current_chap_title:
                        chapters.append(
                            make_chapter_entry(
                                f"chap_{chap_counter:02d}",
                                current_chap_title,
                                current_part_title,
                                current_chap_lines,
                            )
                        )
                        chap_counter += 1
                    current_chap_lines = []
                current_part_title = clean_head
                current_chap_title = ""
                continue

            if current_chap_lines:
                if current_chap_title:
                    chapters.append(
                        make_chapter_entry(
                            f"chap_{chap_counter:02d}",
                            current_chap_title,
                            current_part_title,
                            current_chap_lines,
                        )
                    )
                    chap_counter += 1
                else:
                    check_paras = reassemble_lines_and_dehyphenate(current_chap_lines)
                    if check_paras and len(" ".join(check_paras).strip()) > 120:
                        chapters.append(
                            make_chapter_entry(
                                f"chap_{chap_counter:02d}",
                                "Prologue",
                                current_part_title,
                                current_chap_lines,
                            )
                        )
                        chap_counter += 1
                current_chap_lines = []

            current_chap_title = clean_head
        else:
            current_chap_lines.append(line_obj)

    if current_chap_lines:
        chapters.append(
            make_chapter_entry(
                f"chap_{chap_counter:02d}",
                current_chap_title or "Final Chapter",
                current_part_title,
                current_chap_lines,
            )
        )

    if not chapters:
        chapters.append(make_chapter_entry("chap_01", title, "", raw_document_lines))

    # 5. Format chapter XHTML bodies and link footnotes
    structured_chapters = []
    total_footnotes_linked = 0

    for chap in chapters:
        paras_html = []
        chap_fns = dict(chap.get("footnotes", {}))
        chap_linked_refs = set()
        need_no_indent = True

        for p_idx, p_text in enumerate(chap["paragraphs"]):
            if p_text.startswith("__SUBTITLE__"):
                sub_title = html_escape(p_text.replace("__SUBTITLE__", "").strip(), quote=False)
                paras_html.append(f'<h2 class="section-subtitle">{sub_title}</h2>')
                need_no_indent = True
                continue

            if p_text == "__ASTERISM__":
                paras_html.append('<p class="asterism">* * *</p>')
                need_no_indent = True
                continue

            escaped_p = html_escape(p_text, quote=False)
            linked_p = link_footnotes_in_text(escaped_p, chap_fns, linked_set=chap_linked_refs)

            if need_no_indent or p_idx == 0:
                p_class = ' class="no-indent"'
                need_no_indent = False
            elif DATE_SIG_REGEX.match(p_text):
                p_class = ' class="signature-date"'
            elif p_text.startswith(("(", "[")) and len(p_text) < 40:
                p_class = ' class="signature-note"'
            else:
                p_class = ""

            paras_html.append(f"<p{p_class}>{linked_p}</p>")

        for k in chap_fns.keys():
            all_footnotes.pop(k, None)

        total_footnotes_linked += len(chap_fns)

        footnotes_html = build_footnotes_section_html(chap_fns, linked_set=chap_linked_refs)
        full_chap_body = "\n".join(paras_html) + footnotes_html

        structured_chapters.append(
            {
                "id": chap["id"],
                "title": chap["title"],
                "part": chap.get("part", ""),
                "html_body": full_chap_body,
                "footnotes_count": len(chap_fns),
            }
        )

    if all_footnotes and structured_chapters:
        residual_html = build_footnotes_section_html(all_footnotes)
        structured_chapters[-1]["html_body"] += residual_html
        structured_chapters[-1]["footnotes_count"] += len(all_footnotes)
        total_footnotes_linked += len(all_footnotes)

    return {
        "title": title,
        "author": author,
        "language": language,
        "edition_info": edition_info,
        "total_pages": total_pages,
        "detected_col_mode": f"{dominant_cols} column{'s' if dominant_cols > 1 else ''}",
        "dominant_cols": dominant_cols,
        "chapters_count": len(structured_chapters),
        "total_footnotes": total_footnotes_linked,
        "chapters": structured_chapters,
    }
