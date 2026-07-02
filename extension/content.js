// Listen for messages from the popup script
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === "scrapeProduct") {
    try {
      const productData = scrapePage();
      sendResponse({ success: true, data: productData });
    } catch (error) {
      sendResponse({ success: false, error: error.message });
    }
  }
  return true; // Keep message channel open for asynchronous reply
});

function scrapePage() {
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

  // 3. Scrape High-Resolution Images
  const imageSet = new Set();
  const allImages = Array.from(document.querySelectorAll("img"));
  
  allImages.forEach(img => {
    const src = img.src || img.getAttribute("data-src") || img.getAttribute("lazy-src") || img.getAttribute("data-lazy-src");
    if (src && (src.includes("ae01.alicdn.com/kf") || src.includes("alicdn.com/kf"))) {
      // Reconstruct original high-resolution image URL by stripping thumbnail suffixes (like _Q90.jpg, _50x50.jpg, etc.)
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
      imageSet.add(cleanUrl);
    }
  });

  // 4. Scrape Specifications & Details
  const specs = [];
  
  // Scrape spec properties (e.g. materials, sizes)
  const specItems = document.querySelectorAll(".specification--prop--3Z4tNf0, .specification--title--2m1vV, .product-prop, .sku-property-text");
  specItems.forEach(item => {
    const text = item.innerText.trim();
    if (text && !specs.includes(text)) {
      specs.push(text);
    }
  });

  // Fallback scan of main description container
  const descContainer = document.querySelector("#product-description, .product-description, #desc-lazyload-container, .detail-desc-decorate-richtext");
  let descText = "";
  if (descContainer) {
    descText = descContainer.innerText.slice(0, 1500).trim();
  }

  return {
    title: title,
    price: price,
    images: Array.from(imageSet).slice(0, 10), // Keep top 10 images
    specs: specs.join("\n"),
    descriptionFallback: descText
  };
}
