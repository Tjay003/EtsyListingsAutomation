document.addEventListener("DOMContentLoaded", () => {
  // Tabs navigation elements
  const tabBtnGen = document.getElementById("tab-btn-generator");
  const tabBtnSettings = document.getElementById("tab-btn-settings");
  const panelGen = document.getElementById("panel-generator");
  const panelSettings = document.getElementById("panel-settings");

  // Generator elements
  const btnScrape = document.getElementById("btn-scrape");
  const statusContainer = document.getElementById("status-container");
  const statusText = document.getElementById("status-text");
  const errorContainer = document.getElementById("error-container");
  const outputContainer = document.getElementById("output-container");
  const outputTitle = document.getElementById("output-title");
  const outputPrice = document.getElementById("output-price");
  const outputTags = document.getElementById("output-tags");
  const outputDesc = document.getElementById("output-desc");
  const titleCounter = document.getElementById("title-counter");

  // Settings elements
  const inputApiKey = document.getElementById("input-api-key");
  const selectModel = document.getElementById("select-model");
  const inputCancelPolicy = document.getElementById("input-cancellation-policy");
  const inputReturnPolicy = document.getElementById("input-return-policy");
  const btnSaveSettings = document.getElementById("btn-save-settings");
  const settingsSaveStatus = document.getElementById("settings-save-status");

  // Copy buttons
  const copyBtns = {
    title: document.getElementById("copy-title"),
    price: document.getElementById("copy-price"),
    tags: document.getElementById("copy-tags"),
    desc: document.getElementById("copy-desc")
  };

  // Default shop policies
  const DEFAULT_CANCEL = "Cancellation is allowed within 5 hours after placing the order.";
  const DEFAULT_RETURN = "Returns and refunds are accepted for items that arrive damaged or incorrect only.";

  // Load Settings on start
  chrome.storage.local.get(["apiKey", "model", "cancelPolicy", "returnPolicy"], (result) => {
    inputApiKey.value = result.apiKey || "";
    selectModel.value = result.model || "gemini-flash-latest";
    inputCancelPolicy.value = result.cancelPolicy || DEFAULT_CANCEL;
    inputReturnPolicy.value = result.returnPolicy || DEFAULT_RETURN;
  });

  // Save Settings
  btnSaveSettings.addEventListener("click", () => {
    const apiKey = inputApiKey.value.trim();
    const model = selectModel.value;
    const cancelPolicy = inputCancelPolicy.value.trim();
    const returnPolicy = inputReturnPolicy.value.trim();

    chrome.storage.local.set({ apiKey, model, cancelPolicy, returnPolicy }, () => {
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

  // Live Title character counter
  outputTitle.addEventListener("input", () => {
    const len = outputTitle.value.length;
    titleCounter.textContent = `${len}/140`;
    if (len > 140) {
      titleCounter.classList.add("warning");
    } else {
      titleCounter.classList.remove("warning");
    }
  });

  // Scrape and Generate Listing
  btnScrape.addEventListener("click", async () => {
    hideMessage();
    outputContainer.classList.add("hidden");
    
    // Set UI to loading state instantly
    btnScrape.disabled = true;
    btnScrape.textContent = "Processing...";
    showStatus("Initializing scraping request...");

    try {
      // 1. Fetch settings from storage
      const settings = await new Promise(resolve => {
        chrome.storage.local.get(["apiKey", "model", "cancelPolicy", "returnPolicy"], resolve);
      });

      if (!settings.apiKey) {
        showError("Please set your Google Gemini API Key in the Settings tab first.");
        btnScrape.disabled = false;
        btnScrape.textContent = "Scrape & Generate Copy";
        return;
      }

      // 2. Query active browser tab
      let activeTab;
      try {
        const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
        if (!tabs || tabs.length === 0) {
          showError("Could not detect active browser tab.");
          btnScrape.disabled = false;
          btnScrape.textContent = "Scrape & Generate Copy";
          return;
        }
        activeTab = tabs[0];
      } catch (e) {
        showError("Failed to query browser tabs.");
        btnScrape.disabled = false;
        btnScrape.textContent = "Scrape & Generate Copy";
        return;
      }

      // Check if on AliExpress
      if (!activeTab.url || !(activeTab.url.includes("aliexpress.com") || activeTab.url.includes("aliexpress.us"))) {
        showError("Please navigate to an AliExpress product page and try again.");
        btnScrape.disabled = false;
        btnScrape.textContent = "Scrape & Generate Copy";
        return;
      }

      // 3. Request scraping from content script
      showStatus("Connecting to page and scraping DOM details...");
      
      // Inject content script if not already loaded (failsafe)
      try {
        await chrome.scripting.executeScript({
          target: { tabId: activeTab.id },
          files: ["content.js"]
        });
      } catch (e) {
        // Script might already be injected by manifest, ignore execute errors
      }

      chrome.tabs.sendMessage(activeTab.id, { action: "scrapeProduct" }, async (response) => {
        if (!response) {
          showError("Failed to communicate with the page. Try reloading the AliExpress tab and opening this popup again.");
          btnScrape.disabled = false;
          btnScrape.textContent = "Scrape & Generate Copy";
          return;
        }
        if (!response.success) {
          showError(`Scraping error: ${response.error}`);
          btnScrape.disabled = false;
          btnScrape.textContent = "Scrape & Generate Copy";
          return;
        }

        const scrapedData = response.data;
        
        // Process images to send them multimodally
        showStatus("Downloading & converting product images for visual scanning...");
        const imageParts = [];
        const imagesToProcess = scrapedData.images.slice(0, 3); // Grab top 3 product images
        
        for (const imgUrl of imagesToProcess) {
          try {
            const part = await urlToGenerativePart(imgUrl);
            if (part) imageParts.push(part);
          } catch (e) {
            console.error("Failed to load image part:", imgUrl, e);
          }
        }
        
        showStatus("Sending request to Google Gemini API...");

        try {
          const listing = await generateCopywriting(
            settings.apiKey,
            settings.model || "gemini-flash-latest",
            scrapedData,
            imageParts,
            settings.cancelPolicy || DEFAULT_CANCEL,
            settings.returnPolicy || DEFAULT_RETURN,
            (statusMsg) => showStatus(statusMsg)
          );

          // Populate fields
          outputTitle.value = listing.title;
          titleCounter.textContent = `${listing.title.length}/140`;
          if (listing.title.length > 140) titleCounter.classList.add("warning");
          else titleCounter.classList.remove("warning");

          outputPrice.value = listing.suggested_price || scrapedData.price || "";
          outputTags.value = listing.tags.join(", ");
          outputDesc.value = listing.description;

          hideMessage();
          outputContainer.classList.remove("hidden");
        } catch (error) {
          showError(`Generation failed: ${error.message}`);
        } finally {
          btnScrape.disabled = false;
          btnScrape.textContent = "Scrape & Generate Copy";
        }
      });
    } catch (err) {
      showError(`An unexpected error occurred: ${err.message}`);
      btnScrape.disabled = false;
      btnScrape.textContent = "Scrape & Generate Copy";
    }
  });

  // Call Gemini API with retries and structured output
  async function generateCopywriting(apiKey, model, scrapedData, imageParts, cancelPolicy, returnPolicy, onStatusUpdate) {
    const prompt = `Create a structured Etsy product listing for this AliExpress item.
Original Title: ${scrapedData.title}
Scraped Specifications:
${scrapedData.specs}
Scraped Description:
${scrapedData.descriptionFallback}
Estimated Price: ${scrapedData.price}

Guidelines:
1. Write an SEO-friendly, catchy Title under 140 characters. Focus on keywords buyers search for.
2. Write a detailed, structured Description highlighting specifications, materials, and benefits. Examine the provided product photos to describe colors, shapes, textures, straps, and hardware accurately.
3. Provide exactly 13 relevant search Tags (keywords or phrases). Ensure each tag is strictly under 20 characters (including spaces).
4. Suggest a retail price in USD.`;

    const schema = {
      type: "OBJECT",
      properties: {
        title: { type: "STRING", description: "Catchy search-optimized title under 140 characters" },
        description: { type: "STRING", description: "Detailed product description focusing on specs and design details" },
        tags: {
          type: "ARRAY",
          items: { type: "STRING" },
          description: "Exactly 13 tags under 20 characters each"
        },
        suggested_price: { type: "STRING", description: "Etsy retail price in USD, e.g., '$24.99'" }
      },
      required: ["title", "description", "tags", "suggested_price"]
    };

    const url = `https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent?key=${apiKey}`;
    
    // Combine the text prompt part with the base64 visual image parts
    const contentParts = [{ text: prompt }];
    if (imageParts && imageParts.length > 0) {
      imageParts.forEach(part => contentParts.push(part));
    }

    const payload = {
      contents: [{ parts: contentParts }],
      generationConfig: {
        responseMimeType: "application/json",
        responseSchema: schema
      }
    };

    const maxRetries = 3;
    let delay = 2000;
    let lastError;

    for (let attempt = 0; attempt < maxRetries; attempt++) {
      try {
        if (onStatusUpdate) {
          onStatusUpdate(`Sending request to Google Gemini API (Attempt ${attempt + 1}/${maxRetries})...`);
        }
        
        const response = await fetch(url, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });

        if (response.ok) {
          const resJson = await response.json();
          let listing = JSON.parse(resJson.candidates[0].content.parts[0].text);

          // Tag check & local guardrail
          let cleanedTags = [];
          listing.tags.forEach(tag => {
            let t = tag.trim().toLowerCase().replace(/['"]/g, "");
            if (t.length > 20) {
              t = t.slice(0, 20).trim();
            }
            if (t && !cleanedTags.includes(t)) {
              cleanedTags.push(t);
            }
          });
          listing.tags = cleanedTags.slice(0, 13);

          // Append shop policies
          const policyFooter = `\n\n---\nCancellation Policy: ${cancelPolicy}\nReturns & Refunds Policy: ${returnPolicy}`;
          listing.description = listing.description.trim() + policyFooter;

          return listing;
        }

        const errText = await response.text();
        if (response.status === 429 || response.status === 503) {
          const waitSec = Math.round(delay / 1000);
          if (onStatusUpdate) {
            onStatusUpdate(`Google API busy (${response.status}). Retrying in ${waitSec}s...`);
          }
          await new Promise(r => setTimeout(r, delay));
          delay *= 2;
        } else {
          // Fail fast on non-rate-limit errors
          throw new Error(`Google API Error: ${response.status} - ${errText}`);
        }
      } catch (error) {
        lastError = error;
        // If it's a structural or bad request error (not a rate limit), throw immediately
        const isRateLimit = error.message.includes("429") || error.message.includes("503") || error.message.toLowerCase().includes("busy") || error.message.toLowerCase().includes("quota");
        if (error.message.includes("Google API Error") && !isRateLimit) {
          throw error;
        }
        if (attempt < maxRetries - 1) {
          const waitSec = Math.round(delay / 1000);
          if (onStatusUpdate) {
            onStatusUpdate(`Network error. Retrying in ${waitSec}s...`);
          }
          await new Promise(r => setTimeout(r, delay));
          delay *= 2;
        }
      }
    }
    throw lastError;
  }

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

  // Setup copy events
  copyBtns.title.addEventListener("click", () => copyToClipboard(outputTitle.value, copyBtns.title));
  copyBtns.price.addEventListener("click", () => copyToClipboard(outputPrice.value, copyBtns.price));
  copyBtns.tags.addEventListener("click", () => copyToClipboard(outputTags.value, copyBtns.tags));
  copyBtns.desc.addEventListener("click", () => copyToClipboard(outputDesc.value, copyBtns.desc));

  function copyToClipboard(text, button) {
    if (!text) return;
    navigator.clipboard.writeText(text).then(() => {
      button.textContent = "Copied!";
      button.classList.add("copied");
      setTimeout(() => {
        button.textContent = "Copy";
        button.classList.remove("copied");
      }, 2000);
    });
  }

  // Convert image URL to base64 inlineData part for Gemini API
  async function urlToGenerativePart(url) {
    try {
      const response = await fetch(url);
      if (!response.ok) return null;
      const blob = await response.blob();
      return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onloadend = () => {
          const base64Data = reader.result.split(',')[1];
          resolve({
            inlineData: {
              mimeType: blob.type || "image/jpeg",
              data: base64Data
            }
          });
        };
        reader.onerror = reject;
        reader.readAsDataURL(blob);
      });
    } catch (error) {
      console.error("Error converting image for Gemini API:", error);
      return null;
    }
  }
});
