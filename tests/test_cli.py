"""
CLI and core tests for Kindle Toolbox.
Run with:
    ~/miniconda3/envs/pdf-toolkit/bin/python -m unittest discover -s tests -v
"""

import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import pymupdf

BASE_DIR = Path(__file__).resolve().parent.parent
CLI = BASE_DIR / "cli.py"
sys.path.insert(0, str(BASE_DIR))


def run_cli(*args, cwd=None):
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        capture_output=True,
        text=True,
        cwd=cwd,
        timeout=120,
    )


def make_book_pdf(path: Path) -> Path:
    doc = pymupdf.open()
    p1 = doc.new_page(width=595, height=842)
    p1.insert_text((72, 120), "Chapter 1: Introduction", fontsize=18)
    p1.insert_text((72, 160), "This is the first paragraph of the introduction chapter for testing EPUB generation.", fontsize=11)
    p2 = doc.new_page(width=595, height=842)
    p2.insert_text((72, 120), "Chapter 2: Conclusion", fontsize=18)
    p2.insert_text((72, 160), "This is the second chapter body with clean flowing text for E-Ink devices.", fontsize=11)
    doc.set_metadata({"title": "Test Book", "author": "Ada Lovelace"})
    doc.save(str(path))
    doc.close()
    return path


class KindleToolboxCLITests(unittest.TestCase):
    def test_help_for_all_subcommands(self):
        for sub in ([], ["web"], ["pdf"], ["pdf-info"]):
            res = run_cli(*sub, "--help")
            self.assertEqual(res.returncode, 0, res.stderr)
            self.assertIn("usage:", res.stdout)

    def test_no_command_exits_with_usage_code(self):
        self.assertEqual(run_cli().returncode, 2)

    def test_pdf_info_and_pdf_to_epub_in_cwd(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp).resolve()
            pdf = make_book_pdf(tmp_path / "sample.pdf")

            # pdf-info --json
            r_info = run_cli("pdf-info", str(pdf), "--json", cwd=tmp)
            self.assertEqual(r_info.returncode, 0, r_info.stderr)
            info = json.loads(r_info.stdout)
            self.assertEqual(info["total_pages"], 2)
            self.assertGreaterEqual(info["chapters_count"], 1)

            # pdf conversion -> writes valid EPUB zip in cwd
            r_conv = run_cli("pdf", str(pdf), "--title", "Custom Book", "--author", "Ada", "--json", cwd=tmp)
            self.assertEqual(r_conv.returncode, 0, r_conv.stderr)
            payload = json.loads(r_conv.stdout)
            epub_path = Path(payload["filepath"])
            self.assertEqual(epub_path.parent, tmp_path)
            self.assertTrue(epub_path.is_file())
            with zipfile.ZipFile(epub_path, "r") as zf:
                self.assertIn("mimetype", zf.namelist())

            # second run does not overwrite existing EPUB
            r_conv2 = run_cli("pdf", str(pdf), "--title", "Custom Book", "--author", "Ada", cwd=tmp)
            self.assertEqual(r_conv2.returncode, 0, r_conv2.stderr)
            epub_path2 = Path(r_conv2.stdout.strip())
            self.assertNotEqual(epub_path, epub_path2)
            self.assertTrue(epub_path2.is_file())

    def test_web_subcommand_with_mocked_scraper(self):
        import cli

        fake_article = {
            "title": "Mocked Essay",
            "author": "Test Writer",
            "date": "2026-11-11",
            "sitename": "Example",
            "url": "https://example.com/essay",
            "language": "en",
            "html_body": "<p>First paragraph of the mocked essay.</p>",
            "images": [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "essay.epub"
            with patch("core.scraper.extract_clean_article", return_value=fake_article):
                rc = cli.main(["web", "https://example.com/essay", "-o", str(out_file), "-q"])
            self.assertEqual(rc, 0)
            self.assertTrue(out_file.is_file())


if __name__ == "__main__":
    unittest.main()
