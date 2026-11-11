"""
Motor de conversión versátil de PDF a EPUB para Kindle Toolbox.
Especializado en manejar PDFs complejos con maquetación en columnas,
desguionado automático de palabras, extracción y vinculación de notas al pie,
limpieza de encabezados/pies de página y división inteligente de capítulos.
"""

import os
import re
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional

import pymupdf
from bs4 import BeautifulSoup


def clean_pdf_text_artifacts(text: str) -> str:
    """
    Sanea artefactos de codificación comunes en PDFs generados por Ghostscript/PDFCreator:
    - \x02 y \x15 corresponden a la letra 'N' mayúscula.
    - Elimina caracteres de control ASCII no imprimibles.
    """
    if not text:
        return ""
    # Reemplazo de caracteres específicos de encoding defectuoso
    t = text.replace("\x02", "N").replace("\x15", "N")
    # Limpieza de otros caracteres de control
    t = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x14\x16-\x1f]", "", t)
    return t


def clean_title_and_author(raw_title: str, raw_author: str, filename: str = "") -> Tuple[str, str]:
    """
    Limpia el título y autor removiendo etiquetas de descarga comunes como:
    (z-library.sk, 1lib.sk, z-lib.sk), (libgen), [b-ok], etc.
    Extrae además nombres limpios desde el nombre del archivo si es necesario.
    """
    # Patrón para eliminar URLs y repositorios entre paréntesis o corchetes
    junk_pattern = re.compile(
        r"\s*[\(\[](?:z-library|1lib|z-lib|b-ok|libgen|oceanofpdf|dokumen)[\w\.\s,-]*[\)\]]",
        re.IGNORECASE
    )

    t = clean_pdf_text_artifacts(raw_title or "").strip()
    a = clean_pdf_text_artifacts(raw_author or "").strip()
    fn = Path(filename).stem if filename else ""

    # Limpiar junk tags del título y del filename
    t = junk_pattern.sub("", t).strip()
    fn_clean = junk_pattern.sub("", fn).strip()

    # Si el título es muy corto, genérico o vacío, extraer del nombre de archivo
    if not t or len(t) < 3 or t.lower() in ("documento", "microsoft word", "untitled", "sin título"):
        t = fn_clean

    # Si el nombre de archivo tiene formato "Título (Autor)" o "Autor - Título"
    if "(" in t and ")" in t:
        m = re.match(r"^([^(]+)\s*\(([^)]+)\)\s*$", t)
        if m:
            candidate_title = m.group(1).strip()
            candidate_author = m.group(2).strip()
            # Si el autor entre paréntesis no es una etiqueta genérica
            if len(candidate_author) > 2 and not junk_pattern.search(f"({candidate_author})"):
                t = candidate_title
                if not a or a.lower() in ("autor desconocido", "desconocido", "usuario", "user", "admin", "none", ""):
                    a = candidate_author

    # Si el autor es genérico, intentar inferir del nombre de archivo original
    if (not a or a.lower() in ("autor desconocido", "desconocido", "usuario", "user", "admin", "none", "")) and "(" in fn_clean:
        m = re.match(r"^([^(]+)\s*\(([^)]+)\)", fn_clean)
        if m:
            candidate_author = m.group(2).strip()
            if not junk_pattern.search(f"({candidate_author})"):
                a = candidate_author
                if not t:
                    t = m.group(1).strip()

    # Limpiar autor de etiquetas
    a = junk_pattern.sub("", a).strip()
    if not a or a.lower() in ("usuario", "user", "admin", "none", ""):
        a = "Autor Desconocido"

    # Si el título quedó con espacios dobles o guiones sueltos
    t = re.sub(r"\s+", " ", t).strip(" -_")
    a = re.sub(r"\s+", " ", a).strip(" -_")

    return t or "Libro Digital", a or "Autor Desconocido"


def is_title_credits_page(page: pymupdf.Page) -> bool:
    """
    Detecta si una página inicial es la portada/portadilla o página de créditos del PDF original.
    Generalmente contiene poco texto (< 650 caracteres) y palabras clave como
    'Edición:', 'Lengua:', 'Editorial', 'ISBN', 'Digitalización:', etc.
    """
    text = clean_pdf_text_artifacts(page.get_text("text")).strip()
    if not text or len(text) > 750:
        return False

    keywords = [
        "edición:", "edicion:", "lengua:", "digitalización:", "digitalizacion:",
        "distribución:", "distribucion:", "editorial", "isbn", "traducción:",
        "traduccion:", "copyright", "todos los derechos", "publicado por", "impreso en"
    ]
    matches = sum(1 for kw in keywords if kw in text.lower())
    return matches >= 2 or (len(text) < 300 and matches >= 1)


def extract_p1_info(page: pymupdf.Page) -> Tuple[str, str, str]:
    """
    Extrae título, autor e información de edición de la primera página de créditos/portadilla.
    Retorna (título_detectado, autor_detectado, info_creditos_html).
    """
    text = clean_pdf_text_artifacts(page.get_text("text")).strip()
    lines = [clean_pdf_text_artifacts(l).strip() for l in text.splitlines() if l.strip()]

    title_candidate = ""
    author_candidate = ""
    credits_lines = []

    for l in lines:
        l_low = l.lower()
        if any(kw in l_low for kw in ("edición:", "lengua:", "digitalización:", "distribución:", "editorial", "isbn", "traducción:")):
            credits_lines.append(l)
        elif not title_candidate and len(l) > 3 and not any(kw in l_low for kw in ("http:", "www.", "koba", "bolchetvo")):
            title_candidate = l
        elif title_candidate and not author_candidate and len(l) > 2 and not any(kw in l_low for kw in ("http:", "www.")):
            author_candidate = l
        else:
            credits_lines.append(l)

    # Formatear créditos en párrafos limpios
    credits_html = "".join(f"<p>{cl}</p>" for cl in credits_lines) if credits_lines else ""
    return title_candidate, author_candidate, credits_html


def is_printed_toc_page(page: pymupdf.Page) -> bool:
    """
    Detecta si la página corresponde a un índice de contenido impreso con números de página
    y puntos de relleno (líderes '....... 15'), para excluirlo de la narración del EPUB
    (la navegación en un EPUB debe ser manejada por el TOC digital nav.xhtml / toc.ncx).
    """
    text = clean_pdf_text_artifacts(page.get_text("text"))
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if not lines:
        return False

    # Buscar cabecera de índice
    has_toc_header = bool(re.search(r"^\s*(ÍNDICE|INDICE|TABLA\s+DE\s+CONTENIDO)\b", text, re.I))

    # Contar líneas con puntos suspensivos o puntos de relleno seguidos de número
    dotted_lines = sum(
        1 for l in lines
        if re.search(r"(\.{3,}|\…|\.\s*\.\s*\.)\s*\d+\s*$", l) or re.search(r"(\.{3,}|\…)", l)
    )

    if has_toc_header and (dotted_lines >= 3 or len(lines) < 25):
        return True

    if dotted_lines >= 5:
        return True

    return False


def detect_page_columns(page: pymupdf.Page, top_margin: float = 56.0, bottom_margin: float = 802.0) -> Tuple[int, float]:
    """
    Detecta automáticamente si la página está a 1 o 2 columnas analizando la distribución
    horizontal de los bloques de texto. Retorna (num_columnas, gutter_mid_x).
    """
    page_w = page.rect.width
    mid_x = page_w / 2.0

    blocks = page.get_text("blocks")
    # Filtrar bloques útiles dentro del margen
    useful_blocks = [
        b for b in blocks
        if b[4].strip() and b[3] > top_margin and b[1] < bottom_margin
    ]

    if not useful_blocks:
        return 1, mid_x

    # Comprobar cuántos bloques caen claramente a la izquierda o derecha
    left_count = 0
    right_count = 0
    spanning_count = 0

    gutter_left = mid_x - 30
    gutter_right = mid_x + 30

    for b in useful_blocks:
        x0, y0, x1, y1 = b[:4]
        # Si el bloque cruza el medio con amplitud significativa
        if x0 < gutter_left and x1 > gutter_right:
            spanning_count += 1
        elif x1 <= mid_x + 15:
            left_count += 1
        elif x0 >= mid_x - 15:
            right_count += 1

    # Si encontramos bloques simultáneos a la izquierda y derecha
    if left_count >= 1 and right_count >= 1:
        return 2, mid_x

    return 1, mid_x


def extract_block_footnotes(
    block: Dict[str, Any],
    dominant_size: float = 11.0,
    page_height: float = 842.0
) -> Tuple[Optional[Dict[str, Any]], Dict[str, str]]:
    """
    Inspecciona las líneas de un bloque de texto y extrae de forma precisa
    las notas al pie (iniciadas por número de nota con tipografía reducida o al fondo de la página).
    Retorna el bloque depurado (solo con líneas del cuerpo) y un diccionario {num_nota: texto_nota}.
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

        # Comprobar si la línea inicia una nota al pie
        m = re.match(r"^(\d{1,3})\s+([A-ZÁÉÍÓÚ\(\"“].*)", line_t)
        is_fn_start = False
        if m:
            # Nota al pie si el tamaño es menor al dominante o está en el tercio inferior
            if sz < dominant_size - 0.7 or y > (page_height * 0.60):
                is_fn_start = True

        if is_fn_start:
            if curr_fn_num and curr_fn_lines:
                footnotes[curr_fn_num] = " ".join(curr_fn_lines)
            curr_fn_num = m.group(1)
            curr_fn_lines = [line_t]
        elif curr_fn_num is not None:
            # Continuación de la nota actual si mantiene tamaño reducido o posición baja
            if sz < dominant_size - 0.4 or y > (page_height * 0.65):
                curr_fn_lines.append(line_t)
            else:
                # Regreso al texto del cuerpo
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
            max(bx[3] for bx in line_boxes)
        )
    return new_b, footnotes


def extract_page_elements(
    page: pymupdf.Page,
    col_mode: str = "auto",
    dominant_font: str = "TimesNewRoman",
    dominant_size: float = 11.0,
    top_margin: float = 56.0,
    bottom_margin: float = 802.0
) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    """
    Extrae los bloques de texto de una página en estricto orden de lectura:
    - Cabeceras y números de página excluidos.
    - En páginas de 2 columnas: Columna izquierda completa primero, luego columna derecha.
    - Notas al pie detectadas y extraídas del flujo para evitar interrumpir la lectura.
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
        if b.get("type") != 0:  # solo texto
            continue

        bbox = b.get("bbox", (0, 0, 0, 0))
        # Filtrar encabezados de página (y3 <= top_margin) y pies marginales (y1 >= bottom_margin)
        if bbox[3] <= top_margin or bbox[1] >= bottom_margin:
            continue

        # Extraer notas al pie línea por línea dentro del bloque para no mezclar texto
        new_b, b_fns = extract_block_footnotes(b, dominant_size=dominant_size, page_height=page_h)
        if b_fns:
            page_footnotes.update(b_fns)

        if new_b is not None:
            body_blocks.append(new_b)

    if cols == 1:
        # Una columna: ordenar simplemente de arriba a abajo
        body_blocks.sort(key=lambda b: (b["bbox"][1], b["bbox"][0]))
        return body_blocks, page_footnotes

    # Dos columnas: clasificar en pasantes, izquierda y derecha
    col_left = []
    col_right = []
    spanning_top = []
    spanning_bottom = []

    gutter_left = mid_x - 30
    gutter_right = mid_x + 30

    for b in body_blocks:
        x0, y0, x1, y1 = b["bbox"]
        if x0 < gutter_left and x1 > gutter_right:
            if y0 < page_h * 0.35:
                spanning_top.append(b)
            else:
                spanning_bottom.append(b)
        elif (x0 + x1) / 2.0 < mid_x:
            col_left.append(b)
        else:
            col_right.append(b)

    # Ordenar verticalmente cada sección
    spanning_top.sort(key=lambda b: b["bbox"][1])
    col_left.sort(key=lambda b: b["bbox"][1])
    col_right.sort(key=lambda b: b["bbox"][1])
    spanning_bottom.sort(key=lambda b: b["bbox"][1])

    # Secuencia de lectura natural
    ordered = spanning_top + col_left + col_right + spanning_bottom
    return ordered, page_footnotes


def is_section_subtitle(text: str, prev_text: str = "", next_text: str = "") -> bool:
    """
    Detecta si una línea aislada representa un subtítulo o división de sección interna
    (por ejemplo, numerales romanos 'I', 'II', 'III', 'IV' que dividen prefacios o partes).
    """
    t = text.strip()
    if not re.match(r"^[IVXLCDM]{1,6}\.?$", t):
        return False
    # Debe estar seguido por un párrafo que comience con mayúscula o comillas
    if not next_text or not re.match(r"^[A-ZÁÉÍÓÚ\"“]", next_text.strip()):
        return False
    if not prev_text:
        return True
    # La línea anterior debe haber terminado con puntuación, cierre o ser corta (firma/fecha)
    is_terminal = bool(re.search(r"[\.!?:\)\]\"”\x15]\s*$", prev_text.strip()))
    is_short = len(prev_text.strip()) < 50
    return is_terminal or is_short


def reassemble_lines_and_dehyphenate(lines_raw: List[Dict[str, Any]]) -> List[str]:
    """
    Une las líneas de texto reconstruyendo párrafos y desguionando palabras partidas al final de línea.
    Identifica subtítulos de sección internos (__SUBTITLE__) y separadores ornamentales (__ASTERISM__).
    """
    paragraphs = []
    current_para = []

    for idx, line_obj in enumerate(lines_raw):
        text = line_obj["text"].strip()
        if not text:
            continue

        # Saneamiento de fuentes defectuosas
        text = clean_pdf_text_artifacts(text)

        prev_text = current_para[-1] if current_para else (paragraphs[-1] if paragraphs else "")
        next_text = ""
        for next_idx in range(idx + 1, min(idx + 6, len(lines_raw))):
            cand = clean_pdf_text_artifacts(lines_raw[next_idx]["text"]).strip()
            if cand:
                next_text = cand
                break

        # 1. Comprobar si esta línea es un subtítulo de sección romano (ej: "I", "II", "III")
        if is_section_subtitle(text, prev_text, next_text):
            if current_para:
                paragraphs.append(" ".join(current_para))
                current_para = []
            paragraphs.append(f"__SUBTITLE__{text.rstrip('.')}")
            continue

        # 2. Comprobar si la línea es un asterismo o separador ornamental
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

        # Comprobar si la línea anterior termina en guión de palabra partida
        # Ej: "mate-", "econó-", pero no guiones largos como "—" o dobles "--"
        if prev_text.endswith("-") and not prev_text.endswith(("--", " -")):
            # Si la siguiente línea empieza por letra minúscula (o carácter continuador)
            if text and (text[0].islower() or text[0] in "áéíóúñ"):
                # Quitar guión y fusionar palabra directamente
                current_para[-1] = prev_text[:-1] + text
            else:
                # Mantener guión para nombres compuestos (ej: "franco-alemán")
                current_para[-1] = prev_text + text
        else:
            # Comprobar si corresponde a un nuevo párrafo o a la continuación del actual
            # Puntuación terminal completa: . ! ? : ) ] " ” '
            is_prev_terminal = bool(re.search(r"[\.!?:\)\]\"”']\s*$", prev_text))
            is_curr_indented = line_obj.get("is_indented", False)

            # Comprobar si la línea actual es una fecha/firma (ej: "Londres, 11 de junio...")
            is_curr_sig = bool(re.match(r"^[A-ZÁÉÍÓÚ][a-záéíóú]+,\s+\d{1,2}\s+de\s+[a-záéíóú]+\s+de\s+\d{4}", text))

            if (is_prev_terminal and (is_curr_indented or len(prev_text) < 45)) or is_curr_sig:
                # Guardar párrafo actual y empezar uno nuevo
                paragraphs.append(" ".join(current_para))
                current_para = [text]
            else:
                # Continuar el párrafo con un espacio
                current_para.append(text)

    if current_para:
        paragraphs.append(" ".join(current_para))

    return paragraphs


HEADING_REGEX = re.compile(
    r"^(PREFACIO|PREFACIOS|ÍNDICE|INDICE|"
    r"(PRIMERA|SEGUNDA|TERCERA|CUARTA|QUINTA|SEXTA)\s+PARTE|"
    r"[IVXLCDM]+\.\s+[A-ZÁÉÍÓÚ]|"
    r"CAP[ÍI]TULO\s+[IVXLCDM\d]+)",
    re.IGNORECASE
)


def is_heading_line(line_text: str, font_name: str, font_size: float, dominant_size: float) -> bool:
    """Detecta si una línea representa un título o encabezado de capítulo."""
    clean_t = clean_pdf_text_artifacts(line_text).strip()
    if not clean_t or len(clean_t) > 95:
        return False

    # Descartar líneas de índice impreso que contienen puntos de relleno (ej: "Prefacios ....... 1")
    if re.search(r"\.{3,}|\…|\.\s*\.\s*\.", clean_t):
        return False

    is_bold = "bold" in font_name.lower() or font_size >= dominant_size + 1.5
    if is_bold and HEADING_REGEX.search(clean_t):
        return True

    # Partes en mayúsculas destacadas
    if re.match(r"^(PRIMERA|SEGUNDA|TERCERA|CUARTA)\s+PARTE\b", clean_t, re.I):
        return True

    return False


def link_footnotes_in_text(text: str, footnotes: Dict[str, str], linked_set: Optional[set] = None) -> str:
    """
    Convierte referencias numéricas en el cuerpo del texto a enlaces interactivos de nota al pie
    con semántica EPUB3 (epub:type="noteref" role="doc-noteref") para desplegar ventanas emergentes (popups) en Kindle.
    Ejemplo: 'fecundo2' -> 'fecundo<a href="#note-2" class="footnote-ref" epub:type="noteref" role="doc-noteref"><sup>2</sup></a>'
    """
    for num in sorted(footnotes.keys(), key=lambda n: int(n) if n.isdigit() else 999, reverse=True):
        pattern = re.compile(rf"(?:\b|(?<=[a-zA-ZáéíóúÁÉÍÓÚñÑ,\.\)])){num}(?=[\s,\.;:\)]|$)", re.UNICODE)
        if pattern.search(text):
            if linked_set is not None:
                linked_set.add(num)
            replacement = rf'<a href="#note-{num}" id="ref-{num}" class="footnote-ref" epub:type="noteref" role="doc-noteref"><sup>{num}</sup></a>'
            text = pattern.sub(replacement, text, count=1)
    return text


def build_footnotes_section_html(footnotes: Dict[str, str], linked_set: Optional[set] = None) -> str:
    """
    Genera el bloque HTML de notas al pie vinculado y compatible con la ventana emergente nativa (popup footnote)
    de Amazon Kindle, Apple Books y lectores EPUB3 utilizando elementos <aside epub:type="footnote">.
    """
    if not footnotes:
        return ""

    items_html = []
    sorted_keys = sorted(footnotes.keys(), key=lambda k: int(k) if k.isdigit() else 999)

    for num in sorted_keys:
        raw_text = footnotes[num]
        cleaned_text = re.sub(rf"^\s*{num}\s+", "", raw_text).strip()
        backlink = f'<a href="#ref-{num}" class="footnote-backref" role="doc-backlink" title="Volver al texto">{num}.</a> ' if (linked_set is None or num in linked_set) else f'<strong>{num}.</strong> '
        items_html.append(
            f'<aside id="note-{num}" class="footnote-item" epub:type="footnote" role="doc-footnote">\n'
            f'  <p>{backlink}<span>{cleaned_text}</span></p>\n'
            f'</aside>'
        )

    return f"""
    <section class="footnotes-section" epub:type="footnotes" role="doc-endnotes">
      <hr class="footnotes-divider" />
      <h4 class="footnotes-title">Notas</h4>
      {"".join(items_html)}
    </section>
"""


def extract_structured_pdf(pdf_path: str, col_mode: str = "auto") -> Dict[str, Any]:
    """
    Procesa de principio a fin el archivo PDF:
    - Analiza metadatos y fuentes predominantes.
    - Extrae el texto en orden natural por columnas, eliminando cabeceras y pies repetitivos.
    - Desguiona palabras y reconstruye párrafos semánticos.
    - Separa y vincula las notas al pie.
    - Divide el contenido en capítulos con títulos reconocidos.
    """
    path_obj = Path(pdf_path)
    if not path_obj.exists():
        raise FileNotFoundError(f"Archivo no encontrado: {pdf_path}")

    doc = pymupdf.open(str(path_obj))
    total_pages = len(doc)

    # 1. Detectar metadatos base y limpiar nombres
    meta = doc.metadata or {}
    raw_title = meta.get("title", "").strip()
    raw_author = meta.get("author", "").strip()
    title, author = clean_title_and_author(raw_title, raw_author, filename=path_obj.name)

    # 1.1 Inspeccionar primera página (portadilla / créditos editoriales)
    edition_info = ""
    start_pno = 0
    if total_pages > 0 and is_title_credits_page(doc[0]):
        p1_title, p1_author, p1_credits = extract_p1_info(doc[0])
        if p1_title and (not title or title == path_obj.stem or len(title) > len(p1_title)):
            cleaned_p1_t, _ = clean_title_and_author(p1_title, author, filename=path_obj.name)
            if cleaned_p1_t:
                title = cleaned_p1_t
        if p1_author and (not author or author == "Autor Desconocido"):
            _, cleaned_p1_a = clean_title_and_author(title, p1_author, filename=path_obj.name)
            if cleaned_p1_a:
                author = cleaned_p1_a
        edition_info = p1_credits
        start_pno = 1

    # 1.2 Inspeccionar páginas iniciales en busca de Índice de contenidos impreso
    # para omitirlo del cuerpo narrativo del libro (la navegación la gestiona el TOC digital)
    while start_pno < min(5, total_pages) and is_printed_toc_page(doc[start_pno]):
        start_pno += 1

    # 2. Muestreo de páginas para determinar fuente y tamaño predominante
    sample_pages = min(15, total_pages - start_pno) if total_pages > start_pno else 1
    fonts_counter = {}
    sizes_counter = {}
    col_detections = []

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

    # 3. Extracción de todas las páginas narrativas
    raw_document_lines = []
    all_footnotes = {}
    page_footnotes_map = {}

    for pno in range(start_pno, total_pages):
        page = doc[pno]
        ordered_blocks, page_fns = extract_page_elements(
            page,
            col_mode=col_mode,
            dominant_font=dominant_font,
            dominant_size=dominant_size
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

                # Determinar si tiene sangría relativa
                is_indented = (bbox[0] % 250) > 8.0

                raw_document_lines.append({
                    "text": line_text,
                    "font": font_name,
                    "size": font_size,
                    "is_indented": is_indented,
                    "page": pno + 1
                })

    # 4. Segmentación en capítulos según encabezados detectados
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
            "footnotes": cfns
        }

    chapters = []
    current_chap_title = ""
    current_part_title = ""
    current_chap_lines = []
    chap_counter = 1

    part_regex = re.compile(r"^(PRIMERA|SEGUNDA|TERCERA|CUARTA|QUINTA|SEXTA)\s+PARTE\b", re.IGNORECASE)

    for line_obj in raw_document_lines:
        t = line_obj["text"].strip()
        f = line_obj["font"]
        sz = line_obj["size"]

        if is_heading_line(t, f, sz, dominant_size):
            clean_head = clean_pdf_text_artifacts(t).strip()

            # Comprobar si es un anuncio de PARTE (ej: "PRIMERA PARTE. FILOSOFÍA")
            if part_regex.search(clean_head):
                if current_chap_lines:
                    if current_chap_title:
                        chapters.append(make_chapter_entry(
                            f"chap_{chap_counter:02d}",
                            current_chap_title,
                            current_part_title,
                            current_chap_lines
                        ))
                        chap_counter += 1
                    current_chap_lines = []
                current_part_title = clean_head
                current_chap_title = ""
                continue

            # Si ya teníamos contenido acumulado, cerrar el capítulo anterior
            if current_chap_lines:
                if current_chap_title:
                    chapters.append(make_chapter_entry(
                        f"chap_{chap_counter:02d}",
                        current_chap_title,
                        current_part_title,
                        current_chap_lines
                    ))
                    chap_counter += 1
                else:
                    # Comprobar si las líneas previas al primer encabezado tienen contenido real sustancial
                    check_paras = reassemble_lines_and_dehyphenate(current_chap_lines)
                    if check_paras and len(" ".join(check_paras).strip()) > 120:
                        chapters.append(make_chapter_entry(
                            f"chap_{chap_counter:02d}",
                            "Prólogo",
                            current_part_title,
                            current_chap_lines
                        ))
                        chap_counter += 1
                current_chap_lines = []

            current_chap_title = clean_head
        else:
            current_chap_lines.append(line_obj)

    # Añadir último capítulo acumulado
    if current_chap_lines:
        chapters.append(make_chapter_entry(
            f"chap_{chap_counter:02d}",
            current_chap_title or "Capítulo Final",
            current_part_title,
            current_chap_lines
        ))

    # Si no se detectó ningún capítulo (o solo 1 genérico), estructurar como documento completo
    if not chapters:
        chapters.append(make_chapter_entry(
            "chap_01",
            title,
            "",
            raw_document_lines
        ))

    # 5. Formatear HTML y vincular notas al pie en cada capítulo
    structured_chapters = []
    total_footnotes_linked = 0

    for chap in chapters:
        paras_html = []
        chap_fns = dict(chap.get("footnotes", {}))
        chap_linked_refs = set()
        need_asangre = True

        # Formatear párrafos, subtítulos de sección y firmas
        for p_idx, p_text in enumerate(chap["paragraphs"]):
            if p_text.startswith("__SUBTITLE__"):
                sub_title = p_text.replace("__SUBTITLE__", "").strip()
                paras_html.append(f'<h2 class="subtitulo-seccion">{sub_title}</h2>')
                need_asangre = True
                continue

            if p_text == "__ASTERISM__":
                paras_html.append('<p class="asterism">* * *</p>')
                need_asangre = True
                continue

            # Buscar menciones a notas disponibles en el ámbito de este capítulo
            linked_p = link_footnotes_in_text(p_text, chap_fns, linked_set=chap_linked_refs)

            if need_asangre or p_idx == 0:
                p_class = ' class="asangre"'
                need_asangre = False
            elif re.match(r"^[A-ZÁÉÍÓÚ][a-záéíóú]+,\s+\d{1,2}\s+de\s+[a-záéíóú]+\s+de\s+\d{4}", p_text):
                p_class = ' class="firma-fecha"'
            elif p_text.startswith(("(", "[")) and len(p_text) < 40:
                p_class = ' class="firma-nota"'
            else:
                p_class = ""

            paras_html.append(f"<p{p_class}>{linked_p}</p>")

        # Quitar notas ya asignadas del pool global
        for k in chap_fns.keys():
            all_footnotes.pop(k, None)

        total_footnotes_linked += len(chap_fns)

        # Añadir sección de notas al pie al final del capítulo
        footnotes_html = build_footnotes_section_html(chap_fns, linked_set=chap_linked_refs)
        full_chap_body = "\n".join(paras_html) + footnotes_html

        structured_chapters.append({
            "id": chap["id"],
            "title": chap["title"],
            "part": chap.get("part", ""),
            "html_body": full_chap_body,
            "footnotes_count": len(chap_fns)
        })

    # Si quedaron notas residuales no asociadas, añadirlas al último capítulo
    if all_footnotes and structured_chapters:
        residual_html = build_footnotes_section_html(all_footnotes)
        structured_chapters[-1]["html_body"] += residual_html
        structured_chapters[-1]["footnotes_count"] += len(all_footnotes)
        total_footnotes_linked += len(all_footnotes)

    return {
        "title": title,
        "author": author,
        "edition_info": edition_info,
        "total_pages": total_pages,
        "detected_col_mode": f"{dominant_cols} columna{'s' if dominant_cols > 1 else ''}",
        "dominant_cols": dominant_cols,
        "chapters_count": len(structured_chapters),
        "total_footnotes": total_footnotes_linked,
        "chapters": structured_chapters
    }
