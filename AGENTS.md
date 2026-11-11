# Agent Guide — Kindle Toolbox (`tools kindle`)

Fast reference for AI agents invoking or maintaining `kindle-toolbox`.

## 1. Invoking from an Agent

- **Never start the web server (`./run.sh`)** to convert articles or PDFs. Always invoke `tools kindle` (or `./cli.sh`).
- **Always pass `--json -q`** for structured JSON output on `stdout` and silent progress on `stderr`.
- **Default output location**: current working directory (`<Title> - <Author>.epub`, never overwrites existing files). Pass `-o <path.epub>` to write to an exact path.
- **Exit codes**: `0` = success, `1` = runtime error, `2` = usage error.

### Common Recipes

```bash
# 1. Convert a web article URL into a reflowable EPUB3 book
tools kindle web "https://example.com/essay" -o essay.epub --json -q
tools kindle web "https://example.com/essay" --title "Custom Title" --author "Author" --style article --no-images --json -q

# 2. Inspect detected chapters, layout columns, and footnotes in a PDF book (fast, no conversion)
tools kindle pdf-info book.pdf --json -q

# 3. Convert a PDF book into a multi-chapter reflowable EPUB3 (columns: auto | 1 | 2)
tools kindle pdf book.pdf --columns auto --title "Book Title" --author "Author" -o book.epub --json -q
```

### JSON Output Schemas (`--json`)

- **`web` / `pdf`**:
  ```json
  {
    "filename": "Book Title - Author.epub",
    "filepath": "/abs/path/Book Title - Author.epub",
    "filesize": 48210,
    "title": "Book Title",
    "author": "Author",
    "chapters_count": 8
  }
  ```
- **`pdf-info`**:
  ```json
  {
    "title": "Book Title",
    "author": "Author",
    "language": "es",
    "total_pages": 120,
    "detected_col_mode": "single",
    "dominant_cols": 1,
    "chapters_count": 8,
    "total_footnotes": 14,
    "chapters": [
      { "id": "chap_1", "title": "Chapter 1", "footnotes_count": 2 }
    ],
    "filepath": "/abs/path/book.pdf"
  }
  ```

## 2. Codebase Map

- `core/scraper.py`: `extract_clean_article`, `fetch_article_metadata` (Trafilatura + BeautifulSoup + Pillow image optimization).
- `core/pdf_to_epub.py`: `extract_structured_pdf` (column detection, de-hyphenation, footnote linking, chapter splitting).
- `core/epub_generator.py`: `create_epub_book`, `create_multi_chapter_epub`, `build_epub_from_url`, `build_epub_from_pdf`, `analyze_pdf`.
- `cli.py` / `cli.sh`: CLI adapter (`argparse`). Uses Miniconda env `~/miniconda3/envs/pdf-toolkit`.
- `tests/test_cli.py`: Run with `~/miniconda3/envs/pdf-toolkit/bin/python -m unittest discover -s tests -v`.
