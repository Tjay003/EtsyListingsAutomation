// Helper to extract productId from AliExpress product detail URLs
function getProductIdFromUrl(url) {
  if (!url) return null;
  const match = url.match(/\/item\/(\d+)\.html/i);
  return match ? match[1] : null;
}

document.addEventListener("DOMContentLoaded", async () => {
  // Tabs navigation elements
  const tabBtnGen = document.getElementById("tab-btn-generator");
  const tabBtnSettings = document.getElementById("tab-btn-settings");
  const panelGen = document.getElementById("panel-generator");
  const panelSettings = document.getElementById("panel-settings");

  // Queue elements
  const btnSendQueue = document.getElementById("btn-send-queue");
  const statusContainer = document.getElementById("status-container");
  const statusText = document.getElementById("status-text");
  const errorContainer = document.getElementById("error-container");

  // Checkboxes
  const chkMain = document.getElementById("chk-main");
  const chkVariation = document.getElementById("chk-variation");
  const chkDescription = document.getElementById("chk-description");
  const chkText = document.getElementById("chk-text");

  // Badges
  const badgeMain = document.getElementById("badge-main");
  const badgeVariation = document.getElementById("badge-variation");
  const badgeDescription = document.getElementById("badge-description");

  // Settings elements
  const inputServerUrl = document.getElementById("input-server-url");
  const btnSaveSettings = document.getElementById("btn-save-settings");
  const settingsSaveStatus = document.getElementById("settings-save-status");

  // Load Settings on start
  let serverUrl = "http://localhost:8000";
  chrome.storage.local.get(["serverUrl"], (result) => {
    if (result.serverUrl) {
      serverUrl = result.serverUrl;
      inputServerUrl.value = serverUrl;
    }
  });

  // Save Settings
  btnSaveSettings.addEventListener("click", () => {
    const url = inputServerUrl.value.trim();
    chrome.storage.local.set({ serverUrl: url }, () => {
      serverUrl = url;
      settingsSaveStatus.classList.remove("hidden");
      setTimeout(() => settingsSaveStatus.classList.add("hidden"), 2000);
    });
  });

  // Switch tabs
  tabBtnGen.addEventListener("click", () => {
    tabBtnGen.classList.add("active");
    tabBtnSettings.classList.remove("active");
    panelGen.classList.add("active");
    panelSettings.classList.remove("active");
  });

  tabBtnSettings.addEventListener("click", () => {
    tabBtnSettings.classList.add("active");
    tabBtnGen.classList.remove("active");
    panelSettings.classList.add("active");
    panelGen.classList.remove("active");
  });

  // Helper displays
  function showStatus(text) {
    statusText.textContent = text;
    statusContainer.classList.remove("hidden");
    errorContainer.classList.add("hidden");
  }

  function hideMessage() {
    statusContainer.classList.add("hidden");
    errorContainer.classList.add("hidden");
  }

  function showError(msg) {
    errorContainer.textContent = msg;
    errorContainer.classList.remove("hidden");
    statusContainer.classList.add("hidden");
  }

  function updateBadge(badge, count) {
    badge.classList.remove("loading");
    badge.textContent = count;
    if (count === 0) {
      badge.classList.add("empty");
    } else {
      badge.classList.remove("empty");
    }
  }

  // --- INITIALIZE (Get Preview Counts) ---
  try {
    const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
    if (tabs && tabs.length > 0) {
      const activeTab = tabs[0];
      if (activeTab.url && (activeTab.url.includes("aliexpress.com") || activeTab.url.includes("aliexpress.us"))) {
        const productId = getProductIdFromUrl(activeTab.url);
        
        // Inject content script if not already loaded
        try {
          await chrome.scripting.executeScript({
            target: { tabId: activeTab.id },
            files: ["content.js"]
          });
        } catch (e) {}

        // Get DOM-visible counts from content script
        chrome.tabs.sendMessage(activeTab.id, { action: "getPreviewCounts" }, (response) => {
          if (chrome.runtime.lastError) {
             badgeMain.textContent = "Error";
             badgeVariation.textContent = "Error";
             badgeDescription.textContent = "Error";
             return;
          }
          if (response && response.success) {
            updateBadge(badgeMain, response.counts.main);
            updateBadge(badgeVariation, response.counts.variation);

            // ALSO ask background for intercepted description images (validating matching productId)
            chrome.runtime.sendMessage({ action: "get_desc_images", tabId: activeTab.id, productId: productId }, (bgRes) => {
              const bgDescCount = (bgRes && bgRes.images) ? bgRes.images.length : 0;
              const domDescCount = response.counts.description;
              const totalDesc = Math.max(bgDescCount, domDescCount);
              console.log(`[Popup] Badge: DOM desc=${domDescCount}, Background intercepted=${bgDescCount}, showing=${totalDesc}`);
              updateBadge(badgeDescription, totalDesc);
            });
          }
        });
      } else {
         badgeMain.textContent = "-";
         badgeVariation.textContent = "-";
         badgeDescription.textContent = "-";
      }
    }
  } catch (e) {
    console.error("Initialization error:", e);
  }


  // --- ADD TO QUEUE ---
  btnSendQueue.addEventListener("click", async () => {
    hideMessage();
    
    btnSendQueue.disabled = true;
    const origText = btnSendQueue.textContent;
    btnSendQueue.textContent = "Scraping & Sending...";
    showStatus("Scraping page elements from active tab...");

    try {
      const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
      if (!tabs || tabs.length === 0) {
        showError("Could not detect active browser tab.");
        btnSendQueue.disabled = false;
        btnSendQueue.textContent = origText;
        return;
      }
      const activeTab = tabs[0];

      if (!activeTab.url || !(activeTab.url.includes("aliexpress.com") || activeTab.url.includes("aliexpress.us"))) {
        showError("Please navigate to an AliExpress product page and try again.");
        btnSendQueue.disabled = false;
        btnSendQueue.textContent = origText;
        return;
      }

      chrome.tabs.sendMessage(activeTab.id, { action: "scrapeProduct" }, async (response) => {
        if (!response || !response.success) {
          showError("Failed to scrape page DOM details.");
          btnSendQueue.disabled = false;
          btnSendQueue.textContent = origText;
          return;
        }

        const scrapedData = response.data;

        // ==========================================
        // ALISAVE-STYLE: REQUEST INTERCEPTED IMAGES FROM BACKGROUND
        // ==========================================
        // background.js already caught the description API response when the page loaded.
        // Just ask it for the cached result — instant, no scrolling, no CSP issues.
        showStatus("Retrieving intercepted description images...");
        let interceptedDescImages = [];
        try {
          const productId = getProductIdFromUrl(activeTab.url);
          interceptedDescImages = await new Promise((resolve) => {
            chrome.runtime.sendMessage({ action: "get_desc_images", tabId: activeTab.id, productId: productId }, (res) => {
              if (chrome.runtime.lastError) { resolve([]); return; }
              resolve((res && res.images) ? res.images : []);
            });
          });
          console.log(`[Popup] Background returned ${interceptedDescImages.length} intercepted desc images.`);
        } catch(e) {
          console.error("Background image fetch failed:", e);
        }


        // Merge: content script DOM images + background intercepted images, minus main/variation
        const mainSet = new Set(scrapedData.main_images);
        const varSet = new Set(scrapedData.variation_images);
        const descriptionSet = new Set(scrapedData.description_images);

        interceptedDescImages.forEach(img => {
          if (!mainSet.has(img) && !varSet.has(img)) {
            descriptionSet.add(img);
          }
        });

        const finalDescImages = Array.from(descriptionSet);
        console.log(`[Popup] Final description image count: ${finalDescImages.length}`);

        showStatus("Transmitting scraped details to local server queue...");

        const payload = {
          title: chkText.checked ? scrapedData.title : "Untitled Product",
          price: chkText.checked ? scrapedData.price : "",
          specs: chkText.checked ? scrapedData.specs : {},
          description_text: chkText.checked ? scrapedData.description_text : "",
          main_images: chkMain.checked ? scrapedData.main_images : [],
          variation_images: chkVariation.checked ? scrapedData.variation_images : [],
          description_images: chkDescription.checked ? finalDescImages : []
        };

        console.log(`[Popup] ✅ SENDING payload: main=${payload.main_images.length}, variation=${payload.variation_images.length}, description=${payload.description_images.length}`);
        console.log(`[Popup] chkDescription.checked = ${chkDescription.checked}`);
        console.log(`[Popup] First desc image:`, finalDescImages[0] || "NONE");

        fetch(`${serverUrl}/api/queue-product`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json"
          },
          body: JSON.stringify(payload)
        })
        .then(async (res) => {
          if (!res.ok) {
            const errText = await res.text();
            throw new Error(`Server error ${res.status}: ${errText}`);
          }
          return res.json();
        })
        .then(data => {
          showStatus("Successfully added to automation queue!");
          setTimeout(() => hideMessage(), 2500);
          btnSendQueue.disabled = false;
          btnSendQueue.textContent = origText;
        })
        .catch(err => {
          showError(`Connection to workspace server failed: ${err.message}. Make sure uvicorn is running on ${serverUrl}.`);
          btnSendQueue.disabled = false;
          btnSendQueue.textContent = origText;
        });
      });
    } catch (err) {
      showError(`Error sending details: ${err.message}`);
      btnSendQueue.disabled = false;
      btnSendQueue.textContent = origText;
    }
  });

});
