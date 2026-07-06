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
// Using onCompleted ensures cookies and TLS session are fully active, preventing status 500 errors.

chrome.webRequest.onCompleted.addListener(
  (details) => {
    if (!details.url) return;
    const url = details.url;

    // Filter for description endpoints
    const isDescUrl = (
      url.includes('desc.htm') ||
      url.includes('descriptionModule') ||
      url.includes('/desc/') ||
      (url.includes('alicdn.com') && url.includes('description'))
    );
    if (!isDescUrl) return;

    const tabId = details.tabId;
    if (tabId === -1) return; // Skip background/telemetry frame requests

    // AliExpress wraps the real URL inside fourier.aliexpress.com/ts?url=ENCODED_REAL_URL
    let realDescUrl = url;
    try {
      const parsedUrl = new URL(url);
      const innerUrl = parsedUrl.searchParams.get('url');
      if (innerUrl) {
        realDescUrl = decodeURIComponent(innerUrl);
        console.log(`[Background] Decoded real desc URL: ${realDescUrl}`);
      }
    } catch(e) {}

    // ===== CORS & SECURITY FIX =====
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
        console.log(`[Background] Skipping fetch for unauthorized domain: ${hostname}`);
        return;
      }
    } catch(e) {
      return;
    }

    console.log(`[Background] Intercepted description URL: ${realDescUrl} for tab ${tabId}`);

    fetch(realDescUrl, {
      headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://www.aliexpress.us/',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5'
      }
    })
    .then(res => {
      console.log(`[Background] Desc fetch status: ${res.status}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.text();
    })
    .then(html => {
      const regex = /(?:https?:)?\/\/[^\s"'<>]*alicdn\.com[^\s"'<>]*\/kf\/[a-zA-Z0-9_]+\.(?:jpg|png|jpeg|webp)/gi;
      const images = new Set();
      let m;
      while ((m = regex.exec(html)) !== null) {
        let imgUrl = m[0];
        imgUrl = imgUrl.replace(/_\d+x\d+[^.]*\.(jpg|png|jpeg|webp)/, '.$1')
                       .replace(/_.webp$/, '');
        if (imgUrl.startsWith('//')) imgUrl = 'https:' + imgUrl;
        images.add(imgUrl);
      }
      const imgArray = Array.from(images);
      const productId = getProductIdFromDescUrl(realDescUrl);

      console.log(`[Background] Intercepted ${imgArray.length} images for productId: ${productId} on tab ${tabId}`);

      if (imgArray.length > 0 && productId) {
        const cacheKey = `desc_${tabId}`;
        chrome.storage.session.get([cacheKey], (existing) => {
          const cacheData = existing[cacheKey] || {};
          let mergedImages = new Set();
          
          if (cacheData.productId === productId) {
            mergedImages = new Set([...(cacheData.images || []), ...imgArray]);
          } else {
            mergedImages = new Set(imgArray);
          }

          chrome.storage.session.set({
            [cacheKey]: {
              productId: productId,
              images: Array.from(mergedImages),
              timestamp: Date.now()
            }
          }, () => {
            console.log(`[Background] Saved ${mergedImages.size} description images in storage for productId: ${productId}`);
          });
        });
      }
    })
    .catch(err => {
      console.error(`[Background] Failed to fetch desc URL: ${err.message}`);
    });
  },
  {
    urls: [
      "https://*.alicdn.com/*desc*",
      "https://*.aliexpress.com/*desc*",
      "https://*.aliexpress.us/*desc*"
    ]
  }
);


// Clean up storage when tab is closed
chrome.tabs.onRemoved.addListener((tabId) => {
  chrome.storage.session.remove(`desc_${tabId}`);
});

// Note: Removed chrome.tabs.onUpdated listener. 
// We no longer clear the cache on tab update status === 'loading' to prevent 
// race-condition wipes when sub-resources load. Stale cache is handled via productId checking.

// ==========================================
// MESSAGE HANDLER
// ==========================================
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {

  if (request.action === "get_desc_images") {
    const tabId = request.tabId;
    const requestProductId = request.productId;
    const cacheKey = `desc_${tabId}`;

    chrome.storage.session.get([cacheKey], (result) => {
      const cacheData = result[cacheKey] || {};
      
      // Verification check: Only return cache if the requested productId matches the cached one
      if (cacheData.images && cacheData.images.length > 0) {
        if (!requestProductId || cacheData.productId === requestProductId) {
          console.log(`[Background] Cache MATCH: Returning ${cacheData.images.length} images for productId: ${requestProductId}`);
          sendResponse({ images: cacheData.images });
          return;
        } else {
          console.log(`[Background] Cache STALE: Requested ${requestProductId}, cached ${cacheData.productId}. Returning [].`);
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


