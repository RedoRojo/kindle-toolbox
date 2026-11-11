# Kindle Toolbox 📖

Local toolkit for transforming web articles and PDF documents into **reflowable EPUB3** e-books tailored for E-Ink displays and Kindle e-readers, from the **browser** or the **command line**.

## ✨ Key Features

- **Web to EPUB (Single Article)**:
  - Extracts clean content from articles and essays while stripping ads, navigation menus, and visual clutter.
  - Downloads, optimizes, and embeds article images as local assets inside the EPUB package.
- **Smart PDF to EPUB Conversion**:
  - Reconstructs clean flowing text from complex PDF documents (including multi-column layouts).
  - Automatic de-hyphenation of line-broken words and sanitization of encoding artifacts.
  - Automatic chapter structure detection, removal of repetitive headers/footers, and hyperlinked footnotes.
- **E-Ink Editorial Finish**:
  - Automatic high-resolution cover generation featuring title and author.
  - E-Ink optimized typographic stylesheets (`book` indented or `article` block-spaced) and dual navigation (`NCX` and `EPUB3 Nav`).

## 🌐 Web Interface

```bash
./run.sh
```

By default, the web server starts at **[http://127.0.0.1:8004](http://127.0.0.1:8004)** (or launch it directly from **Tools Hub**).

## ⌨️ Command Line Interface

Via the global Tools Hub dispatcher (recommended):

```bash
tools kindle web "https://example.com/article" [--title "..."] [--author "..."] [-o article.epub]
tools kindle pdf book.pdf [--columns auto|1|2] [--style book|article] [--no-cover] [-o book.epub]
tools kindle pdf-info book.pdf [--json]
```

Or standalone from this repository: `./cli.sh <command> ...`.

| Subcommand | Key Options | Description |
| :--- | :--- | :--- |
| `web` | `--title`, `--author`, `--style book\|article`, `--no-cover`, `--no-images`, `-o` | Convert a web article URL into a reflowable EPUB3 |
| `pdf` | `--columns auto\|1\|2`, `--title`, `--author`, `--style book\|article`, `--no-cover`, `-o` | Convert a PDF book into a multi-chapter EPUB3 |
| `pdf-info` | `--columns auto\|1\|2`, `--json` | Inspect detected chapters, layout, and footnotes without converting |

All subcommands write output files to the **current working directory** by default (without overwriting existing files) and support `--json`, `-q/--quiet`, and `-v/--verbose`.

## 🧪 Running Tests

```bash
~/miniconda3/envs/pdf-toolkit/bin/python -m unittest discover -s tests -v
```
