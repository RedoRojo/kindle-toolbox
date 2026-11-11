# Kindle Toolbox 📖

Local web converter for transforming web articles and PDF documents into **reflowable EPUB3** e-books, specifically tailored for comfortable reading on E-Ink displays and Kindle e-readers.

## ✨ Key Features

- **Web to EPUB (Single Article or Multi-Chapter Book)**:
  - Extracts clean content from articles, essays, or multiple web links while stripping ads, navigation menus, and visual clutter.
  - Downloads, optimizes, and embeds article images as local assets inside the EPUB package.
- **Smart PDF to EPUB Conversion**:
  - Reconstructs clean flowing text from complex PDF documents (including multi-column layouts).
  - Automatic de-hyphenation of line-broken words and sanitization of encoding artifacts.
  - Automatic chapter structure detection and removal of repetitive headers and footers.
  - Extraction and hyperlinking of footnotes.
- **E-Ink Editorial Finish**:
  - Automatic high-resolution cover generation featuring title and author.
  - E-Ink optimized typographic stylesheets and dual navigation (`NCX` and `EPUB3 Nav`).

## 🚀 Quick Start

```bash
./run.sh
```

By default, the web server starts at **[http://127.0.0.1:8004](http://127.0.0.1:8004)** (or can be launched directly from **Tools Hub**).

## 📦 Installing Dependencies

Using a standard virtual environment or Conda:

```bash
pip install -r requirements.txt
```
