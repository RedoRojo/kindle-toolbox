"""
Módulo de extracción y limpieza web para Kindle Toolbox.
Portado y optimizado a partir de pdf-toolbox para generar HTML semántico
y assets de imágenes limpios para libros electrónicos EPUB3.
"""

import io
import re
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import httpx
import trafilatura
from bs4 import BeautifulSoup
from PIL import Image

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def fetch_raw_html(url: str, timeout: float = 20.0) -> Tuple[str, str]:
    """
    Descarga el contenido HTML de la URL asegurando la codificación correcta
    (especialmente para webs clásicas en ISO-8859-1 o Windows-1252).
    Retorna (html_text, final_url).
    """
    # Intentar primero con trafilatura
    downloaded = trafilatura.fetch_url(url)
    if downloaded:
        return downloaded, url

    headers = {"User-Agent": DEFAULT_USER_AGENT}
    with httpx.Client(timeout=timeout, headers=headers, follow_redirects=True) as client:
        resp = client.get(url)
        resp.raise_for_status()

        # Detección inteligente de codificación si no es UTF-8 explícito
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
    Elimina bloques de redes sociales, botones de compartir, anuncios y banners.
    Garantiza que el documento tenga un contenedor semántico <article>
    para evitar que trafilatura active 'recover_wild_text' (que descarta h1-h6).
    """
    if not html_str:
        return ""

    soup = BeautifulSoup(html_str, "html.parser")
    social_patterns = re.compile(
        r"share|social|tweet|twitter|facebook|whatsapp|sharing|sharebox|"
        r"post-share|share-bar|share-buttons|social-icons|newsletter|subscribe|"
        r"author-social|reaction-buttons|comments|disqus|related-posts",
        re.IGNORECASE
    )

    for tag in soup.find_all(attrs={"class": social_patterns}):
        tag.decompose()
    for tag in soup.find_all(attrs={"id": social_patterns}):
        tag.decompose()
    for a in soup.find_all("a", href=re.compile(
        r"twitter\.com/intent/tweet|facebook\.com/sharer|linkedin\.com/share|"
        r"pinterest\.com/pin|api\.whatsapp\.com|t\.me/share|mailto:\?subject",
        re.I
    )):
        a.decompose()

    # Si la web no tiene <article> ni <main>, envolver el body para preservar encabezados
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


def post_clean_extracted_soup(soup: BeautifulSoup):
    """
    Limpia textos residuales de compartir o suscripciones que hayan escapado a trafilatura.
    """
    share_text_pattern = re.compile(
        r"\b(Share\s+Tweet|Tweet\s+Share|Share\s+on\s+Twitter|Compartir\s+en\s+Twitter|Compartir\s+Tweet)\b",
        re.IGNORECASE
    )
    for text_node in list(soup.find_all(string=True)):
        if share_text_pattern.search(text_node):
            new_text = share_text_pattern.sub("", text_node)
            text_node.replace_with(new_text)


def clean_and_normalize_headings(soup: BeautifulSoup, doc_title: str = "", doc_author: str = ""):
    """
    Normaliza y jerarquiza los títulos y subtítulos del contenido:
    1. Promueve párrafos en negrita con formato de título (<p><b>...</b></p>) a <h4> reales.
    2. Elimina títulos iniciales duplicados que repiten de forma idéntica el título o autor.
    3. Fusiona encabezados adyacentes de numeración (ej. <h4>1.</h4> + <h4>TITULO</h4> -> <h4>1. TITULO</h4>).
    """
    # 1. Promover párrafos breves que son 100% negrita
    for p in list(soup.find_all("p")):
        bold_child = p.find(["b", "strong"])
        if bold_child and bold_child.parent == p:
            b_text = bold_child.get_text().strip()
            p_text = p.get_text().strip()
            if b_text == p_text and 2 <= len(b_text) <= 120:
                is_num_title = bool(re.match(
                    r"^(\d+\.?|[IVXLCDM]+\.?|Cap[íi]tulo\s+\w+|Secci[óo]n\s+\w+|Parte\s+\w+).*$",
                    b_text, re.I
                ))
                if is_num_title or not b_text.endswith("."):
                    h = soup.new_tag("h4")
                    h.string = b_text
                    p.replace_with(h)

    # 2. Desduplicar encabezados iniciales que repitan el título o autor general
    norm_title = re.sub(r"\W+", " ", doc_title.lower()).strip() if doc_title else ""
    norm_author = re.sub(r"\W+", " ", doc_author.lower()).strip() if doc_author else ""

    leading_headings = list(soup.find_all(["h1", "h2", "h3"]))[:3]
    for h in leading_headings:
        h_text = re.sub(r"\W+", " ", h.get_text().lower()).strip()
        if (norm_title and (h_text == norm_title or (len(norm_title) > 8 and norm_title in h_text))) or \
           (norm_author and (h_text == norm_author or (len(norm_author) > 6 and norm_author in h_text))):
            h.decompose()

    # 3. Fusionar encabezados adyacentes de numeración / sección
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
                r"^(PRIMERA|SEGUNDA|TERCERA|CUARTA|QUINTA|SEXTA|S[ÉE]PTIMA|OCTAVA|NOVENA|D[ÉE]CIMA|PARTE\s+\w+|CAP[ÍI]TULO\s+\w+).*$",
                t1, re.I
            ):
                separator = ": " if not t1.endswith(":") else " "
                h2.string = f"{t1}{separator}{t2}"
                h1.decompose()


def process_and_extract_images(soup: BeautifulSoup, base_url: str, max_width: int = 1600) -> List[Dict[str, Any]]:
    """
    Descarga y optimiza las imágenes referenciadas en el HTML para empaquetarlas en el EPUB.
    Convierte formatos no estándares (como WebP o TIFF) a JPEG/PNG para compatibilidad con Kindle.
    Actualiza el atributo src en el soup a la ruta relativa interna 'images/img_XXX.ext'.
    Retorna la lista de diccionarios con metadatos y bytes de cada imagen.
    """
    images_list = []
    headers = {"User-Agent": DEFAULT_USER_AGENT, "Referer": base_url}

    # Procesar <picture> dejando solo el <img>
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

            # Evitar SVG decorativos diminutos o tracking pixels
            if "data:image/svg" in raw_src and "pixel" in raw_src:
                img.decompose()
                continue

            try:
                if raw_src.startswith("data:image/"):
                    # Procesar Data URI existente
                    header, data = raw_src.split(",", 1)
                    import base64
                    img_bytes = base64.b64decode(data)
                else:
                    abs_url = urljoin(base_url, raw_src)
                    resp = client.get(abs_url)
                    if resp.status_code != 200 or not resp.content:
                        img.decompose()
                        continue
                    img_bytes = resp.content

                # Verificar y optimizar con Pillow
                pil_img = Image.open(io.BytesIO(img_bytes))
                orig_format = pil_img.format or "JPEG"

                # Descartar iconos extremadamente pequeños (ej. avatars o badges < 20x20)
                if pil_img.width < 30 and pil_img.height < 30:
                    img.decompose()
                    continue

                # Redimensionar si es excesivamente grande para un e-reader
                if pil_img.width > max_width:
                    ratio = max_width / float(pil_img.width)
                    new_height = int(float(pil_img.height) * ratio)
                    pil_img = pil_img.resize((max_width, new_height), Image.Resampling.LANCZOS)

                # Convertir formatos raros o WebP a JPEG o PNG
                output_ext = "jpg"
                media_type = "image/jpeg"
                save_format = "JPEG"

                if orig_format.upper() in ("PNG", "GIF"):
                    output_ext = orig_format.lower()
                    media_type = f"image/{orig_format.lower()}"
                    save_format = orig_format.upper()
                else:
                    # Si tiene canal alfa (RGBA) y convertimos a JPEG, quitar alfa
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

                # Actualizar tag en el soup
                img["src"] = epub_rel_path

                # Limpiar atributos superfluos
                for attr in ["srcset", "data-src", "data-original", "data-lazy-src", "loading", "sizes", "style"]:
                    if img.has_attr(attr):
                        del img[attr]

                images_list.append({
                    "id": item_id,
                    "filename": filename,
                    "rel_path": epub_rel_path,
                    "content": final_bytes,
                    "media_type": media_type
                })
                img_counter += 1

            except Exception:
                # Si falla la descarga o procesamiento, eliminar la imagen rota
                img.decompose()

    return images_list


def fetch_article_metadata(url: str) -> Dict[str, Any]:
    """
    Extrae rápidamente los metadatos de un artículo web para la vista previa editable.
    """
    raw_html, final_url = fetch_raw_html(url, timeout=12.0)
    meta = trafilatura.extract_metadata(raw_html)

    title = meta.title if meta and meta.title else ""
    author = meta.author if meta and meta.author else ""
    date = meta.date if meta and meta.date else ""
    sitename = meta.sitename if meta and meta.sitename else urlparse(final_url).netloc

    soup = BeautifulSoup(raw_html, "html.parser")

    # Heurística para títulos clásicos tipo "Autor (Año): Título"
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
        title = h1.get_text(strip=True) if h1 else (soup.title.string.strip() if soup.title else "")

    if not author:
        meta_author = soup.find("meta", attrs={"name": re.compile(r"author", re.I)})
        if meta_author and meta_author.get("content"):
            author = meta_author["content"].strip()

    return {
        "title": title.strip() if title else "Artículo Web",
        "author": author.strip() if author and author.lower() not in ("none", "null") else "Autor Desconocido",
        "date": date.strip() if date else "",
        "sitename": sitename.strip() if sitename else urlparse(final_url).netloc,
        "url": final_url
    }


def extract_clean_article(url: str, include_images: bool = True) -> Dict[str, Any]:
    """
    Procesa de manera completa el artículo web:
    - Descarga con encoding seguro.
    - Pre-limpieza y envoltura semántica.
    - Extracción con Trafilatura (con fallback a BeautifulSoup).
    - Normalización de títulos y subtítulos.
    - Descarga y empaquetado de imágenes optimizadas para EPUB.
    """
    raw_html, final_url = fetch_raw_html(url)
    cleaned_html = pre_clean_html(raw_html)

    # Metadatos base
    meta_info = fetch_article_metadata(url)
    title = meta_info["title"]
    author = meta_info["author"]
    date = meta_info["date"]
    sitename = meta_info["sitename"]

    # Contar encabezados en original
    raw_soup = BeautifulSoup(cleaned_html, "html.parser")
    raw_headings_count = len(raw_soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]))

    # Extracción de trafilatura
    extracted_html = trafilatura.extract(
        cleaned_html,
        output_format="html",
        include_formatting=True,
        include_images=include_images,
        include_links=True
    )

    ext_soup = BeautifulSoup(extracted_html or "", "html.parser")
    ext_headings_count = len(ext_soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]))

    # Fallback si trafilatura falló, el texto es ínfimo o eliminó encabezados presentes en el original
    if not extracted_html or len(extracted_html.strip()) < 120 or (raw_headings_count > 0 and ext_headings_count == 0):
        soup = BeautifulSoup(cleaned_html, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "aside", "header", "iframe", "noscript"]):
            tag.decompose()

        article_node = soup.find("article") or soup.find("main") or soup.find(class_=re.compile(r"content|post|entry|article", re.I))
        if article_node:
            extracted_html = str(article_node)
        else:
            body = soup.find("body")
            extracted_html = str(body) if body else str(soup)

    soup = BeautifulSoup(extracted_html or "<p>No se pudo extraer contenido.</p>", "html.parser")
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
        "html_body": str(soup),
        "images": images
    }
