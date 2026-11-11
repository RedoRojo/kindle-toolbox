/**
 * Kindle Toolbox - Interactive Frontend
 * Supports Web Article to EPUB and Versatile PDF to EPUB conversion.
 */

// Web extraction state
let currentExtractId = null;
let currentSourceUrl = "";
let currentHtmlBody = "";

// PDF analysis state
let currentPdfId = null;

const SAFE_HTML_TAGS = new Set([
  "article", "section", "div", "p", "br", "hr",
  "h1", "h2", "h3", "h4", "h5", "h6",
  "blockquote", "pre", "code", "sup", "sub", "span",
  "b", "strong", "i", "em", "u", "s",
  "ul", "ol", "li",
  "a", "img", "figure", "figcaption",
  "table", "thead", "tbody", "tr", "th", "td",
]);

const SAFE_HTML_ATTRS = new Set(["class", "href", "src", "alt", "title"]);

function isSafeUrlValue(attrName, value) {
  const trimmed = (value || "").trim();
  if (!trimmed) return false;
  if (attrName === "href") {
    if (trimmed.startsWith("#")) return true;
    return /^(https?:|mailto:)/i.test(trimmed);
  }
  if (attrName === "src") {
    return /^(images\/|https?:|data:image\/(?:png|jpeg|jpg|gif);base64,)/i.test(trimmed);
  }
  return true;
}

function sanitizeNodeTree(sourceRoot, doc) {
  const fragment = doc.createDocumentFragment();

  function cloneSafe(node) {
    if (node.nodeType === Node.TEXT_NODE) {
      return doc.createTextNode(node.nodeValue || "");
    }
    if (node.nodeType !== Node.ELEMENT_NODE) {
      return null;
    }

    const tag = node.tagName.toLowerCase();
    if (!SAFE_HTML_TAGS.has(tag)) {
      // Unwrap harmless container elements or drop executable ones completely
      if (["script", "style", "iframe", "object", "embed", "noscript", "svg"].includes(tag)) {
        return null;
      }
      const fallbackFrag = doc.createDocumentFragment();
      for (const child of node.childNodes) {
        const cleanChild = cloneSafe(child);
        if (cleanChild) fallbackFrag.appendChild(cleanChild);
      }
      return fallbackFrag;
    }

    const cleanEl = doc.createElement(tag);
    for (const attr of node.attributes) {
      const name = attr.name.toLowerCase();
      if (SAFE_HTML_ATTRS.has(name) && isSafeUrlValue(name, attr.value)) {
        cleanEl.setAttribute(name, attr.value);
      }
    }
    if (tag === "a") {
      cleanEl.setAttribute("rel", "noopener noreferrer");
      cleanEl.setAttribute("target", "_blank");
    }
    for (const child of node.childNodes) {
      const cleanChild = cloneSafe(child);
      if (cleanChild) cleanEl.appendChild(cleanChild);
    }
    return cleanEl;
  }

  for (const child of sourceRoot.childNodes) {
    const cleanChild = cloneSafe(child);
    if (cleanChild) fragment.appendChild(cleanChild);
  }
  return fragment;
}

function safeRenderHtmlPreview(container, rawHtml) {
  const html = rawHtml || "<p>No content available.</p>";
  if ("setHTML" in Element.prototype) {
    container.setHTML(html, {
      sanitizer: {
        elements: Array.from(SAFE_HTML_TAGS),
        attributes: Array.from(SAFE_HTML_ATTRS),
      },
    });
    return;
  }
  const parsed = new DOMParser().parseFromString(html, "text/html");
  const cleanFragment = sanitizeNodeTree(parsed.body, document);
  container.replaceChildren(cleanFragment);
}

function formatBytes(bytes) {
  if (bytes === 0) return "0 Bytes";
  const k = 1024;
  const sizes = ["Bytes", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + " " + sizes[i];
}

function setStatusBox(elementId, message, isError = false) {
  const box = document.getElementById(elementId);
  if (!box) return;
  if (!message) {
    box.classList.add("hidden");
    box.textContent = "";
    return;
  }
  box.textContent = message;
  box.className = "status-box " + (isError ? "error" : "");
  box.classList.remove("hidden");
}

// Accessible tab switching
function switchTab(tabId) {
  const btnWeb = document.getElementById("tabBtnWeb");
  const btnPdf = document.getElementById("tabBtnPdf");
  const panelWeb = document.getElementById("panelWeb");
  const panelPdf = document.getElementById("panelPdf");

  if (tabId === "pdf") {
    btnWeb.classList.remove("active");
    btnWeb.setAttribute("aria-selected", "false");
    btnPdf.classList.add("active");
    btnPdf.setAttribute("aria-selected", "true");

    panelWeb.classList.remove("active");
    panelWeb.hidden = true;
    panelPdf.classList.add("active");
    panelPdf.hidden = false;

    fetchLocalPdfs();
  } else {
    btnPdf.classList.remove("active");
    btnPdf.setAttribute("aria-selected", "false");
    btnWeb.classList.add("active");
    btnWeb.setAttribute("aria-selected", "true");

    panelPdf.classList.remove("active");
    panelPdf.hidden = true;
    panelWeb.classList.add("active");
    panelWeb.hidden = false;
  }
}

// ==========================================
// SECTION 1: WEB ARTICLE TO EPUB
// ==========================================

async function handleExtract(event) {
  event.preventDefault();
  setStatusBox("statusMessage", "");
  setStatusBox("webGenerateStatusMessage", "");

  const urlInput = document.getElementById("articleUrl");
  const includeImages = document.getElementById("includeImages").checked;
  const btnExtract = document.getElementById("btnExtract");
  const spinner = document.getElementById("extractSpinner");
  const btnText = btnExtract.querySelector(".btn-text");

  const url = urlInput.value.trim();
  if (!url) return;

  btnExtract.disabled = true;
  spinner.classList.remove("hidden");
  btnText.textContent = "Extracting...";

  const previewCard = document.getElementById("previewCard");
  const downloadResult = document.getElementById("downloadResult");
  downloadResult.classList.add("hidden");

  try {
    const res = await fetch("/api/extract", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url: url,
        include_images: includeImages,
      }),
    });

    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.detail || "Failed to extract article");
    }

    currentExtractId = data.extract_id;
    currentSourceUrl = data.url;
    currentHtmlBody = data.html_body;

    document.getElementById("metaTitle").value = data.title || "";
    document.getElementById("metaAuthor").value = data.author || "";
    document.getElementById("metaDate").value = data.date || "";
    document.getElementById("metaSitename").value = data.sitename || "";

    const count = data.images_count || 0;
    document.getElementById("imagesBadge").textContent = `${count} ${count === 1 ? "image" : "images"}`;
    safeRenderHtmlPreview(document.getElementById("einkContent"), data.html_body);

    previewCard.classList.remove("hidden");
    previewCard.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (err) {
    setStatusBox("statusMessage", err.message || "Unable to connect to the server", true);
  } finally {
    btnExtract.disabled = false;
    spinner.classList.add("hidden");
    btnText.textContent = "Extract Article";
  }
}

async function handleGenerate() {
  setStatusBox("webGenerateStatusMessage", "");
  const btnGenerate = document.getElementById("btnGenerate");
  const spinner = document.getElementById("generateSpinner");
  const btnText = btnGenerate.querySelector(".btn-text");

  const titleInput = document.getElementById("metaTitle");
  const title = titleInput.value.trim();
  const author = document.getElementById("metaAuthor").value.trim();
  const date = document.getElementById("metaDate").value.trim();
  const sitename = document.getElementById("metaSitename").value.trim();
  const paragraphStyle = document.querySelector('input[name="paragraphStyle"]:checked').value;
  const generateCover = document.getElementById("generateCover").checked;

  if (!title) {
    setStatusBox("webGenerateStatusMessage", "Please provide a title for the book.", true);
    titleInput.focus();
    return;
  }

  btnGenerate.disabled = true;
  spinner.classList.remove("hidden");
  btnText.textContent = "Generating EPUB...";

  const downloadResult = document.getElementById("downloadResult");
  downloadResult.classList.add("hidden");

  try {
    const payload = {
      extract_id: currentExtractId,
      url: currentSourceUrl,
      title: title,
      author: author,
      date: date,
      sitename: sitename,
      html_body: currentHtmlBody,
      paragraph_style: paragraphStyle,
      generate_cover: generateCover,
    };

    const res = await fetch("/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.detail || "Failed to compile e-book");
    }

    document.getElementById("downloadFileName").textContent = data.filename;
    document.getElementById("downloadFileSize").textContent = formatBytes(data.filesize);

    const link = document.getElementById("downloadBtnLink");
    link.href = data.download_url;

    downloadResult.classList.remove("hidden");

    const autoLink = document.createElement("a");
    autoLink.href = data.download_url;
    autoLink.download = data.filename;
    document.body.appendChild(autoLink);
    autoLink.click();
    document.body.removeChild(autoLink);

    downloadResult.scrollIntoView({ behavior: "smooth", block: "nearest" });
  } catch (err) {
    setStatusBox("webGenerateStatusMessage", err.message || "Could not generate the EPUB file.", true);
  } finally {
    btnGenerate.disabled = false;
    spinner.classList.add("hidden");
    btnText.textContent = "Generate & Download EPUB";
  }
}

// ==========================================
// SECTION 2: PDF TO EPUB
// ==========================================

async function fetchLocalPdfs() {
  const select = document.getElementById("localPdfSelect");
  try {
    const res = await fetch("/api/pdf/local-files");
    if (!res.ok) return;
    const data = await res.json();

    const currentVal = select.value;
    select.innerHTML = '<option value="">-- Select a local file --</option>';

    data.files.forEach((f) => {
      const opt = document.createElement("option");
      opt.value = f.path;
      opt.textContent = `${f.name} (${formatBytes(f.size)})`;
      select.appendChild(opt);
    });

    if (currentVal && data.files.some((f) => f.path === currentVal)) {
      select.value = currentVal;
    } else if (data.files.length > 0 && !document.getElementById("pdfFileInput").files.length) {
      select.value = data.files[0].path;
    }
  } catch (err) {
    console.warn("Unable to load local PDF files:", err);
  }
}

function onLocalPdfChange() {
  const select = document.getElementById("localPdfSelect");
  if (select.value) {
    document.getElementById("pdfFileInput").value = "";
  }
}

function onPdfFileSelected() {
  const fileInput = document.getElementById("pdfFileInput");
  if (fileInput.files.length > 0) {
    document.getElementById("localPdfSelect").value = "";
  }
}

async function handleAnalyzePdf(event) {
  event.preventDefault();
  setStatusBox("pdfStatusMessage", "");
  setStatusBox("pdfGenerateStatusMessage", "");

  const localSelect = document.getElementById("localPdfSelect");
  const fileInput = document.getElementById("pdfFileInput");
  const colMode = document.getElementById("pdfColMode").value;

  const localPath = localSelect.value;
  const uploadedFile = fileInput.files[0];

  if (!localPath && !uploadedFile) {
    setStatusBox("pdfStatusMessage", "Please select a local PDF file or upload one from your device.", true);
    localSelect.focus();
    return;
  }

  const btnAnalyze = document.getElementById("btnAnalyzePdf");
  const spinner = document.getElementById("analyzePdfSpinner");
  const btnText = btnAnalyze.querySelector(".btn-text");

  btnAnalyze.disabled = true;
  spinner.classList.remove("hidden");
  btnText.textContent = "Analyzing PDF & Columns...";

  const previewCard = document.getElementById("pdfPreviewCard");
  const downloadResult = document.getElementById("pdfDownloadResult");
  downloadResult.classList.add("hidden");

  const formData = new FormData();
  formData.append("col_mode", colMode);
  if (uploadedFile) {
    formData.append("file", uploadedFile);
  } else if (localPath) {
    formData.append("local_path", localPath);
  }

  try {
    const res = await fetch("/api/pdf/analyze", {
      method: "POST",
      body: formData,
    });

    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.detail || "Failed to analyze PDF");
    }

    currentPdfId = data.pdf_id;

    document.getElementById("pdfPagesBadge").textContent = `${data.total_pages} pages`;
    document.getElementById("pdfColsBadge").textContent = data.detected_col_mode;
    document.getElementById("pdfChaptersBadge").textContent = `${data.chapters_count} chapters`;
    document.getElementById("pdfFootnotesBadge").textContent = `${data.total_footnotes} linked footnotes`;

    document.getElementById("pdfMetaTitle").value = data.title || "";
    document.getElementById("pdfMetaAuthor").value = data.author || "";

    const listContainer = document.getElementById("chaptersList");
    listContainer.replaceChildren();

    data.chapters.forEach((chap, idx) => {
      const item = document.createElement("div");
      item.className = "chapter-item";

      const topRow = document.createElement("div");
      topRow.className = "chapter-item-top";

      const titleSpan = document.createElement("span");
      titleSpan.className = "chapter-item-title";
      titleSpan.textContent = `${idx + 1}. ${chap.title}`;

      const metaSpan = document.createElement("span");
      metaSpan.className = "chapter-item-meta";
      metaSpan.textContent = `${chap.footnotes_count} footnote${chap.footnotes_count === 1 ? "" : "s"}`;

      topRow.appendChild(titleSpan);
      topRow.appendChild(metaSpan);

      const previewDiv = document.createElement("div");
      previewDiv.className = "chapter-item-preview";
      previewDiv.textContent = chap.preview;

      item.appendChild(topRow);
      item.appendChild(previewDiv);
      listContainer.appendChild(item);
    });

    previewCard.classList.remove("hidden");
    previewCard.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (err) {
    setStatusBox("pdfStatusMessage", err.message || "Unable to process PDF file.", true);
  } finally {
    btnAnalyze.disabled = false;
    spinner.classList.add("hidden");
    btnText.textContent = "Analyze & Preview PDF";
  }
}

async function handleConvertPdf() {
  setStatusBox("pdfGenerateStatusMessage", "");
  if (!currentPdfId) {
    setStatusBox("pdfGenerateStatusMessage", "Please analyze a PDF document first.", true);
    return;
  }

  const btnGenerate = document.getElementById("btnGeneratePdf");
  const spinner = document.getElementById("generatePdfSpinner");
  const btnText = btnGenerate.querySelector(".btn-text");

  const titleInput = document.getElementById("pdfMetaTitle");
  const title = titleInput.value.trim();
  const author = document.getElementById("pdfMetaAuthor").value.trim();
  const paragraphStyle = document.querySelector('input[name="pdfParagraphStyle"]:checked').value;
  const generateCover = document.getElementById("pdfGenerateCover").checked;

  if (!title) {
    setStatusBox("pdfGenerateStatusMessage", "Please provide a title for the book.", true);
    titleInput.focus();
    return;
  }

  btnGenerate.disabled = true;
  spinner.classList.remove("hidden");
  btnText.textContent = "Compiling Multi-Chapter EPUB...";

  const downloadResult = document.getElementById("pdfDownloadResult");
  downloadResult.classList.add("hidden");

  try {
    const res = await fetch("/api/pdf/convert", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        pdf_id: currentPdfId,
        title: title,
        author: author,
        paragraph_style: paragraphStyle,
        generate_cover: generateCover,
      }),
    });

    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.detail || "Failed to compile EPUB");
    }

    document.getElementById("pdfDownloadFileName").textContent = data.filename;
    document.getElementById("pdfDownloadFileSize").textContent = formatBytes(data.filesize);

    const link = document.getElementById("pdfDownloadBtnLink");
    link.href = data.download_url;

    downloadResult.classList.remove("hidden");

    const autoLink = document.createElement("a");
    autoLink.href = data.download_url;
    autoLink.download = data.filename;
    document.body.appendChild(autoLink);
    autoLink.click();
    document.body.removeChild(autoLink);

    downloadResult.scrollIntoView({ behavior: "smooth", block: "nearest" });
  } catch (err) {
    setStatusBox("pdfGenerateStatusMessage", err.message || "Could not generate EPUB.", true);
  } finally {
    btnGenerate.disabled = false;
    spinner.classList.add("hidden");
    btnText.textContent = "Compile & Download Complete EPUB";
  }
}

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("tabBtnWeb").addEventListener("click", () => switchTab("web"));
  document.getElementById("tabBtnPdf").addEventListener("click", () => switchTab("pdf"));

  document.getElementById("extractForm").addEventListener("submit", handleExtract);
  document.getElementById("btnGenerate").addEventListener("click", handleGenerate);

  document.getElementById("pdfForm").addEventListener("submit", handleAnalyzePdf);
  document.getElementById("localPdfSelect").addEventListener("change", onLocalPdfChange);
  document.getElementById("pdfFileInput").addEventListener("change", onPdfFileSelected);
  document.getElementById("btnRefreshPdfs").addEventListener("click", fetchLocalPdfs);
  document.getElementById("btnGeneratePdf").addEventListener("click", handleConvertPdf);

  fetchLocalPdfs();
});
