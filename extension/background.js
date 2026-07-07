// ==========================================
// BACKGROUND.JS — AliSave-style XHR Interceptor
// ==========================================
// MV3 service workers are ephemeral — global variables like `descCache = {}`
// get wiped every time Chrome kills and restarts the service worker.
// We use chrome.storage.session to persist the cache across restarts.

// Helper to extract productId from AliExpress description URLs
function getProductIdFromDescUrl(urlStr) {
  try {
    const url = new URL(urlStr);
    return url.searchParams.get("productId");
  } catch (e) {
    return null;
  }
}

// ==========================================
// INTERCEPT DESCRIPTION IMAGES VIA webRequest.onCompleted
// ==========================================
// Using onCompleted ensures cookies and TLS session are fully active, preventing status 500 error// Helper to clean tab URLs (strips query params and hashes)
function getCleanUrlPath(urlStr) {
  if (!urlStr) return "";
  try {
    const url = new URL(urlStr);
    return url.origin + url.pathname;
  } catch(e) {
    return urlStr;
  }
}

// ==========================================
// INTERCEPT DESCRIPTION IMAGES VIA webRequest.onCompleted
// ==========================================
chrome.webRequest.onCompleted.addListener(
  (details) => {
    if (!details.url) return;
    const url = details.url;

    // Filter for description endpoints
    const isDescUrl = (
      url.includes('desc.htm') ||
      url.includes('descriptionModule') ||
      url.includes('/desc/') ||
      url.includes('description') ||
      url.includes('fourier')
    );
    if (!isDescUrl) {
      console.log(`[Background] Request skipped: Not a description or fourier URL: ${url}`);
      return;
    }

    const tabId = details.tabId;
    if (tabId === -1) {
      console.log(`[Background] Request skipped: No valid tabId (-1) for URL: ${url}`);
      return;
    }

    // Decouple Fourier wrapper URL if present
    let realDescUrl = url;
    try {
      const parsedUrl = new URL(url);
      const innerUrl = parsedUrl.searchParams.get('url');
      if (innerUrl) {
        realDescUrl = decodeURIComponent(innerUrl);
        console.log(`[Background] Decoupled fourier URL to: ${realDescUrl}`);
      }
    } catch(e) {
      console.warn(`[Background] Failed to parse Fourier search params: ${e.message}`);
    }

    // Ensure we only fetch domains belonging to AliExpress / AliCDN to prevent CORS errors on third-party trackers
    try {
      const hostname = new URL(realDescUrl).hostname;
      const isAllowedDomain = (
        hostname.endsWith('aliexpress.com') ||
        hostname.endsWith('aliexpress.us') ||
        hostname.endsWith('alicdn.com') ||
        hostname.endsWith('aliexpress-media.com')
      );
      if (!isAllowedDomain) {
        console.log(`[Background] Request skipped: Hostname ${hostname} is not in allowed domains for URL: ${realDescUrl}`);
        return;
      }
    } catch(e) {
      console.error(`[Background] Request skipped: Invalid URL format: ${realDescUrl}`);
      return;
    }

    console.log(`[Background] Intercepted description URL: ${realDescUrl} for tab ${tabId}`);

    // Read the active tab's URL to store in cache
    chrome.tabs.get(tabId, (tab) => {
      if (chrome.runtime.lastError) {
        console.error(`[Background] chrome.tabs.get failed: ${chrome.runtime.lastError.message}`);
        return;
      }
      if (!tab || !tab.url) {
        console.warn(`[Background] Tab not found or has no URL for tab ID: ${tabId}`);
        return;
      }
      const cleanTabUrl = getCleanUrlPath(tab.url);
      console.log(`[Background] Fetching description HTML from: ${realDescUrl} (active tab: ${cleanTabUrl})...`);

      fetch(realDescUrl, {
        headers: {
          'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
          'Referer': 'https://www.aliexpress.us/',
          'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
          'Accept-Language': 'en-US,en;q=0.5'
        }
      })
      .then(res => {
        console.log(`[Background] Fetch response status: ${res.status} for URL: ${realDescUrl}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.text();
      })
      .then(html => {
        console.log(`[Background] Successfully fetched ${html.length} chars of HTML. Parsing images...`);
        
        // Broader regex matching both alicdn.com and aliexpress-media.com with optional file extension
        const regex = /(?:https?:)?\/\/[^\s"'<>]*?(?:alicdn\.com|aliexpress-media\.com)[^\s"'<>]*?\/kf\/[a-zA-Z0-9_-]+(?:\.(?:jpg|png|jpeg|webp))?/gi;
        const images = new Set();
        let m;
        while ((m = regex.exec(html)) !== null) {
          let imgUrl = m[0];
          // Clean size specifiers if present
          imgUrl = imgUrl.replace(/_\d+x\d+[^.]*\.(jpg|png|jpeg|webp)/, '.$1')
                         .replace(/_.webp$/, '');
          if (imgUrl.startsWith('//')) imgUrl = 'https:' + imgUrl;
          images.add(imgUrl);
        }
        const imgArray = Array.from(images);
        console.log(`[Background] Parsed ${imgArray.length} unique description images from HTML.`);

        if (imgArray.length > 0) {
          const cacheKey = `desc_${tabId}`;
          chrome.storage.session.get([cacheKey], (existing) => {
            const cacheData = existing[cacheKey] || {};
            let mergedImages = new Set();
            
            // If tabUrl matches, merge images. Otherwise, overwrite cache for the new product.
            if (cacheData.tabUrl === cleanTabUrl) {
              mergedImages = new Set([...(cacheData.images || []), ...imgArray]);
            } else {
              mergedImages = new Set(imgArray);
            }

            chrome.storage.session.set({
              [cacheKey]: {
                tabUrl: cleanTabUrl,
                images: Array.from(mergedImages),
                timestamp: Date.now()
              }
            }, () => {
              console.log(`[Background] Cached ${mergedImages.size} description images in session storage for ${cleanTabUrl}`);
            });
          });
        } else {
          console.warn(`[Background] No matching description images found in HTML matching the regex.`);
        }
      })
      .catch(err => {
        console.error(`[Background] Error fetching/parsing description: ${err.message}`);
      });
    });
  },
  {
    urls: [
      "*://*.alicdn.com/*desc*",
      "*://*.alicdn.com/*description*",
      "*://*.aliexpress.com/*desc*",
      "*://*.aliexpress.com/*description*",
      "*://*.aliexpress.us/*desc*",
      "*://*.aliexpress.us/*description*",
      "*://fourier.aliexpress.com/*"
    ]
  }
);

// Clean up storage when tab is closed
chrome.tabs.onRemoved.addListener((tabId) => {
  chrome.storage.session.remove(`desc_${tabId}`);
});

// ==========================================
// MESSAGE HANDLER
// ==========================================
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {

  if (request.action === "get_desc_images") {
    const tabId = request.tabId;
    const cleanRequestUrl = getCleanUrlPath(request.tabUrl);
    const cacheKey = `desc_${tabId}`;

    chrome.storage.session.get([cacheKey], (result) => {
      const cacheData = result[cacheKey] || {};
      
      if (cacheData.images && cacheData.images.length > 0) {
        if (!cleanRequestUrl || cacheData.tabUrl === cleanRequestUrl) {
          console.log(`[Background] Cache MATCH: Returning ${cacheData.images.length} images for URL: ${cleanRequestUrl}`);
          sendResponse({ images: cacheData.images });
          return;
        } else {
          console.log(`[Background] Cache STALE: Requested URL ${cleanRequestUrl}, cached URL ${cacheData.tabUrl}. Returning [].`);
        }
      }
      sendResponse({ images: [] });
    });
    return true; // Keep message channel open for async storage read
  }

  if (request.action === "fetch_html") {
    fetch(request.url, {
      headers: { 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)' }
    })
      .then(res => { if (!res.ok) throw new Error("HTTP " + res.status); return res.text(); })
      .then(html => sendResponse({ html }))
      .catch(err => sendResponse({ error: err.message }));
    return true;
  }
});




