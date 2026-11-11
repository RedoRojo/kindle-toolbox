"""
Kindle Toolbox - Servidor Web FastAPI
Conversor de artículos web y documentos PDF a libros electrónicos EPUB3 optimizados para pantallas E-Ink y Kindle.
"""

import os
import shutil
import time
import uuid
from pathlib import Path
from typing import Dict, Any, Optional, List

from fastapi import FastAPI, HTTPException, Request, BackgroundTasks, UploadFile, File, Form
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from core.scraper import extract_clean_article, fetch_article_metadata
from core.epub_generator import create_epub_book, create_multi_chapter_epub, OUTPUT_DIR
from core.pdf_to_epub import extract_structured_pdf

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(
    title="Kindle Toolbox",
    description="Conversor de artículos web y PDFs a EPUB optimizado para lectores de tinta electrónica y Kindle"
)

# Estáticos y plantillas
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# Caché en memoria para extracciones y PDFs analizados
EXTRACTION_CACHE: Dict[str, Dict[str, Any]] = {}
PDF_CACHE: Dict[str, Dict[str, Any]] = {}


def cleanup_expired_cache_and_files():
    """Limpia elementos cacheados y archivos generados mayores a 2 horas."""
    now = time.time()
    # Limpiar caché en memoria de artículos
    expired_art = [k for k, v in EXTRACTION_CACHE.items() if now - v["created_at"] > 3600]
    for k in expired_art:
        EXTRACTION_CACHE.pop(k, None)

    # Limpiar caché en memoria de PDFs
    expired_pdf = [k for k, v in PDF_CACHE.items() if now - v["created_at"] > 3600]
    for k in expired_pdf:
        PDF_CACHE.pop(k, None)

    # Limpiar archivos de salida en disco
    try:
        for f in OUTPUT_DIR.iterdir():
            if f.is_file() and (now - f.stat().st_mtime) > 7200:
                f.unlink(missing_ok=True)
    except Exception:
        pass

    # Limpiar archivos subidos en disco
    try:
        for f in UPLOAD_DIR.iterdir():
            if f.is_file() and (now - f.stat().st_mtime) > 7200:
                f.unlink(missing_ok=True)
    except Exception:
        pass


class ExtractRequest(BaseModel):
    url: str
    include_images: bool = True


class GenerateRequest(BaseModel):
    extract_id: Optional[str] = None
    url: str
    title: str
    author: Optional[str] = "Autor Desconocido"
    date: Optional[str] = ""
    sitename: Optional[str] = ""
    html_body: Optional[str] = None
    paragraph_style: Optional[str] = "book"  # "book" o "article"
    generate_cover: Optional[bool] = True


class PdfConvertRequest(BaseModel):
    pdf_id: str
    title: Optional[str] = None
    author: Optional[str] = None
    paragraph_style: Optional[str] = "book"
    generate_cover: Optional[bool] = True


@app.get("/", response_class=HTMLResponse)
async def index_page(request: Request):
    """Página principal de la aplicación."""
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={}
    )


# ==========================================
# RUTAS DE ARTÍCULO WEB A EPUB
# ==========================================

@app.post("/api/extract")
async def extract_article_endpoint(req: ExtractRequest, background_tasks: BackgroundTasks):
    """
    Descarga y procesa el artículo web, devolviendo metadatos y HTML limpio
    para previsualización y edición antes de generar el libro.
    """
    url = req.url.strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="URL inválida. Debe comenzar con http:// o https://")

    try:
        article = extract_clean_article(url, include_images=req.include_images)
        extract_id = str(uuid.uuid4())
        EXTRACTION_CACHE[extract_id] = {
            "data": article,
            "created_at": time.time()
        }

        background_tasks.add_task(cleanup_expired_cache_and_files)

        return {
            "extract_id": extract_id,
            "title": article["title"],
            "author": article["author"],
            "date": article["date"],
            "sitename": article["sitename"],
            "url": article["url"],
            "html_body": article["html_body"],
            "images_count": len(article.get("images", []))
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al extraer el artículo: {str(e)}")


@app.post("/api/generate")
async def generate_epub_endpoint(req: GenerateRequest, background_tasks: BackgroundTasks):
    """
    Genera el archivo EPUB con los metadatos editados y el estilo seleccionado.
    """
    background_tasks.add_task(cleanup_expired_cache_and_files)

    article_data = None
    if req.extract_id and req.extract_id in EXTRACTION_CACHE:
        article_data = EXTRACTION_CACHE[req.extract_id]["data"]

    if not article_data:
        if req.html_body:
            article_data = {
                "title": req.title,
                "author": req.author or "Autor Desconocido",
                "date": req.date or "",
                "sitename": req.sitename or "",
                "url": req.url,
                "html_body": req.html_body,
                "images": []
            }
        else:
            if not req.url:
                raise HTTPException(status_code=400, detail="Falta la URL de origen o el contenido HTML.")
            article_data = extract_clean_article(req.url, include_images=True)

    article_data["title"] = req.title.strip() if req.title else article_data["title"]
    article_data["author"] = req.author.strip() if req.author else article_data["author"]
    article_data["date"] = req.date.strip() if req.date else article_data["date"]
    article_data["sitename"] = req.sitename.strip() if req.sitename else article_data["sitename"]
    if req.html_body:
        article_data["html_body"] = req.html_body

    paragraph_style = req.paragraph_style if req.paragraph_style in ("book", "article") else "book"
    generate_cover = bool(req.generate_cover)

    try:
        result = create_epub_book(
            article_data=article_data,
            paragraph_style=paragraph_style,
            generate_cover=generate_cover
        )
        return {
            "success": True,
            "filename": result["filename"],
            "download_url": f"/api/download/{result['filename']}",
            "filesize": result["filesize"],
            "title": result["title"],
            "author": result["author"]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al compilar el EPUB: {str(e)}")


# ==========================================
# RUTAS DE PDF A EPUB VERSÁTIL
# ==========================================

@app.get("/api/pdf/local-files")
async def list_local_pdfs():
    """
    Lista los archivos PDF detectados en la carpeta del proyecto y descargas para facilitar su selección.
    """
    files = []
    seen_paths = set()

    def add_file(f: Path):
        p_str = str(f.resolve())
        if p_str not in seen_paths and f.is_file() and f.suffix.lower() == ".pdf":
            seen_paths.add(p_str)
            files.append({
                "name": f.name,
                "path": p_str,
                "size": f.stat().st_size
            })

    # 1. Directorio actual de kindle-toolbox
    for f in sorted(BASE_DIR.glob("*.pdf")):
        add_file(f)

    # 2. Carpeta de descargas del usuario (los 15 más recientes)
    downloads_dir = Path.home() / "Downloads"
    if downloads_dir.exists():
        dl_pdfs = sorted(downloads_dir.glob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)[:15]
        for f in dl_pdfs:
            add_file(f)

    # 3. Carpeta contenedora
    parent_dir = BASE_DIR.parent
    if parent_dir.exists():
        for f in sorted(parent_dir.glob("*.pdf")):
            add_file(f)

    return {"files": files}


@app.post("/api/pdf/analyze")
async def analyze_pdf_endpoint(
    background_tasks: BackgroundTasks,
    local_path: Optional[str] = Form(None),
    col_mode: str = Form("auto"),
    file: Optional[UploadFile] = File(None)
):
    """
    Inspecciona y estructura el documento PDF (detectando columnas, notas al pie y capítulos).
    """
    target_path = None

    if file and file.filename:
        # Guardar archivo subido en uploads/
        safe_name = f"{uuid.uuid4()}_{Path(file.filename).name}"
        save_path = UPLOAD_DIR / safe_name
        with open(save_path, "wb") as buf:
            shutil.copyfileobj(file.file, buf)
        target_path = save_path
    elif local_path:
        # Resolver ruta local dentro del entorno
        clean_p = Path(local_path).resolve()
        if clean_p.exists() and clean_p.is_file() and clean_p.suffix.lower() == ".pdf":
            target_path = clean_p

    if not target_path or not target_path.exists():
        raise HTTPException(status_code=400, detail="No se proporcionó un archivo PDF válido.")

    background_tasks.add_task(cleanup_expired_cache_and_files)

    try:
        structured_data = extract_structured_pdf(str(target_path), col_mode=col_mode)
        pdf_id = str(uuid.uuid4())

        PDF_CACHE[pdf_id] = {
            "data": structured_data,
            "filepath": str(target_path),
            "created_at": time.time()
        }

        # Preparar resumen liviano para el frontend
        chapters_summary = [
            {
                "id": c["id"],
                "title": c["title"],
                "preview": c["html_body"][:320] + "...",
                "footnotes_count": c["footnotes_count"]
            }
            for c in structured_data["chapters"]
        ]

        return {
            "pdf_id": pdf_id,
            "title": structured_data["title"],
            "author": structured_data["author"],
            "total_pages": structured_data["total_pages"],
            "detected_col_mode": structured_data["detected_col_mode"],
            "dominant_cols": structured_data["dominant_cols"],
            "chapters_count": structured_data["chapters_count"],
            "total_footnotes": structured_data["total_footnotes"],
            "chapters": chapters_summary
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al analizar el PDF: {str(e)}")


@app.post("/api/pdf/convert")
async def convert_pdf_endpoint(req: PdfConvertRequest, background_tasks: BackgroundTasks):
    """
    Compila el EPUB multi-capítulo a partir de los datos analizados del PDF.
    """
    background_tasks.add_task(cleanup_expired_cache_and_files)

    if not req.pdf_id or req.pdf_id not in PDF_CACHE:
        raise HTTPException(status_code=404, detail="Sesión de análisis PDF no encontrada o expirada. Por favor analiza de nuevo.")

    cached = PDF_CACHE[req.pdf_id]
    pdf_data = cached["data"]

    # Aplicar ediciones del usuario
    if req.title:
        pdf_data["title"] = req.title.strip()
    if req.author:
        pdf_data["author"] = req.author.strip()

    paragraph_style = req.paragraph_style if req.paragraph_style in ("book", "article") else "book"
    generate_cover = bool(req.generate_cover)

    try:
        result = create_multi_chapter_epub(
            book_data=pdf_data,
            chapters=pdf_data["chapters"],
            paragraph_style=paragraph_style,
            generate_cover=generate_cover
        )

        return {
            "success": True,
            "filename": result["filename"],
            "download_url": f"/api/download/{result['filename']}",
            "filesize": result["filesize"],
            "title": result["title"],
            "author": result["author"],
            "chapters_count": result["chapters_count"]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al compilar el EPUB: {str(e)}")


@app.get("/api/download/{filename}")
async def download_epub(filename: str):
    """Descarga directa del EPUB generado."""
    safe_name = Path(filename).name
    target_path = OUTPUT_DIR / safe_name

    if not target_path.exists() or not target_path.is_file():
        raise HTTPException(status_code=404, detail="Archivo no encontrado o expirado.")

    return FileResponse(
        path=target_path,
        media_type="application/epub+zip",
        filename=safe_name
    )
