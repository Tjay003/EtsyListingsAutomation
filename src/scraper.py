import os
import re
import urllib.parse
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

def sanitize_filename(name):
    """Sanitize title to be used as directory/file name."""
    return re.sub(r'[\\/*?:"<>|]', "", name).replace(" ", "_")[:50]

def download_image(url, folder, filename):
    """Download image from URL to local folder."""
    if not url:
        return None
    # Ensure URL is absolute
    if url.startswith("//"):
        url = "https:" + url
    elif not url.startswith("http"):
        url = "https://" + url
        
    try:
        response = requests.get(url, timeout=15)
        if response.status_code == 200:
            os.makedirs(folder, exist_ok=True)
            filepath = os.path.join(folder, filename)
            with open(filepath, "wb") as f:
                f.write(response.content)
            print(f"Downloaded: {filepath}")
            return filepath
    except Exception as e:
        print(f"Failed to download image {url}: {e}")
    return None

def scrape_aliexpress(url, input_dir="inputs", headless=True):
    """Scrape product info and images from AliExpress using Playwright."""
    print(f"Starting AliExpress scraping for: {url} (headless={headless})")
    
    scraped_data = {
        "title": "",
        "price": "",
        "description_text": "",
        "image_paths": []
    }
    
    # Pre-create a temporary folder for debug screenshots and downloads
    temp_folder = os.path.join(input_dir, "aliexpress_scraped_temp")
    os.makedirs(temp_folder, exist_ok=True)
    
    with sync_playwright() as p:
        # Launch browser with custom arguments to bypass simple bot detection
        browser = p.chromium.launch(headless=headless, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"}
        )
        page = context.new_page()
        
        try:
            # Load page
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(4000) # Wait for client rendering
            
            # Check for Captcha / Robot Check
            content_lower = page.content().lower()
            if "robot" in content_lower or "captcha" in content_lower or page.query_selector("iframe[src*='recaptcha']") or page.query_selector("iframe[src*='captcha']"):
                if headless:
                    print("\n[WARNING] AliExpress robot check (CAPTCHA) detected!")
                    print("Please run the script with the '--headed' flag so you can solve it manually in the browser window.\n")
                else:
                    print("\n[REQUIRED] AliExpress CAPTCHA detected!")
                    print("Please solve the captcha in the browser window, then press ENTER in this terminal console to resume...\n")
                    input("Press Enter here after solving the captcha in the browser...")
                    page.wait_for_timeout(2000) # Wait for page state to update
            
            
            # 1. Parse OpenGraph Meta Tags (Super resilient, loaded in the HTML header)
            meta_title = page.query_selector("meta[property='og:title']")
            meta_desc = page.query_selector("meta[property='og:description']")
            meta_image = page.query_selector("meta[property='og:image']")
            
            if meta_title:
                scraped_data["title"] = meta_title.get_attribute("content").strip()
            if meta_desc:
                scraped_data["description_text"] = meta_desc.get_attribute("content").strip()
            
            # If og tags failed, use body selectors
            if not scraped_data["title"]:
                title_element = page.query_selector("h1")
                if title_element:
                    scraped_data["title"] = title_element.inner_text().strip()
                else:
                    scraped_data["title"] = page.title().split("-")[0].strip()
            
            # Create the final target folder based on the extracted title
            folder_name = sanitize_filename(scraped_data["title"] or "aliexpress_product")
            product_input_dir = os.path.join(input_dir, folder_name)
            os.makedirs(product_input_dir, exist_ok=True)
            
            # Save debug screenshot to see what Playwright loaded (useful for debugging captchas)
            screenshot_path = os.path.join(product_input_dir, "debug_screenshot.png")
            page.screenshot(path=screenshot_path)
            print(f"Captured browser state screenshot at: {screenshot_path}")
            
            # Extract Price
            price_element = page.query_selector("[class*='price-current'], [class*='product-price'], span[class*='price']")
            if price_element:
                scraped_data["price"] = price_element.inner_text().strip()
            else:
                meta_price = page.query_selector("meta[property='og:price:amount']")
                if meta_price:
                    scraped_data["price"] = meta_price.get_attribute("content").strip()
            
            # Extract Description Text (if body description is present and longer than meta-desc)
            desc_element = page.query_selector("#product-description, [class*='description-content'], [class*='product-detail']")
            if desc_element:
                body_desc = desc_element.inner_text().strip()
                if len(body_desc) > len(scraped_data["description_text"]):
                    scraped_data["description_text"] = body_desc
            
            # Extract Image URLs
            image_urls = []
            
            # Try OpenGraph image first
            if meta_image:
                og_img_url = meta_image.get_attribute("content")
                if og_img_url:
                    image_urls.append(og_img_url)
            
            # Strategy A: Check main gallery/slider elements
            img_elements = page.query_selector_all(".image-view-magnifier-wrap img, .slider--img img, [class*='slider'] img, [class*='gallery'] img, .magnifier-image, .detail-gallery img")
            for img in img_elements:
                src = img.get_attribute("src") or img.get_attribute("data-src")
                if src:
                    # Clean zoom suffixes like _50x50.jpg or _640x640.jpg to get original size
                    clean_url = re.sub(r'_\d+x\d+\.(jpg|png|webp).*$', '', src)
                    if clean_url not in image_urls:
                        image_urls.append(clean_url)
            
            # Strategy B: Fallback - look for large images in source
            all_imgs = page.query_selector_all("img")
            for img in all_imgs:
                src = img.get_attribute("src") or img.get_attribute("data-src")
                if src and ("alicdn.com" in src or "ae01" in src) and ("_80x80" not in src and "_50x50" not in src):
                    clean_url = re.sub(r'_\d+x\d+\.(jpg|png|webp).*$', '', src)
                    if clean_url not in image_urls:
                        image_urls.append(clean_url)
            
            # Download the top images (limit to 6)
            image_urls = image_urls[:6]
            print(f"Found {len(image_urls)} potential images. Downloading...")
            
            for idx, img_url in enumerate(image_urls):
                filename = f"product_img_{idx + 1}.png"
                local_path = download_image(img_url, product_input_dir, filename)
                if local_path:
                    scraped_data["image_paths"].append(local_path)
            
        except Exception as e:
            print(f"Error during Playwright execution: {e}")
        finally:
            browser.close()
            
    # Clean up empty temp folder
    try:
        if os.path.exists(temp_folder) and not os.listdir(temp_folder):
            os.rmdir(temp_folder)
    except:
        pass
        
    return scraped_data

def parse_aliexpress_html(html_path, input_dir="inputs"):
    """Parse product info and download images from a local AliExpress HTML file."""
    print(f"Parsing local AliExpress HTML file: {html_path}")
    
    scraped_data = {
        "title": "",
        "price": "",
        "description_text": "",
        "image_paths": []
    }
    
    if not os.path.exists(html_path):
        print(f"ERROR: Local HTML file not found at {html_path}")
        return scraped_data
        
    with open(html_path, "r", encoding="utf-8", errors="ignore") as f:
        html_content = f.read()
        
    soup = BeautifulSoup(html_content, "html.parser")
    
    # 1. Title Extraction
    meta_title = soup.find("meta", property="og:title")
    if meta_title and meta_title.get("content"):
        scraped_data["title"] = meta_title.get("content").strip()
    else:
        # Fallback body title selector
        title_el = soup.find("h1")
        if title_el:
            scraped_data["title"] = title_el.get_text().strip()
        else:
            # Check title tag
            html_title = soup.find("title")
            if html_title:
                scraped_data["title"] = html_title.get_text().split("-")[0].strip()
                
    if not scraped_data["title"]:
        scraped_data["title"] = "aliexpress_product"
        
    print(f"Extracted Title from HTML: {scraped_data['title']}")
    
    # Create output directory
    folder_name = sanitize_filename(scraped_data["title"])
    product_input_dir = os.path.join(input_dir, folder_name)
    os.makedirs(product_input_dir, exist_ok=True)
    
    # 2. Price Extraction
    meta_price = soup.find("meta", property="og:price:amount")
    if meta_price and meta_price.get("content"):
        scraped_data["price"] = meta_price.get("content").strip()
    else:
        price_el = soup.select_one("[class*='price-current'], [class*='product-price'], span[class*='price']")
        if price_el:
            scraped_data["price"] = price_el.get_text().strip()
            
    # 3. Description Extraction
    meta_desc = soup.find("meta", property="og:description")
    if meta_desc and meta_desc.get("content"):
        scraped_data["description_text"] = meta_desc.get("content").strip()
        
    desc_el = soup.select_one("#product-description, [class*='description-content'], [class*='product-detail']")
    if desc_el:
        body_desc = desc_el.get_text().strip()
        if len(body_desc) > len(scraped_data["description_text"]):
            scraped_data["description_text"] = body_desc
            
    # 4. Image URLs Extraction (Smart Reconstruction for Local/Live paths)
    image_urls = []
    
    # Try OpenGraph image first
    meta_img = soup.find("meta", property="og:image")
    if meta_img and meta_img.get("content"):
        image_urls.append(meta_img.get("content"))
        
    html_dir = os.path.dirname(html_path)
    
    # Extract images from main body (skipping header, footer, recommendations)
    pdp_container = soup.select_one(".pdp-page-wrap, #root, body")
    target_elements = []
    if pdp_container:
        for img in pdp_container.find_all("img"):
            # Check parents classes to see if it's header/footer/related items
            parent_str = ""
            curr = img.parent
            while curr and curr.name != "[document]":
                if curr.get('class'):
                    parent_str += " " + " ".join(curr.get('class'))
                curr = curr.parent
            
            # Filter out category dropdowns, related recommendations, choices banners, and footer copywrites
            if any(x in parent_str for x in ["Categoey", "category--", "search--", "slider-card", "card-out-wrapper", "footer", "choice-mind"]):
                continue
            target_elements.append(img)
    else:
        target_elements = soup.find_all("img")
        
    for img in target_elements:
        src = img.get("src") or img.get("data-src") or img.get("lazy-src")
        if not src:
            continue
            
        clean_url = None
        # Case A: Live CDN URL
        if "alicdn.com" in src or "ae01" in src:
            clean_url = re.sub(r'_\d+x\d+.*$', '', src)
        # Case B: Local path
        elif "_files/" in src or "bag_files/" in src or src.startswith("./"):
            filename = os.path.basename(src)
            match = re.search(r'(S[a-zA-Z0-9]{30,35})', filename)
            if match:
                key = match.group(1)
                clean_url = f"https://ae01.alicdn.com/kf/{key}.jpg"
            else:
                local_full_path = os.path.join(html_dir, src.lstrip("./"))
                if os.path.exists(local_full_path):
                    clean_url = local_full_path
                    
        if clean_url and clean_url not in image_urls:
            image_urls.append(clean_url)
            
    # 5. Extract additional images and text from local Description Iframes (e.g. saved_resource.html inside bag_files/)
    for iframe in soup.find_all("iframe"):
        iframe_src = iframe.get("src")
        if iframe_src and ("_files/" in iframe_src or "bag_files/" in iframe_src or iframe_src.startswith("./")):
            iframe_path = os.path.join(html_dir, iframe_src.lstrip("./"))
            if os.path.exists(iframe_path):
                print(f"Found local description iframe: {iframe_path}")
                try:
                    with open(iframe_path, "r", encoding="utf-8", errors="ignore") as f_iframe:
                        iframe_soup = BeautifulSoup(f_iframe.read(), "html.parser")
                        
                        # Extract description text
                        iframe_text = iframe_soup.get_text().strip()
                        if iframe_text:
                            iframe_text_clean = re.sub(r'\n+', '\n', iframe_text)
                            scraped_data["description_text"] += "\n" + iframe_text_clean
                            
                        # Extract images
                        for img in iframe_soup.find_all("img"):
                            src = img.get("src") or img.get("data-src") or img.get("lazy-src")
                            if src:
                                clean_url = None
                                if "alicdn.com" in src or "ae01" in src:
                                    clean_url = re.sub(r'_\d+x\d+.*$', '', src)
                                elif "_files/" in src or "bag_files/" in src or src.startswith("./"):
                                    filename = os.path.basename(src)
                                    match = re.search(r'(S[a-zA-Z0-9]{30,35})', filename)
                                    if match:
                                        key = match.group(1)
                                        clean_url = f"https://ae01.alicdn.com/kf/{key}.jpg"
                                    else:
                                        local_img_path = os.path.join(os.path.dirname(iframe_path), src.lstrip("./"))
                                        if os.path.exists(local_img_path):
                                            clean_url = local_img_path
                                if clean_url and clean_url not in image_urls:
                                    image_urls.append(clean_url)
                except Exception as e:
                    print(f"Error parsing iframe {iframe_path}: {e}")
                    
    # Download top 15 images (captures both gallery and detailed description images)
    image_urls = image_urls[:15]
    print(f"Found {len(image_urls)} potential images in HTML. Downloading/Processing...")
    for idx, img_url in enumerate(image_urls):
        filename = f"product_img_{idx + 1}.png"
        
        # If it's a local file already on disk, copy it
        if os.path.isabs(img_url) or (img_url.startswith("C:") or img_url.startswith("/")) and os.path.exists(img_url):
            import shutil
            dest_path = os.path.join(product_input_dir, filename)
            try:
                shutil.copy2(img_url, dest_path)
                scraped_data["image_paths"].append(dest_path)
                print(f"Copied local image: {dest_path}")
            except Exception as e:
                print(f"Failed to copy local image {img_url}: {e}")
        else:
            # Download live CDN URL
            local_path = download_image(img_url, product_input_dir, filename)
            if local_path:
                scraped_data["image_paths"].append(local_path)
            
    return scraped_data
