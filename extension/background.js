// ==========================================
// BACKGROUND.JS — AliSave-style XHR Interceptor
// ==========================================
// MV3 service workers are ephemeral — global variables like `descCache = {}`
// get wiped every time Chrome kills and restarts the service worker.
// We use chrome.storage.session to persist the cache across restarts.

// ==========================================
// INTERCEPT DESCRIPTION IMAGES VIA webRequest
// ==========================================
chrome.webRequest.onCompleted.addListener(
  (details) => {
    if (!details.url) return;
    const url = details.url;

    const isDescUrl = (
      url.includes('desc.htm') ||
      url.includes('descriptionModule') ||
      url.includes('/desc/') ||
      (url.includes('alicdn.com') && url.includes('description')) ||
      (url.includes('fourier.aliexpress') && url.includes('desc'))
    );
    if (!isDescUrl) return;

    const tabId = details.tabId;

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

    console.log(`[Background] Fetching description from: ${realDescUrl} for tab ${tabId}`);

    fetch(realDescUrl, {
      headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://www.aliexpress.us/',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5'
      }
    })
    .then(res => {
      console.log(`[Background] Desc fetch status: ${res.status}, type: ${res.headers.get('content-type')}`);
      return res.text();
    })
    .then(html => {
      console.log(`[Background] Desc response length: ${html.length} chars. Sample: ${html.substring(0, 150)}`);
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
      console.log(`[Background] Saving ${imgArray.length} description images to storage for tab ${tabId}`);

      // Use chrome.storage.session — persists across service worker restarts within session
      const cacheKey = `desc_${tabId}`;
      chrome.storage.session.get([cacheKey], (existing) => {
        const prev = new Set(existing[cacheKey] || []);
        imgArray.forEach(img => prev.add(img));
        chrome.storage.session.set({ [cacheKey]: Array.from(prev) });
      });
    })
    .catch(err => {
      console.error(`[Background] Failed to fetch desc URL: ${err.message}`);
    });
  },
  {
    urls: [
      "https://*.alicdn.com/*desc*",
      "https://*.aliexpress.com/*desc*",
      "https://*.aliexpress.us/*desc*",
      "https://fourier.aliexpress.com/*"
    ]
  }
);

// Clean up storage when tab navigates or closes
chrome.tabs.onRemoved.addListener((tabId) => {
  chrome.storage.session.remove(`desc_${tabId}`);
});
chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (changeInfo.status === 'loading') {
    chrome.storage.session.remove(`desc_${tabId}`);
  }
});

// ==========================================
// MESSAGE HANDLER
// ==========================================
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {

  if (request.action === "get_desc_images") {
    const tabId = request.tabId;
    const cacheKey = `desc_${tabId}`;
    chrome.storage.session.get([cacheKey], (result) => {
      const images = result[cacheKey] || [];
      console.log(`[Background] Popup requested desc images for tab ${tabId}. Returning ${images.length} images.`);
      sendResponse({ images });
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

