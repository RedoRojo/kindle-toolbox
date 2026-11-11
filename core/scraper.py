"""
Web extraction and content cleaning module for Kindle Toolbox.
Generates clean semantic HTML and optimized local image assets for EPUB3 e-books.
"""

import base64
import io
import re
from typing import Dict, Any, List, Tuple
from urllib.parse import urljoin, urlparse

import httpx
import trafilatura
from bs4 import BeautifulSoup
from PIL import Image

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def detect_document_language(text_or_html: str, soup: BeautifulSoup = None) -> str:
    """
    Detects the primary document language (e.g., 'en', 'es', 'fr', 'de')
    from HTML lang attributes or lightweight stopword heuristics, defaulting to 'en'.
    """
    if soup is not None:
        html_tag = soup.find("html")
        if html_tag:
            raw_lang = html_tag.get("lang") or html_tag.get("xml:lang") or ""
            lang_code = raw_lang.strip().split("-")[0].split("_")[0].lower()
            if len(lang_code) == 2 and lang_code.isalpha():
                return lang_code

        meta_lang = soup.find("meta", attrs={"http-equiv": re.compile(r"content-language", re.I)})
        if meta_lang and meta_lang.get("content"):
            lang_code = meta_lang["content"].strip().split("-")[0].split(",")[0].lower()
            if len(lang_code) == 2 and lang_code.isalpha():
                return lang_code

    sample = f" {text_or_html[:4000].lower()} "
    es_hits = sum(sample.count(w) for w in (" de ", " la ", " el ", " los ", " las ", " que ", " por ", " para "))
    en_hits = sum(sample.count(w) for w in (" the ", " and ", " of ", " to ", " in ", " that ", " for ", " with "))

    if es_hits > en_hits and es_hits >= 6:
        return "es"
    return "en"


def fetch_raw_html(url: str, timeout: float = 20.0) -> Tuple[str, str]:
    """
    Downloads raw HTML from the given URL while ensuring proper character encoding
    (especially for legacy pages using ISO-8859-1 or Windows-1252).
    Returns (html_text, final_url).
    """
    downloaded = trafilatura.fetch_url(url)
    if downloaded:
        return downloaded, url

    headers = {"User-Agent": DEFAULT_USER_AGENT}
    with httpx.Client(timeout=timeout, headers=headers, follow_redirects=True) as client:
        resp = client.get(url)
        resp.raise_for_status()

        # Smart charset fallback if server omits explicit UTF-8 or misreports encoding
        if not resp.encoding or resp.encoding.lower() == "utf-8":
            soup_pre = BeautifulSoup(resp.content[:4000], "html.parser")
            meta_charset = soup_pre.find("meta", charset=True)
            if meta_charset and meta_charset.get("charset"):
                resp.encoding = meta_charset["charset"]
            else:
                meta_ct = soup_pre.find("meta", attrs={"http-equiv": re.compile(r"content-type", re.I)})
                if meta_ct and "charset=" in meta_ct.get("content", "").lower():
                    resp.encoding = meta_ct["content"].lower().split("charset=")[-1].split(";")[0].strip()

        return resp.text, str(resp.url)


def pre_clean_html(html_str: str) -> str:
    """
    Strips social media blocks, share buttons, ads, and newsletter banners.
    Ensures the document is wrapped in a semantic <article> container so
    Trafilatura does not fall back to 'recover_wild_text' (which drops h1-h6).
    """
    if not html_str:
        return ""

    soup = BeautifulSoup(html_str, "html.parser")
    social_patterns = re.compile(
        r"share|social|tweet|twitter|facebook|whatsapp|sharing|sharebox|"
        r"post-share|share-bar|share-buttons|social-icons|newsletter|subscribe|"
        r"author-social|reaction-buttons|comments|disqus|related-posts",
        re.IGNORECASE,
    )

    for tag in soup.find_all(attrs={"class": social_patterns}):
        tag.decompose()
    for tag in soup.find_all(attrs={"id": social_patterns}):
        tag.decompose()
    for a in soup.find_all(
        "a",
        href=re.compile(
            r"twitter\.com/intent/tweet|facebook\.com/sharer|linkedin\.com/share|"
            r"pinterest\.com/pin|api\.whatsapp\.com|t\.me/share|mailto:\?subject",
            re.I,
        ),
    ):
        a.decompose()

    # Wrap content in <article> if page lacks semantic landmarks to preserve headings
    if not soup.find(["article", "main"]):
        body = soup.find("body")
        if body:
            art = soup.new_tag("article")
            art.extend(list(body.contents))
            body.append(art)
        else:
            art = soup.new_tag("article")
            art.extend(list(soup.contents))
            soup.append(art)

    return str(soup)


def post_clean_extracted_soup(soup: BeautifulSoup) -> None:
    """
    Removes unsafe tags and residual share/subscribe prompts from extracted HTML.
    """
    for tag in soup.find_all(["script", "style", "iframe", "noscript", "object", "embed"]):
        tag.decompose()

    share_text_pattern = re.compile(
        r"\b(Share\s+Tweet|Tweet\s+Share|Share\s+on\s+Twitter|Share\s+on\s+Facebook|"
        r"Compartir\s+en\s+Twitter|Compartir\s+Tweet)\b",
        re.IGNORECASE,
    )
    for text_node in list(soup.find_all(string=True)):
        if share_text_pattern.search(text_node):
            new_text = share_text_pattern.sub("", text_node)
            text_node.replace_with(new_text)


def clean_and_normalize_headings(soup: BeautifulSoup, doc_title: str = "", doc_author: str = "") -> None:
    """
    Normalizes heading hierarchy inside extracted HTML:
    1. Promotes short full-bold paragraphs (<p><b>...</b></p>) into <h4> headings.
    2. Removes leading duplicate headings identical to document title or author.
    3. Merges split numbering headings (e.g., <h4>1.</h4> + <h4>TITLE</h4> -> <h4>1. TITLE</h4>).
    """
    # 1. Promote standalone bold paragraphs that act as subheadings
    for p in list(soup.find_all("p")):
        bold_child = p.find(["b", "strong"])
        if bold_child and bold_child.parent == p:
            b_text = bold_child.get_text().strip()
            p_text = p.get_text().strip()
            if b_text == p_text and 2 <= len(b_text) <= 120:
                is_num_title = bool(
                    re.match(
                        r"^(\d+\.?|[IVXLCDM]+\.?|Chapter\s+\w+|Section\s+\w+|Part\s+\w+|"
                        r"Cap[íi]tulo\s+\w+|Secci[óo]n\s+\w+|Parte\s+\w+).*$",
                        b_text,
                        re.I,
                    )
                )
                if is_num_title or not b_text.endswith("."):
                    h = soup.new_tag("h4")
                    h.string = b_text
                    p.replace_with(h)

    # 2. Deduplicate leading headings matching main title or author
    norm_title = re.sub(r"\W+", " ", doc_title.lower()).strip() if doc_title else ""
    norm_author = re.sub(r"\W+", " ", doc_author.lower()).strip() if doc_author else ""

    leading_headings = list(soup.find_all(["h1", "h2", "h3"]))[:3]
    for h in leading_headings:
        h_text = re.sub(r"\W+", " ", h.get_text().lower()).strip()
        if (norm_title and (h_text == norm_title or (len(norm_title) > 8 and norm_title in h_text))) or (
            norm_author and (h_text == norm_author or (len(norm_author) > 6 and norm_author in h_text))
        ):
            h.decompose()

    # 3. Merge adjacent numbering/section headings
    headings = list(soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]))
    for i in range(len(headings) - 1):
        h1 = headings[i]
        h2 = headings[i + 1]
        if not h1.parent or not h2.parent:
            continue

        is_short_num = bool(re.match(r"^(\d+\.?|[IVXLCDM]+\.?|[A-Za-z]\.?)$", h1.get_text().strip()))
        if h1.name != h2.name and not is_short_num:
            continue

        curr = h1.next_sibling
        is_adjacent = False
        while curr:
            if curr == h2:
                is_adjacent = True
                break
            if getattr(curr, "name", None):
                if curr.get_text(strip=True):
                    break
            curr = curr.next_sibling

        if is_adjacent:
            t1 = h1.get_text().strip()
            t2 = h2.get_text().strip()
            if is_short_num:
                num = t1 if t1.endswith(".") else f"{t1}."
                h2.string = f"{num} {t2}"
                h1.decompose()
            elif h1.name == h2.name and re.match(
                r"^(FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH|SEVENTH|EIGHTH|NINTH|TENTH|"
                r"PART\s+\w+|CHAPTER\s+\w+|PRIMERA|SEGUNDA|TERCERA|CUARTA|QUINTA|SEXTA|"
                r"S[ÉE]PTIMA|OCTAVA|NOVENA|D[ÉE]CIMA|PARTE\s+\w+|CAP[ÍI]TULO\s+\w+).*$",
                t1,
                re.I,
            ):
                separator = ": " if not t1.endswith(":") else " "
                h2.string = f"{t1}{separator}{t2}"
                h1.decompose()


def process_and_extract_images(soup: BeautifulSoup, base_url: str, max_width: int = 1600) -> List[Dict[str, Any]]:
    """
    Downloads and optimizes referenced HTML images for packaging inside EPUB.
    Converts unsupported formats (e.g., WebP, TIFF) to JPEG or PNG for Kindle compatibility.
    Rewrites each <img> src to the internal relative path 'images/img_XXX.ext'.
    Returns metadata and encoded image bytes for each valid image.
    """
    images_list = []
    headers = {"User-Agent": DEFAULT_USER_AGENT, "Referer": base_url}

    for pic in soup.find_all("picture"):
        for src in pic.find_all("source"):
            src.decompose()

    img_counter = 1
    with httpx.Client(timeout=15.0, headers=headers, follow_redirects=True) as client:
        for img in list(soup.find_all("img")):
            raw_src = (
                img.get("data-src")
                or img.get("data-original")
                or img.get("data-lazy-src")
                or img.get("src")
            )

            if not raw_src:
                img.decompose()
                continue

            # Skip tiny decorative SVGs or tracking pixels
            if "data:image/svg" in raw_src and "pixel" in raw_src:
                img.decompose()
                continue

            try:
                if raw_src.startswith("data:image/"):
                    _header, data = raw_src.split(",", 1)
                    img_bytes = base64.b64decode(data)
                else:
                    abs_url = urljoin(base_url, raw_src)
                    resp = client.get(abs_url)
                    if resp.status_code != 200 or not resp.content:
                        img.decompose()
                        continue
                    img_bytes = resp.content

                pil_img = Image.open(io.BytesIO(img_bytes))
                orig_format = pil_img.format or "JPEG"

                # Discard tiny UI icons or avatars (< 30x30 px)
                if pil_img.width < 30 and pil_img.height < 30:
                    img.decompose()
                    continue

                # Downscale oversized images for e-reader memory efficiency
                if pil_img.width > max_width:
                    ratio = max_width / float(pil_img.width)
                    new_height = int(float(pil_img.height) * ratio)
                    pil_img = pil_img.resize((max_width, new_height), Image.Resampling.LANCZOS)

                if orig_format.upper() in ("PNG", "GIF"):
                    output_ext = orig_format.lower()
                    media_type = f"image/{orig_format.lower()}"
                    save_format = orig_format.upper()
                else:
                    if pil_img.mode in ("RGBA", "LA", "P"):
                        pil_img = pil_img.convert("RGB")
                    save_format = "JPEG"
                    output_ext = "jpg"
                    media_type = "image/jpeg"

                buf = io.BytesIO()
                pil_img.save(buf, format=save_format, quality=85, optimize=True)
                final_bytes = buf.getvalue()

                item_id = f"img_{img_counter:03d}"
                filename = f"{item_id}.{output_ext}"
                epub_rel_path = f"images/{filename}"

                img["src"] = epub_rel_path

                for attr in ["srcset", "data-src", "data-original", "data-lazy-src", "loading", "sizes", "style"]:
                    if img.has_attr(attr):
                        del img[attr]

                images_list.append(
                    {
                        "id": item_id,
                        "filename": filename,
                        "rel_path": epub_rel_path,
                        "content": final_bytes,
                        "media_type": media_type,
                    }
                )
                img_counter += 1

            except Exception:
                img.decompose()

    return images_list


def extract_metadata_from_html(raw_html: str, final_url: str) -> Dict[str, Any]:
    """
    Extracts article metadata (title, author, date, sitename, language) from downloaded HTML.
    """
    meta = trafilatura.extract_metadata(raw_html)

    title = meta.title if meta and meta.title else ""
    author = meta.author if meta and meta.author else ""
    date = meta.date if meta and meta.date else ""
    sitename = meta.sitename if meta and meta.sitename else urlparse(final_url).netloc

    soup = BeautifulSoup(raw_html, "html.parser")

    # Heuristic for classic archive titles like "Author (Year): Title"
    if not title or not author:
        raw_title_tag = soup.title.string if soup.title else ""
        if raw_title_tag:
            m = re.match(r"^([^(\n\r]+?)\s*\(\d{4}\):\s*(.+)$", raw_title_tag.strip())
            if m:
                if not author:
                    author = m.group(1).strip()
                if not title:
                    title = m.group(2).strip()

    if not title:
        h1 = soup.find("h1")
        title = h1.get_text(strip=True) if h1 else (soup.title.string.strip() if soup.title and soup.title.string else "")

    if not author:
        meta_author = soup.find("meta", attrs={"name": re.compile(r"author", re.I)})
        if meta_author and meta_author.get("content"):
            author = meta_author["content"].strip()

    language = detect_document_language(soup.get_text(" ", strip=True), soup=soup)

    return {
        "title": title.strip() if title else "Web Article",
        "author": author.strip() if author and author.lower() not in ("none", "null") else "Unknown Author",
        "date": date.strip() if date else "",
        "sitename": sitename.strip() if sitename else urlparse(final_url).netloc,
        "url": final_url,
        "language": language,
    }


def fetch_article_metadata(url: str) -> Dict[str, Any]:
    """
    Fetches a web URL and returns extracted article metadata.
    """
    raw_html, final_url = fetch_raw_html(url, timeout=12.0)
    return extract_metadata_from_html(raw_html, final_url)


def extract_clean_article(url: str, include_images: bool = True) -> Dict[str, Any]:
    """
    Full article extraction pipeline:
    - Downloads raw HTML with charset auto-detection.
    - Pre-cleans social clutter and enforces semantic wrapping.
    - Extracts main content via Trafilatura (with BeautifulSoup fallback).
    - Normalizes headings and strips unsafe elements.
    - Downloads and optimizes local EPUB images.
    """
    raw_html, final_url = fetch_raw_html(url)
    cleaned_html = pre_clean_html(raw_html)

    meta_info = extract_metadata_from_html(raw_html, final_url)
    title = meta_info["title"]
    author = meta_info["author"]
    date = meta_info["date"]
    sitename = meta_info["sitename"]
    language = meta_info["language"]

    raw_soup = BeautifulSoup(cleaned_html, "html.parser")
    raw_headings_count = len(raw_soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]))

    extracted_html = trafilatura.extract(
        cleaned_html,
        output_format="html",
        include_formatting=True,
        include_images=include_images,
        include_links=True,
    )

    ext_soup = BeautifulSoup(extracted_html or "", "html.parser")
    ext_headings_count = len(ext_soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]))

    # Fallback if Trafilatura fails, extracts minimal content, or drops headings present in original
    if not extracted_html or len(extracted_html.strip()) < 120 or (raw_headings_count > 0 and ext_headings_count == 0):
        soup = BeautifulSoup(cleaned_html, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "aside", "header", "iframe", "noscript"]):
            tag.decompose()

        article_node = (
            soup.find("article")
            or soup.find("main")
            or soup.find(class_=re.compile(r"content|post|entry|article", re.I))
        )
        if article_node:
            extracted_html = str(article_node)
        else:
            body = soup.find("body")
            extracted_html = str(body) if body else str(soup)

    soup = BeautifulSoup(extracted_html or "<p>No content could be extracted.</p>", "html.parser")
    post_clean_extracted_soup(soup)
    clean_and_normalize_headings(soup, doc_title=title, doc_author=author)

    images = []
    if include_images:
        images = process_and_extract_images(soup, final_url)
    else:
        for tag in soup.find_all(["img", "figure", "picture"]):
            tag.decompose()

    return {
        "title": title,
        "author": author,
        "date": date,
        "sitename": sitename,
        "url": final_url,
        "language": language,
        "html_body": str(soup),
        "images": images,
    }
