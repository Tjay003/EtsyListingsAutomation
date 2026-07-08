---
name: etsy-pipeline
description: Use this skill when implementing features, reviewing the architecture, debugging errors, running E2E tests, or writing components for the Etsy listings automation tool (extension, scraper, server, or AI image/text generation).
---

# Etsy Listings Automation - Core Architecture & Workflows

This skill contains detailed component mechanics, testing procedures, and engineering historical context.

## How Core Components Work
1. **Chrome Extension (Scraping & Interception)**:
   - AliExpress loads description images dynamically via a late network call when scrolling.
   - To bypass this, `background.js` listens to `chrome.webRequest.onCompleted` to catch the real description HTML URL.
   - It decodes the URL (bypassing the `fourier.aliexpress.com` tracker), fetches the HTML, and caches description image URLs in `chrome.storage.session` (session storage persists service worker restarts in MV3).
   - `content.js` and `popup.js` aggregate main carousel, variation, and description images.
2. **FastAPI Backend (Queue & Processing)**:
   - Receives JSON payload at `/api/queue-product`, creates a directory in the output path, and downloads all selected assets in a background task.
   - Stores metadata in a `metadata.json` file inside the product directory.
   - Runs copywriting generation and theme prompt rolling via Gemini upon hitting `/api/run-pipeline`.

---

## End-to-End (E2E) Testing Flow
1. **Start the Backend Server**:
   ```powershell
   .\.venv\Scripts\python -m uvicorn src.server:app --reload
   ```
2. **Load Chrome Extension**:
   - Open Chrome at `chrome://extensions/`
   - Enable **Developer Mode** (top right toggle).
   - Click **Load unpacked** and select the `extension` folder in this repo.
3. **Queue a Product**:
   - Go to any product page on `aliexpress.com` or `aliexpress.us`.
   - Open the extension popup, verify correct image counts, select checkboxes, and click **Queue Product**.
4. **Process in Dashboard**:
   - Open [http://localhost:8000](http://localhost:8000) in Chrome.
   - Check if the item appears in the **Queue** tab.
   - Click **Run Pipeline** and choose a theme (e.g., `bauhaus_beige`) to verify copywriting and prompt generation.
5. **Verify Outputs**:
   - Check if the product folder under `outputs/` is updated with `metadata.json` containing the copywriting and prompts.

---

## Lessons Learned & Key Fixes
* **Session Storage over Cache memory**: In Manifest V3, service workers restart frequently. Always use `chrome.storage.session` for caching intercepted data to prevent losing description images.
* **Fourier Tracker Bypass**: Decoded target URLs from `fourier.aliexpress.com/ts?url=...` to fetch raw HTML blocks directly instead of forcing UI scrolls or clicks.
* **No `inputs` Folder Needed**: The `inputs` folder was a leftover from CLI testing. The current system relies strictly on the dashboard/extension flow. All scraped data and assets reside in `outputs` (configurable via `OUTPUT_DIR` in `.env`).
