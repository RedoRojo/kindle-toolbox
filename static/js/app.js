/**
 * Kindle Toolbox - Frontend interactivo
 * Soporte dual: Artículos Web a EPUB y Conversión Versátil de PDF a EPUB
 */

// Estado Web
let currentExtractId = null;
let currentSourceUrl = "";
let currentHtmlBody = "";

// Estado PDF
let currentPdfId = null;

function formatBytes(bytes) {
  if (bytes === 0) return "0 Bytes";
  const k = 1024;
  const sizes = ["Bytes", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + " " + sizes[i];
}

// Control de pestañas
function switchTab(tabId) {
  const btnWeb = document.getElementById("tabBtnWeb");
  const btnPdf = document.getElementById("tabBtnPdf");
  const panelWeb = document.getElementById("panelWeb");
  const panelPdf = document.getElementById("panelPdf");

  if (tabId === "pdf") {
    btnWeb.classList.remove("active");
    btnPdf.classList.add("active");
    panelWeb.classList.remove("active");
    panelPdf.classList.add("active");
    fetchLocalPdfs();
  } else {
    btnPdf.classList.remove("active");
    btnWeb.classList.add("active");
    panelPdf.classList.remove("active");
    panelWeb.classList.add("active");
  }
}

function showWebStatus(message, isError = false) {
  const box = document.getElementById("statusMessage");
  if (!message) {
    box.classList.add("hidden");
    box.textContent = "";
    return;
  }
  box.textContent = message;
  box.className = "status-box " + (isError ? "error" : "");
  box.classList.remove("hidden");
}

function showPdfStatus(message, isError = false) {
  const box = document.getElementById("pdfStatusMessage");
  if (!message) {
    box.classList.add("hidden");
    box.textContent = "";
    return;
  }
  box.textContent = message;
  box.className = "status-box " + (isError ? "error" : "");
  box.classList.remove("hidden");
}

// ==========================================
// SECCIÓN 1: ARTÍCULO WEB A EPUB
// ==========================================

async function handleExtract(event) {
  event.preventDefault();
  showWebStatus("");

  const urlInput = document.getElementById("articleUrl");
  const includeImages = document.getElementById("includeImages").checked;
  const btnExtract = document.getElementById("btnExtract");
  const spinner = document.getElementById("extractSpinner");
  const btnText = btnExtract.querySelector(".btn-text");

  const url = urlInput.value.trim();
  if (!url) return;

  btnExtract.disabled = true;
  spinner.classList.remove("hidden");
  btnText.textContent = "Extrayendo...";

  const previewCard = document.getElementById("previewCard");
  const downloadResult = document.getElementById("downloadResult");
  downloadResult.classList.add("hidden");

  try {
    const res = await fetch("/api/extract", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url: url,
        include_images: includeImages
      })
    });

    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.detail || "Error al extraer el artículo");
    }

    currentExtractId = data.extract_id;
    currentSourceUrl = data.url;
    currentHtmlBody = data.html_body;

    document.getElementById("metaTitle").value = data.title || "";
    document.getElementById("metaAuthor").value = data.author || "";
    document.getElementById("metaDate").value = data.date || "";
    document.getElementById("metaSitename").value = data.sitename || "";

    const count = data.images_count || 0;
    document.getElementById("imagesBadge").textContent = `${count} ${count === 1 ? "imagen" : "imágenes"}`;
    document.getElementById("einkContent").innerHTML = data.html_body || "<p>Sin contenido.</p>";

    previewCard.classList.remove("hidden");
    previewCard.scrollIntoView({ behavior: "smooth", block: "start" });

  } catch (err) {
    showWebStatus(err.message || "Error al conectar con el servidor", true);
  } finally {
    btnExtract.disabled = false;
    spinner.classList.add("hidden");
    btnText.textContent = "Extraer Artículo";
  }
}

async function handleGenerate() {
  const btnGenerate = document.getElementById("btnGenerate");
  const spinner = document.getElementById("generateSpinner");
  const btnText = btnGenerate.querySelector(".btn-text");

  const title = document.getElementById("metaTitle").value.trim();
  const author = document.getElementById("metaAuthor").value.trim();
  const date = document.getElementById("metaDate").value.trim();
  const sitename = document.getElementById("metaSitename").value.trim();
  const paragraphStyle = document.querySelector('input[name="paragraphStyle"]:checked').value;
  const generateCover = document.getElementById("generateCover").checked;

  if (!title) {
    alert("Por favor indica un título para el libro.");
    return;
  }

  btnGenerate.disabled = true;
  spinner.classList.remove("hidden");
  btnText.textContent = "Generando EPUB...";

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
      generate_cover: generateCover
    };

    const res = await fetch("/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.detail || "Error al compilar el libro electrónico");
    }

    document.getElementById("downloadFileName").textContent = data.filename;
    document.getElementById("downloadFileSize").textContent = formatBytes(data.filesize);
    
    const link = document.getElementById("downloadBtnLink");
    link.href = data.download_url;

    downloadResult.classList.remove("hidden");

    // Auto descarga
    const autoLink = document.createElement("a");
    autoLink.href = data.download_url;
    autoLink.download = data.filename;
    document.body.appendChild(autoLink);
    autoLink.click();
    document.body.removeChild(autoLink);

    downloadResult.scrollIntoView({ behavior: "smooth", block: "nearest" });

  } catch (err) {
    alert("Error: " + (err.message || "No se pudo generar el EPUB"));
  } finally {
    btnGenerate.disabled = false;
    spinner.classList.add("hidden");
    btnText.textContent = "Generar y Descargar EPUB";
  }
}

// ==========================================
// SECCIÓN 2: PDF A EPUB VERSÁTIL
// ==========================================

async function fetchLocalPdfs() {
  const select = document.getElementById("localPdfSelect");
  try {
    const res = await fetch("/api/pdf/local-files");
    if (!res.ok) return;
    const data = await res.json();
    
    // Guardar selección previa si existe
    const currentVal = select.value;
    select.innerHTML = '<option value="">-- Seleccionar archivo local --</option>';

    data.files.forEach(f => {
      const opt = document.createElement("option");
      opt.value = f.path;
      opt.textContent = `${f.name} (${formatBytes(f.size)})`;
      select.appendChild(opt);
    });

    // Restaurar o preseleccionar el primer archivo interesante
    if (currentVal) {
      select.value = currentVal;
    } else if (data.files.length > 0) {
      // Auto-seleccionar Anti-Dühring o el primero
      const defaultPdf = data.files.find(f => f.name.includes("Anti-Dühring")) || data.files[0];
      if (defaultPdf) {
        select.value = defaultPdf.path;
      }
    }
  } catch (err) {
    console.warn("No se pudieron cargar PDFs locales:", err);
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
  showPdfStatus("");

  const localSelect = document.getElementById("localPdfSelect");
  const fileInput = document.getElementById("pdfFileInput");
  const colMode = document.getElementById("pdfColMode").value;

  const localPath = localSelect.value;
  const uploadedFile = fileInput.files[0];

  if (!localPath && !uploadedFile) {
    showPdfStatus("Por favor selecciona un archivo PDF local o sube uno.", true);
    return;
  }

  const btnAnalyze = document.getElementById("btnAnalyzePdf");
  const spinner = document.getElementById("analyzePdfSpinner");
  const btnText = btnAnalyze.querySelector(".btn-text");

  btnAnalyze.disabled = true;
  spinner.classList.remove("hidden");
  btnText.textContent = "Analizando PDF y Columnas...";

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
      body: formData
    });

    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.detail || "Error al analizar el PDF");
    }

    currentPdfId = data.pdf_id;

    // Actualizar badges
    document.getElementById("pdfPagesBadge").textContent = `${data.total_pages} páginas`;
    document.getElementById("pdfColsBadge").textContent = data.detected_col_mode;
    document.getElementById("pdfChaptersBadge").textContent = `${data.chapters_count} capítulos`;
    document.getElementById("pdfFootnotesBadge").textContent = `${data.total_footnotes} notas vinculadas`;

    // Metadatos
    document.getElementById("pdfMetaTitle").value = data.title || "";
    document.getElementById("pdfMetaAuthor").value = data.author || "";

    // Lista de capítulos
    const listContainer = document.getElementById("chaptersList");
    listContainer.innerHTML = "";

    data.chapters.forEach((chap, idx) => {
      const item = document.createElement("div");
      item.className = "chapter-item";
      item.innerHTML = `
        <div class="chapter-item-top">
          <span class="chapter-item-title">${idx + 1}. ${chap.title}</span>
          <span class="chapter-item-meta">${chap.footnotes_count} nota${chap.footnotes_count === 1 ? '' : 's'}</span>
        </div>
        <div class="chapter-item-preview">${chap.preview}</div>
      `;
      listContainer.appendChild(item);
    });

    previewCard.classList.remove("hidden");
    previewCard.scrollIntoView({ behavior: "smooth", block: "start" });

  } catch (err) {
    showPdfStatus(err.message || "Error al procesar el archivo PDF", true);
  } finally {
    btnAnalyze.disabled = false;
    spinner.classList.add("hidden");
    btnText.textContent = "Analizar y Previsualizar PDF";
  }
}

async function handleConvertPdf() {
  if (!currentPdfId) {
    alert("Por favor analiza primero un documento PDF.");
    return;
  }

  const btnGenerate = document.getElementById("btnGeneratePdf");
  const spinner = document.getElementById("generatePdfSpinner");
  const btnText = btnGenerate.querySelector(".btn-text");

  const title = document.getElementById("pdfMetaTitle").value.trim();
  const author = document.getElementById("pdfMetaAuthor").value.trim();
  const paragraphStyle = document.querySelector('input[name="pdfParagraphStyle"]:checked').value;
  const generateCover = document.getElementById("pdfGenerateCover").checked;

  if (!title) {
    alert("Por favor indica un título para el libro.");
    return;
  }

  btnGenerate.disabled = true;
  spinner.classList.remove("hidden");
  btnText.textContent = "Compilando EPUB multi-capítulo...";

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
        generate_cover: generateCover
      })
    });

    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.detail || "Error al compilar el EPUB");
    }

    document.getElementById("pdfDownloadFileName").textContent = data.filename;
    document.getElementById("pdfDownloadFileSize").textContent = formatBytes(data.filesize);

    const link = document.getElementById("pdfDownloadBtnLink");
    link.href = data.download_url;

    downloadResult.classList.remove("hidden");

    // Auto descarga
    const autoLink = document.createElement("a");
    autoLink.href = data.download_url;
    autoLink.download = data.filename;
    document.body.appendChild(autoLink);
    autoLink.click();
    document.body.removeChild(autoLink);

    downloadResult.scrollIntoView({ behavior: "smooth", block: "nearest" });

  } catch (err) {
    alert("Error: " + (err.message || "No se pudo generar el EPUB"));
  } finally {
    btnGenerate.disabled = false;
    spinner.classList.add("hidden");
    btnText.textContent = "Compilar y Descargar EPUB Completo";
  }
}

// Cargar lista inicial si está en tab PDF al cargar
document.addEventListener("DOMContentLoaded", () => {
  fetchLocalPdfs();
});
