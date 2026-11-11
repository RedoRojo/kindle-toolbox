# Kindle Toolbox 📖

Conversor local de artículos web y documentos PDF a libros electrónicos **EPUB3 reflowable**, diseñado específicamente para una lectura cómoda en pantallas de tinta electrónica (E-Ink) y lectores Kindle.

## ✨ Características Principales

- **Web a EPUB (Artículo Individual o Libro Multicapítulo)**:
  - Extrae el contenido limpio de artículos, ensayos o múltiples enlaces web eliminando anuncios, menús y elementos distractores.
  - Descarga, optimiza e incrusta las imágenes del artículo como activos locales dentro del paquete EPUB.
- **PDF a EPUB Inteligente**:
  - Reconstruye el flujo de texto desde documentos PDF complejos (incluyendo maquetación en múltiples columnas).
  - Desguionado automático de palabras cortadas al final de línea y saneamiento de artefactos de codificación.
  - Detección automática de estructura de capítulos y limpieza de encabezados/pies de página repetitivos.
  - Extracción y vinculación de notas al pie.
- **Acabado Editorial E-Ink**:
  - Generación automática de portada de alta resolución con título y autor.
  - Hojas de estilo tipográficas optimizadas para tinta electrónica y navegación dual (`NCX` y `EPUB3 Nav`).

## 🚀 Ejecución Rápida

```bash
./run.sh
```

Por defecto, el servidor web se iniciará en **[http://127.0.0.1:8004](http://127.0.0.1:8004)** (o puedes abrirlo directamente desde **Tools Hub**).

## 📦 Instalación de Dependencias

Si utilizas un entorno virtual estándar o Conda:

```bash
pip install -r requirements.txt
```
