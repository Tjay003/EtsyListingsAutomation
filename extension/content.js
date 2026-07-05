// ==========================================
// SCRAPER VERSION: TARGETED DESCRIPTION METHOD v4
// ==========================================
console.log("=== SCRAPER VERSION: TARGETED DESCRIPTION METHOD v4 ===");

// Listen for messages from the popup script
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === "scrapeProduct") {
    scrapePage().then(productData => {
      sendResponse({ success: true, data: productData });
    }).catch(error => {
      sendResponse({ success: false, error: error.message });
    });
  } else if (request.action === "getPreviewCounts") {
    scrapePage().then(productData => {
      sendResponse({ 
        success: true, 
        counts: {
          main: productData.main_images.length,
          variation: productData.variation_images.length,
          description: productData.description_images.length
        }
      });
    }).catch(error => {
      sendResponse({ success: false, error: error.message });
    });
  }
  return true; // Keep message channel open for asynchronous reply
});

function getParentClassChain(imgTag, depth=12) {
  let chain = [];
  let curr = imgTag.parentElement;
  let d = 0;
  while (curr && curr.nodeName !== "#document" && d < depth) {
    if (curr.className && typeof curr.className === "string") {
      chain.push(curr.className);
    }
    curr = curr.parentElement;
    d++;
  }
  return chain.join(" ");
}

async function scrapePage() {
  // Helper function to clean image URL
  const cleanImageURL = (src) => {
    let cleanUrl = src.replace(/_\d+x\d+.*$/, "")
                       .replace(/_Q\d+.*$/, "")
                       .replace(/_50x50.*$/, "")
                       .replace(/_120x120.*$/, "")
                       .replace(/_220x220.*$/, "")
                       .replace(/_350x350.*$/, "")
                       .replace(/_640x640.*$/, "")
                       .replace(/_\.webp$/, "")
                       .trim();
    if (cleanUrl.startsWith("//")) {
      cleanUrl = "https:" + cleanUrl;
    }
    return cleanUrl;
  };

  // 1. Scrape Title
  let title = "";
  const titleSelectors = [
    ".title--productTitleText--3v5S1kE",
    "[data-pl='product-title']",
    ".product-title",
    "h1"
  ];
  for (const sel of titleSelectors) {
    const el = document.querySelector(sel);
    if (el) {
      title = el.innerText.trim();
      if (title) break;
    }
  }
  if (!title) {
    title = document.title.replace("- AliExpress", "").trim();
  }

  // 2. Scrape Price
  let price = "";
  const priceSelectors = [
    '[class*="price-default--current--"]',
    '[class*="price-default--currentWrap--"]',
    '[class*="price--currentPriceText--"]',
    ".price--currentPriceText--2s1756t",
    ".price--currentPriceText--32sS1kE",
    "[data-pl='product-price']",
    ".product-price-current",
    ".price-promotion"
  ];
  for (const sel of priceSelectors) {
    const el = document.querySelector(sel);
    if (el) {
      price = el.innerText.trim();
      if (price) break;
    }
  }

  // 3. Scrape and Classify Images
  const PRODUCT_HASH_REGEX = /S[a-zA-Z0-9]{30,35}/;
  const MAIN_CLASSES = ["image-view-v2--wrap", "slider--img", "magnifier--wrap"];
  const VARIATION_CLASSES = ["sku-item--image", "sku-item--skus", "sku-item--box"];
  const DESCRIPTION_CLASSES = ["detail-desc-decorate-richtext", "product-description", "description--product-description"];
  const SKIP_CLASSES = [
    "card-out-wrapper", "slider-card", "Categoey--", "shipping--", "choice-mind--",
    "coupon-block--", "price-default--", "recently-view", "recentlyview",
    "pc-header", "footer"
  ];

  const mainImages = new Set();
  const variationImages = new Set();
  const descriptionImages = new Set();

  const allImgs = document.querySelectorAll("img");
  
  allImgs.forEach(img => {
    const src = img.src || img.getAttribute("data-src") || img.getAttribute("lazy-src") || img.getAttribute("data-lazy-src") || img.getAttribute("data-src-zoom-image");
    if (!src) return;
    
    // Check if it's an AliExpress product image format
    if (!PRODUCT_HASH_REGEX.test(src) && !src.includes("/kf/")) {
        return; 
    }

    const chain = getParentClassChain(img);

    // Skip known bad containers (reviews, UI, etc.)
    if (SKIP_CLASSES.some(skipCls => chain.includes(skipCls))) {
      return;
    }

    let isReviewOrAvatar = false;
    let parent = img.parentElement;
    while (parent) {
      const id = (parent.id || "").toLowerCase();
      const className = (typeof parent.className === "string" ? parent.className : "").toLowerCase();
      if (
        id.includes("feedback") || id.includes("review") || id.includes("comment") || id.includes("avatar") ||
        className.includes("feedback") || className.includes("review") || className.includes("comment") || className.includes("avatar") || className.includes("user-")
      ) {
        isReviewOrAvatar = true;
        break;
      }
      parent = parent.parentElement;
    }
    
    if (isReviewOrAvatar) return;

    let cleanUrl = cleanImageURL(src);

    if (VARIATION_CLASSES.some(c => chain.includes(c))) {
      variationImages.add(cleanUrl);
    } else if (MAIN_CLASSES.some(c => chain.includes(c))) {
      mainImages.add(cleanUrl);
    } else if (DESCRIPTION_CLASSES.some(c => chain.includes(c))) {
      descriptionImages.add(cleanUrl);
    }
  });

  // Helper to extract text contents recursively, including traversing open shadow roots
  const getDeepTextContent = (node) => {
    if (!node) return "";
    let text = "";
    
    if (node.shadowRoot) {
      text += getDeepTextContent(node.shadowRoot);
    }
    
    if (node.childNodes && node.childNodes.length > 0) {
      node.childNodes.forEach(child => {
        if (child.nodeType === Node.TEXT_NODE) {
          text += child.textContent;
        } else if (child.nodeType === Node.ELEMENT_NODE) {
          text += " " + getDeepTextContent(child) + " ";
        }
      });
    } else {
      text += node.textContent || "";
    }
    return text;
  };

  // 4. Scrape Specifications & Details (handle wildcard prefix class names)
  const specsObj = {};
  const propContainers = document.querySelectorAll('[class*="specification--prop--"], .product-prop');
  propContainers.forEach(container => {
    const titleEl = container.querySelector('[class*="specification--title--"], .title, .name');
    const descEl = container.querySelector('[class*="specification--desc--"], .value, .desc');
    if (titleEl && descEl) {
      const key = titleEl.innerText.replace(/:$/, "").trim();
      const val = descEl.innerText.trim();
      if (key && val) {
        specsObj[key] = val;
      }
    }
  });

  // Extract description text, accounting for Shadow DOM
  const descContainer = document.querySelector('[class*="description--product-description--"], [data-pl="product-description"], #product-description, .product-description, #desc-lazyload-container, .detail-desc-decorate-richtext');
  let descText = "";
  if (descContainer) {
    descText = getDeepTextContent(descContainer).replace(/\s+/g, " ").trim();
  }


  // ==========================================
  // FETCH HIDDEN DESCRIPTION IMAGES
  // ==========================================
  // Step 1 (global window.runParams extraction) is handled by popup.js using
  // chrome.scripting.executeScript({world:"MAIN"}) which bypasses AliExpress's CSP.
  // content.js handles Step 2: targeted description container expand + scrape.
  console.log('[AliExpress Scraper] Starting targeted description container scrape...');

  // --- Step 2: Click ONLY the description section's "View More" button ---
  // Target the known AliExpress description container and look for a button INSIDE it only.
  const DESC_CONTAINER_SELECTORS = [
    '#product-description',
    '#desc-lazyload-container',
    '.detail-desc-decorate-richtext',
    '.product-description',
    '.description--product-description'
  ];
  let descImgContainer = null;
  for (const sel of DESC_CONTAINER_SELECTORS) {
    descImgContainer = document.querySelector(sel);
    if (descImgContainer) break;
  }

  if (descImgContainer) {
    // Only scroll to and click buttons INSIDE the description container
    descImgContainer.scrollIntoView({ behavior: 'auto' });
    await new Promise(resolve => setTimeout(resolve, 500));

    const innerBtns = descImgContainer.querySelectorAll('button, [role="button"], .more-btn, .show-more, .view-more');
    for (const btn of innerBtns) {
      const text = (btn.innerText || '').toLowerCase();
      if (text.includes('more') || btn.className.toLowerCase().includes('more')) {
        console.log('[AliExpress Scraper] Clicking description View More button...');
        btn.click();
        await new Promise(resolve => setTimeout(resolve, 1000));
      }
    }

    // Also look for AliExpress's specific expand trigger which is often a div overlay
    const expandTriggers = descImgContainer.querySelectorAll('[class*="more"], [class*="expand"], [class*="unfold"]');
    for (const trigger of expandTriggers) {
      if (trigger.clientHeight > 0 && trigger.clientHeight < 60) {
        console.log('[AliExpress Scraper] Clicking expand trigger:', trigger.className);
        trigger.click();
        await new Promise(resolve => setTimeout(resolve, 1000));
      }
    }

    // Wait for images to lazy-load after clicking
    await new Promise(resolve => setTimeout(resolve, 1500));

    // Scrape images from the description container specifically (including shadow DOM if present)
    const rootNode = descImgContainer.shadowRoot || descImgContainer;
    const descImgs = rootNode.querySelectorAll('img');
    descImgs.forEach(img => {
      const src = img.src || img.getAttribute('data-src') || img.getAttribute('lazy-src') || img.getAttribute('data-lazy-src');
      if (src && (PRODUCT_HASH_REGEX.test(src) || src.includes('/kf/'))) {
        descriptionImages.add(cleanImageURL(src));
      }
    });
    console.log(`[AliExpress Scraper] Description container scrape added up to ${descriptionImages.size} total.`);
  }


  // --- Step 3: Scroll back to where user was ---
  window.scrollTo(0, window.scrollY > 200 ? 0 : window.scrollY);

  return {
    title: title,
    price: price,
    main_images: Array.from(mainImages),
    variation_images: Array.from(variationImages),
    description_images: Array.from(descriptionImages),
    specs: specsObj,
    description_text: descText
  };
}
