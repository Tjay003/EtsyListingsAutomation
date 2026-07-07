# Etsy Listings Automation - Project Instructions

These rules and guidelines apply specifically to this project repository.

## Project Overview
This project is an automated Etsy listing tool. It allows users to scrape product details (titles, prices, specs, and image assets) from AliExpress using a Chrome Extension and send them to a local FastAPI server. The server manages a queue of products, generates SEO-optimized copywriting (titles, descriptions, tags) using Gemini AI, and generates image prompts or background-staged product photos based on preconfigured visual themes.

---

## Repository Layout
- **`extension/`**: Chrome Extension files (Manifest V3). Contains Service Worker (`background.js`) for description interception, content parser (`content.js`), and popup UI (`popup.js`).
- **`src/`**: Backend FastAPI server (`server.py`) and processing engines (`ai_helper.py`, `image_gen.py`).
- **`themes.yaml`**: Preconfigured styling presets (e.g. `bauhaus_beige`, `cottagecore_rustic`) for image generation.
- **`test_all.py`**: Local unit testing suite containing logical checks.
- **`outputs/`** (Default): Stores scraped product directories, metadata, downloaded images, and generated assets.

---

## Processing Pipeline Phases
When executing `/api/run-pipeline`, the backend processes a queued product through the following stages:
1. **Phase 1: Smart Visual Extraction**: Scans description, main, and variation images visually to extract hard facts, specifications, and dimensions.
2. **Phase 1b: Variation-Specific Specs Detection**: Scans variation images and titles to map specific sizes (e.g., S, M, L) and dimensions to each variation option, using overall size charts as context.
3. **Phase 2 & 3: Enriched Copywriting & Self-Critique**: Generates SEO-optimized titles, descriptions, and tags. Gemini acts as a strict critic to check tags (max 13, <= 20 chars) and check description facts against extracted specifications before refining the final output.
4. **Phase 4: Image Prompt Rolling**: Generates text-to-image prompts tailored for Midjourney/FLUX based on preconfigured visual themes.

---

## Metadata Schema (`metadata.json`)
The product folder under `outputs/` maintains state in a `metadata.json` file. Notable keys include:
- `main_images`: String array of local main photo paths.
- `variation_images`: Array of objects containing:
  - `url`: Original remote URL.
  - `local_path`: Local path inside the folder.
  - `alt` / `title`: Variation label from page DOM.
  - `detected_specs`: `{ name, size, dimensions, other_details }` extracted by Gemini during Phase 1b.
- `variation_specs`: Flattened list of detected variation specs.
- `etsy_listing`: Final approved copywriting: `{ title, description, tags, suggested_price }`.

---

## Debugging the Extension Background Script
AliExpress description data loads dynamically. The Chrome Extension intercepts API requests in the background Service Worker:
1. Open Chrome at `chrome://extensions/`.
2. Toggle on **Developer Mode**.
3. Under the **Etsy Listings Automation** card, click **Inspect views: service worker** to view the console logs.
4. The background script prints verbose logs for raw URL interception, decoupling of Fourier trackers, domain filtering, and Regex image parses (supporting both `alicdn.com` and `aliexpress-media.com` domains).

---

## Quick Start
- Run backend server:
  ```powershell
  .\.venv\Scripts\python -m uvicorn src.server:app --reload
  ```
- Run unit tests:
  ```powershell
  .\.venv\Scripts\python -m unittest test_all.py
  ```
