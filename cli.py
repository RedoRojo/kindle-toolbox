#!/usr/bin/env python3
"""
Kindle Toolbox - Command Line Interface.

Thin synchronous adapter over core/: converts web articles and PDF books into
reflowable EPUB3 e-books optimized for E-Ink displays and Kindle readers.
Never imports app.py or FastAPI.

Examples:
    tools kindle web "https://example.com/article"
    tools kindle pdf book.pdf --columns auto -o book.epub
    tools kindle pdf-info book.pdf --json
"""

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Optional

__version__ = "1.0.0"

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

PROG = os.environ.get("TOOLS_PROG", "cli.sh")
EXIT_OK, EXIT_ERROR, EXIT_USAGE, EXIT_INTERRUPTED = 0, 1, 2, 130


class CLIError(Exception):
    """Expected runtime error: printed without a traceback, exits with code 1."""


def log(args, message: str) -> None:
    if not getattr(args, "quiet", False):
        print(message, file=sys.stderr, flush=True)


def emit(args, payload: dict, human: str) -> None:
    if getattr(args, "json", False):
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif human:
        print(human)


def resolve_output(requested: Optional[str], default_name: str) -> Path:
    """Explicit -o is used as-is (dirs get default_name); otherwise write to cwd without overwriting."""
    if requested:
        path = Path(requested).expanduser()
        if path.is_dir():
            path = path / default_name
        path.parent.mkdir(parents=True, exist_ok=True)
        return path.resolve()

    path = Path.cwd() / default_name
    stem, suffix, counter = path.stem, path.suffix, 1
    while path.exists():
        path = path.with_name(f"{stem}-{counter}{suffix}")
        counter += 1
    return path.resolve()


def require_pdf(path_str: str) -> Path:
    p = Path(path_str).expanduser()
    if not p.is_file():
        raise CLIError(f"file not found: {path_str}")
    if p.suffix.lower() != ".pdf":
        raise CLIError(f"expected a .pdf file, got: {p.name}")
    return p.resolve()


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------

def cmd_web(args) -> int:
    from core.epub_generator import build_epub_from_url, clean_filename

    url = args.url.strip()
    if not url.startswith(("http://", "https://")):
        raise CLIError("invalid URL: must start with http:// or https://")

    explicit_out = resolve_output(args.output, "article.epub") if args.output else None
    log(args, f"Extracting and converting {url} ...")
    try:
        res = build_epub_from_url(
            url=url,
            title=args.title,
            author=args.author,
            include_images=not args.no_images,
            paragraph_style=args.style,
            generate_cover=not args.no_cover,
            output_path=explicit_out,
        )
        if explicit_out is None:
            src = Path(res["filepath"])
            dest = resolve_output(None, clean_filename(res["title"], res.get("author")))
            shutil.move(str(src), str(dest))
            res["filepath"] = str(dest)
            res["filename"] = dest.name
    except Exception as e:
        raise CLIError(str(e))

    log(args, f"EPUB3 created ({res['title']} — {res['author']}):")
    emit(args, res, res["filepath"])
    return EXIT_OK


def cmd_pdf(args) -> int:
    from core.epub_generator import build_epub_from_pdf, clean_filename

    pdf_path = require_pdf(args.file)
    col_map = {"auto": "auto", "1": "single", "2": "double", "single": "single", "double": "double"}
    col_mode = col_map[args.columns]

    explicit_out = resolve_output(args.output, f"{pdf_path.stem}.epub") if args.output else None
    log(args, f"Analyzing and converting {pdf_path.name} (columns={col_mode})...")
    try:
        res = build_epub_from_pdf(
            pdf_path=str(pdf_path),
            col_mode=col_mode,
            title=args.title,
            author=args.author,
            paragraph_style=args.style,
            generate_cover=not args.no_cover,
            output_path=explicit_out,
        )
        if explicit_out is None:
            src = Path(res["filepath"])
            dest = resolve_output(None, clean_filename(res["title"], res.get("author")))
            shutil.move(str(src), str(dest))
            res["filepath"] = str(dest)
            res["filename"] = dest.name
    except Exception as e:
        raise CLIError(str(e))

    log(args, f"EPUB3 created ({res['chapters_count']} chapter(s), {res['title']}):")
    emit(args, res, res["filepath"])
    return EXIT_OK


def cmd_pdf_info(args) -> int:
    from core.epub_generator import analyze_pdf

    pdf_path = require_pdf(args.file)
    col_map = {"auto": "auto", "1": "single", "2": "double", "single": "single", "double": "double"}
    col_mode = col_map[args.columns]

    try:
        info = analyze_pdf(str(pdf_path), col_mode=col_mode)
    except Exception as e:
        raise CLIError(str(e))

    info["filepath"] = str(pdf_path)
    chap_lines = [f"  {i + 1}. {c['title']} ({c['footnotes_count']} footnotes)" for i, c in enumerate(info["chapters"])]
    human = (
        f"Title:     {info['title']}\n"
        f"Author:    {info['author']}\n"
        f"Language:  {info['language']}\n"
        f"Pages:     {info['total_pages']} (layout: {info['detected_col_mode']})\n"
        f"Footnotes: {info['total_footnotes']}\n"
        f"Chapters ({info['chapters_count']}):\n" + "\n".join(chap_lines)
    )
    emit(args, info, human)
    return EXIT_OK


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def add_common_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument("--json", action="store_true", help="print machine-readable JSON to stdout")
    p.add_argument("-q", "--quiet", action="store_true", help="suppress progress messages on stderr")
    p.add_argument("-v", "--verbose", action="store_true", help="show full tracebacks on errors")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Kindle Toolbox CLI — convert web articles and PDF books into reflowable EPUB3 e-books.",
    )
    parser.add_argument("-V", "--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    # web
    p_web = sub.add_parser("web", help="convert a web article URL into a reflowable EPUB3 book")
    p_web.add_argument("url", help="source http(s) URL")
    p_web.add_argument("--title", help="override article title")
    p_web.add_argument("--author", help="override article author")
    p_web.add_argument("--style", choices=("book", "article"), default="book",
                       help="paragraph style: indented 'book' or spaced 'article' (default: book)")
    p_web.add_argument("--no-cover", action="store_true", help="disable automatic cover generation")
    p_web.add_argument("--no-images", action="store_true", help="strip article images")
    p_web.add_argument("-o", "--output", help="output .epub file or directory")
    add_common_flags(p_web)
    p_web.set_defaults(func=cmd_web)

    # pdf
    p_pdf = sub.add_parser("pdf", help="convert a PDF book/document into a multi-chapter reflowable EPUB3")
    p_pdf.add_argument("file", help="input .pdf file")
    p_pdf.add_argument("--columns", choices=("auto", "1", "2", "single", "double"), default="auto",
                       help="column layout detection mode (default: auto)")
    p_pdf.add_argument("--title", help="override book title")
    p_pdf.add_argument("--author", help="override book author")
    p_pdf.add_argument("--style", choices=("book", "article"), default="book",
                       help="paragraph style: indented 'book' or spaced 'article' (default: book)")
    p_pdf.add_argument("--no-cover", action="store_true", help="disable automatic cover generation")
    p_pdf.add_argument("-o", "--output", help="output .epub file or directory")
    add_common_flags(p_pdf)
    p_pdf.set_defaults(func=cmd_pdf)

    # pdf-info
    p_info = sub.add_parser("pdf-info", help="inspect detected chapters, columns, and footnotes of a PDF without converting")
    p_info.add_argument("file", help="input .pdf file")
    p_info.add_argument("--columns", choices=("auto", "1", "2", "single", "double"), default="auto",
                        help="column layout detection mode (default: auto)")
    add_common_flags(p_info)
    p_info.set_defaults(func=cmd_pdf_info)

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not getattr(args, "func", None):
        parser.print_help(sys.stderr)
        return EXIT_USAGE

    try:
        return args.func(args) or EXIT_OK
    except CLIError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_ERROR
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return EXIT_INTERRUPTED
    except Exception as e:
        if getattr(args, "verbose", False):
            raise
        print(f"error: {e} (use -v for details)", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
