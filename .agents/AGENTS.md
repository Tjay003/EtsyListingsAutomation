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
- **`docs/listing_production_studio_storage_plan.md`**: Future deployment/storage plan for treating this as a listing production studio using Railway plus Supabase.

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

## Debugging the Extension & Scraper Logic
AliExpress description data loads dynamically. The Chrome Extension intercepts API requests in the background Service Worker and scans the DOM silently:
1. Open Chrome at `chrome://extensions/`.
2. Toggle on **Developer Mode**.
3. Under the **Etsy Listings Automation** card, click **Inspect views: service worker** to view the `[Background-Debug]` console logs.
4. The background script decouples `fourier` trackers and strictly filters out review endpoints. It intercepts the pure description HTML and applies a broad Regex to capture image assets. This regex supports standard `/kf/` paths as well as alternative `/img/ibank/` paths (commonly used for items dropshipped from 1688), matching across `alicdn.com` and `aliexpress-media.com`.
5. The content script (`content.js`) provides a `[Content-Debug]` log for every image found in the DOM. It also silently extracts hidden item specifications using `.textContent` rather than triggering click events, preventing the page from suddenly jumping/teleporting when running the scraper.

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

---

## Deployment & Friend Testing Direction
- Prefer **local-first installs** for friends and heavy image generation. The dashboard state is file-backed, so downloaded/generated images and `metadata.json` should live on each user's computer instead of filling hosted storage.
- Keep `OUTPUT_DIR` outside the repo for friend installs, usually `C:\Users\<Name>\Downloads\AliExpressQueue`, so code updates do not risk product assets.
- Helper scripts in the repo root support the local workflow:
  - `setup.bat`: first-time virtualenv/dependency setup.
  - `start.bat`: starts the local FastAPI dashboard at `http://localhost:8000`.
  - `update.bat`: runs `git pull` and refreshes dependencies.
- Railway hosted mode exists for demos/shared staging, using token-isolated workspaces, but it stores images on the server volume. Treat User Tokens as workspace keys, not real authentication.
