import os
import sys
import json
import asyncio
import shutil
import urllib.parse
import urllib.request
import uuid
from datetime import datetime
from fastapi import FastAPI, BackgroundTasks, HTTPException, Query, Request
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv, set_key

# Add workspace directory to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.scraper import sanitize_filename
from src.ai_helper import (
    get_genai_client,
    generate_description_from_images,
    write_etsy_listing,
    generate_image_prompt_details,
    extract_visual_specs,
    extract_variation_specs
)
from src.image_gen import (
    DEFAULT_FAL_MODEL_KEY,
    FAL_IMAGE_MODELS,
    generate_image_with_imagen,
    resolve_fal_image_settings
)

# Load env variables initially
env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(dotenv_path=env_path)

def get_output_dir():
    # Read fresh from env
    load_dotenv(dotenv_path=env_path, override=True)
    out_dir = os.environ.get("OUTPUT_DIR")
    if not out_dir:
        out_dir = os.path.expanduser("~/Downloads/AliExpressQueue")
    os.makedirs(out_dir, exist_ok=True)
    return out_dir

app = FastAPI(title="Etsy Listings Automation API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Shared progress queue
class ProgressStreamer:
    def __init__(self):
        self.listeners = []

    def subscribe(self):
        queue = asyncio.Queue()
        self.listeners.append(queue)
        return queue

    def unsubscribe(self, queue):
        if queue in self.listeners:
            self.listeners.remove(queue)

    def publish(self, data):
        for queue in self.listeners:
            queue.put_nowait(data)

streamer = ProgressStreamer()

class ListingSaveRequest(BaseModel):
    title: str
    suggested_price: str
    description: str
    tags: list
    output_dir_name: str
    variation_images: list = None

class SettingsUpdateRequest(BaseModel):
    output_dir: str

@app.get("/api/settings")
def get_settings():
    return {"output_dir": get_output_dir()}

@app.post("/api/settings")
def update_settings(req: SettingsUpdateRequest):
    try:
        set_key(env_path, "OUTPUT_DIR", req.output_dir)
        load_dotenv(dotenv_path=env_path, override=True)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- LISTING PRESETS ---
LISTING_PRESETS_PATH = os.path.join(os.path.dirname(__file__), "..", "listing_presets.json")

DEFAULT_PRESETS = {
    "shop_intro": "",
    "shipping_note": "",
    "materials_disclaimer": "",
    "custom_prompt_rules": (
        "You are an expert e-commerce copywriter and Etsy SEO strategist specializing in premium boutique branding. Your task is to transform raw, clunky supplier specifications from AliExpress/manufacturers into a high-end, high-converting Etsy listing asset.\n"
        "--- CRITICAL COMPLIANCE RULES ---\n"
        "1. ABSOLUTE PROHIBITIONS: Never mention \"China\", \"AliExpress\", \"mass production\", \"factory\", \"bulk\", \"wholesale\", or \"shipping tracking variations\". Reframe everything around a \"curated, small-batch, premium boutique model\".\n"
        "2. TITLE RESTRICTIONS: Do not keyword-stuff titles or use pipe-separated keyword chains. Write one clear, natural buyer-friendly title under 140 characters and preferably under 15 words. Put the product noun and primary structural/material identifiers in the first 50-60 characters. Remove subjective words like \"perfect\", \"beautiful\", or \"unbelievable\".\n"
        "3. DESCRIPTION FORMATTING: Optimize for readability and scanning. Avoid large text walls. For all bulleted lists or technical attribute breakdowns, you must strictly use a literal hyphen (-) instead of bullet dots (•, *, or circle symbols). ABSOLUTELY NO MARKDOWN FORMATTING: Do not use asterisks (**) or underscores (_) to bold or italicize text, as Etsy does not support markdown. Use ALL CAPS for section headers instead. Ensure key traits like color, exact size, and materials appear clearly in the first two sentences.\n"
        "4. TITLE-TAG MATCH: Ensure the 2 or 3 most important keyword phrases in the Title exactly match 2 or 3 of the Tags.\n"
        "5. META DESCRIPTION: Make the first paragraph of the description exactly 1-2 sentences (under 160 characters), naturally weaving in the primary keywords for Google SEO.\n"
        "6. OCCASION TARGETING: If applicable, weave in 1 or 2 tags targeting gift intent (e.g., \"Gifts for Her\", \"Anniversary Gift\")."
    )
}

def load_listing_presets() -> dict:
    """Load listing presets from file, returning defaults if file does not exist."""
    if os.path.exists(LISTING_PRESETS_PATH):
        try:
            with open(LISTING_PRESETS_PATH, "r", encoding="utf-8") as f:
                return {**DEFAULT_PRESETS, **json.load(f)}
        except Exception:
            pass
    return dict(DEFAULT_PRESETS)

def format_listing_txt(listing: dict) -> str:
    """Build a readable listing export with optional cross-platform SEO fields."""
    tags = listing.get("tags", []) or []
    alt_text = listing.get("image_alt_text", []) or []
    seo_notes = listing.get("seo_qa_notes", []) or []
    strategy = listing.get("seo_strategy") or {}

    sections = [
        f"TITLE:\n{listing.get('title', '')}",
        f"PRICE:\n{listing.get('suggested_price', '')}",
        f"TAGS:\n{', '.join(tags)}",
        f"DESCRIPTION:\n{listing.get('description', '')}",
    ]

    seo_sections = []
    if listing.get("google_meta_title"):
        seo_sections.append(f"GOOGLE META TITLE:\n{listing.get('google_meta_title', '')}")
    if listing.get("google_meta_description"):
        seo_sections.append(f"GOOGLE META DESCRIPTION:\n{listing.get('google_meta_description', '')}")
    if listing.get("pinterest_title"):
        seo_sections.append(f"PINTEREST TITLE:\n{listing.get('pinterest_title', '')}")
    if listing.get("pinterest_description"):
        seo_sections.append(f"PINTEREST DESCRIPTION:\n{listing.get('pinterest_description', '')}")
    if alt_text:
        seo_sections.append("IMAGE ALT TEXT:\n" + "\n".join(f"- {item}" for item in alt_text))
    if listing.get("seo_quality_score") is not None:
        seo_sections.append(f"SEO QUALITY SCORE:\n{listing.get('seo_quality_score')}")
    if seo_notes:
        seo_sections.append("SEO QA NOTES:\n" + "\n".join(f"- {item}" for item in seo_notes))
    if strategy:
        seo_sections.append(
            "SEO STRATEGY:\n"
            + json.dumps(strategy, indent=2, ensure_ascii=False)
        )

    if seo_sections:
        sections.append("CROSS-PLATFORM SEO:\n" + "\n\n".join(seo_sections))

    return "\n\n".join(sections)

@app.get("/api/listing-presets")
def get_listing_presets():
    return load_listing_presets()

@app.post("/api/listing-presets")
def save_listing_presets(payload: dict):
    try:
        presets = {k: payload.get(k, "") for k in DEFAULT_PRESETS}
        with open(LISTING_PRESETS_PATH, "w", encoding="utf-8") as f:
            json.dump(presets, f, indent=4, ensure_ascii=False)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/themes")
def get_themes():
    try:
        themes = load_themes("themes.yaml")
        return {"themes": list(themes.keys()) if themes else []}
    except Exception as e:
        return {"themes": []}

@app.get("/api/status-stream")
async def status_stream():
    queue = streamer.subscribe()
    async def event_generator():
        try:
            while True:
                data = await queue.get()
                yield f"data: {json.dumps(data)}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            streamer.unsubscribe(queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")

# --- EXTENSION QUEUE ENDPOINT ---
class QueueProductRequest(BaseModel):
    title: str
    price: str
    specs: dict
    description_text: str
    main_images: list
    variation_images: list
    description_images: list

def download_image(url, dest_path):
    try:
        # Fix protocol-relative URLs
        if url.startswith("//"):
            url = "https:" + url
            
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as response:
            with open(dest_path, 'wb') as out_file:
                shutil.copyfileobj(response, out_file)
        return True
    except Exception as e:
        print(f"Failed to download {url}: {e}")
        return False

def background_queue_product(req_data: dict):
    try:
        title = req_data.get("title", "Untitled Product")
        slug = sanitize_filename(title)
        
        out_root = get_output_dir()
        product_dir = os.path.join(out_root, slug)
        
        dirs = {
            "main_images": os.path.join(product_dir, "main_images"),
            "variation_images": os.path.join(product_dir, "variation_images"),
            "description_images": os.path.join(product_dir, "description_images"),
        }
        for d in dirs.values():
            os.makedirs(d, exist_ok=True)
            
        streamer.publish({"status": "progress", "message": f"Downloading assets for: {title[:30]}..."})

        # Calculate total images to download
        main_list = req_data.get("main_images") or []
        var_list = req_data.get("variation_images") or []
        desc_list = req_data.get("description_images") or []
        total_assets = len(main_list) + len(var_list) + len(desc_list)
        downloaded_assets = 0

        # Save metadata immediately so it shows up in queue
        meta_path = os.path.join(product_dir, "metadata.json")
        metadata = {
            "title": title,
            "price": req_data.get("price", ""),
            "specs": req_data.get("specs", {}),
            "description_text": req_data.get("description_text", ""),
            "main_images": [],
            "variation_images": [],
            "description_images": [],
            "status": "downloading",
            "download_progress": f"0/{total_assets}"
        }
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=4, ensure_ascii=False)
        streamer.publish({"status": "queue_updated"})

        # Helper to update progress inside loop
        def report_progress():
            nonlocal downloaded_assets
            downloaded_assets += 1
            metadata["download_progress"] = f"{downloaded_assets}/{total_assets}"
            with open(meta_path, "w", encoding="utf-8") as fm:
                json.dump(metadata, fm, indent=4, ensure_ascii=False)
            streamer.publish({"status": "queue_updated"})

        # Download Main Images
        for idx, img_url in enumerate(main_list):
            ext = ".jpg"
            for possible_ext in [".png", ".jpeg", ".webp"]:
                if possible_ext in img_url.lower(): ext = possible_ext
            filename = f"main_{idx+1}{ext}"
            dest = os.path.join(dirs["main_images"], filename)
            if download_image(img_url, dest):
                metadata["main_images"].append(f"main_images/{filename}")
            report_progress()

        # Download Variation Images
        for idx, item in enumerate(var_list):
            alt_text = ""
            title_text = ""
            if isinstance(item, dict):
                img_url = item.get("url")
                alt_text = item.get("alt", "")
                title_text = item.get("title", "")
            else:
                img_url = item

            ext = ".jpg"
            for possible_ext in [".png", ".jpeg", ".webp"]:
                if possible_ext in img_url.lower(): ext = possible_ext
            filename = f"var_{idx+1}{ext}"
            dest = os.path.join(dirs["variation_images"], filename)
            if download_image(img_url, dest):
                metadata["variation_images"].append({
                    "local_path": f"variation_images/{filename}",
                    "url": img_url,
                    "alt": alt_text,
                    "title": title_text,
                    "detected_specs": None
                })
            report_progress()

        # Download Description Images
        for idx, img_url in enumerate(desc_list):
            ext = ".jpg"
            for possible_ext in [".png", ".jpeg", ".webp"]:
                if possible_ext in img_url.lower(): ext = possible_ext
            filename = f"desc_{idx+1}{ext}"
            dest = os.path.join(dirs["description_images"], filename)
            if download_image(img_url, dest):
                metadata["description_images"].append(f"description_images/{filename}")
            report_progress()

        # Save final metadata with local paths and update status to queued
        metadata["status"] = "queued"
        if "download_progress" in metadata:
            del metadata["download_progress"]
            
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=4, ensure_ascii=False)

        streamer.publish({"status": "progress", "message": f"Finished downloading: {title[:30]}"})
        # Broadcast final queue update
        streamer.publish({"status": "queue_updated"})


    except Exception as e:
        streamer.publish({"status": "error", "message": f"Queue error: {str(e)}"})

@app.post("/api/queue-product")
def queue_product(req: QueueProductRequest, background_tasks: BackgroundTasks):
    background_tasks.add_task(background_queue_product, req.model_dump())
    return {"status": "success", "message": "Product added to queue"}

# --- QUEUE MANAGEMENT ---
@app.get("/api/queue")
def list_queue():
    out_root = get_output_dir()
    products = []
    if not os.path.exists(out_root):
        return {"queue": []}
        
    for item in os.listdir(out_root):
        product_dir = os.path.join(out_root, item)
        if os.path.isdir(product_dir):
            meta_path = os.path.join(product_dir, "metadata.json")
            if os.path.exists(meta_path):
                try:
                    with open(meta_path, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                        meta["slug"] = item
                        # Assign thumbnail if available
                        thumb = None
                        if meta.get("main_images"):
                            thumb = meta["main_images"][0]
                        elif meta.get("variation_images"):
                            first_var = meta["variation_images"][0]
                            if isinstance(first_var, dict):
                                thumb = first_var.get("local_path")
                            else:
                                thumb = first_var
                        elif meta.get("description_images"):
                            thumb = meta["description_images"][0]
                            
                        # Set absolute path for serving static image in the dashboard
                        if thumb:
                            meta["thumbnail_path"] = f"/api/product-image/{item}/{urllib.parse.quote(thumb)}"
                        else:
                            meta["thumbnail_path"] = None
                            
                        products.append(meta)
                except Exception:
                    pass
    return {"queue": products}

@app.post("/api/delete-queue-item")
def delete_queue_item(payload: dict):
    slug = payload.get("slug")
    if not slug:
        raise HTTPException(status_code=400, detail="Missing slug")
    
    out_root = get_output_dir()
    product_dir = os.path.join(out_root, slug)
    if os.path.exists(product_dir) and os.path.isdir(product_dir):
        try:
            shutil.rmtree(product_dir)
            streamer.publish({"status": "queue_updated"})
            return {"status": "success", "message": "Product deleted successfully"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to delete product: {str(e)}")
    else:
        raise HTTPException(status_code=404, detail="Product not found")


@app.get("/api/product-image/{slug}/{image_path:path}")
def serve_product_image(slug: str, image_path: str):
    out_root = get_output_dir()
    file_path = os.path.join(out_root, slug, image_path)
    if os.path.exists(file_path):
        return FileResponse(file_path)
    raise HTTPException(status_code=404, detail="Image not found")


class ImageTaskConfig(BaseModel):
    task_type: str = "batch" # "batch" or "individual"
    target: str
    prompt: str = ""
    prompt_mode: str = "custom" # "preset" or "custom"
    prompt_preset: str = "auto_product_staging"
    model_key: str = "" # blank inherits ImageGenerationSettings.model_key
    thinking_level: str = "" # blank/inherit/off/minimal/high; only used by models that support it

class ImageGenerationSettings(BaseModel):
    model_key: str = DEFAULT_FAL_MODEL_KEY
    thinking_level: str = ""

class RunPipelineRequest(BaseModel):
    product_slug: str
    mode: str # "listing_only" | "listing_with_images" | "images_only"
    image_tasks: list[ImageTaskConfig] = []
    image_settings: ImageGenerationSettings = ImageGenerationSettings()

class ReferenceImageRequest(BaseModel):
    product_slug: str
    local_path: str
    source: str = ""

def normalize_product_image_path(product_dir: str, local_path: str):
    if not local_path:
        raise HTTPException(status_code=400, detail="Missing image path")

    clean_rel = local_path.replace("\\", "/").lstrip("/")
    allowed_prefixes = ("main_images/", "variation_images/", "description_images/")
    if not clean_rel.startswith(allowed_prefixes):
        raise HTTPException(status_code=400, detail="Reference image must come from downloaded product images")

    product_abs = os.path.abspath(product_dir)
    image_abs = os.path.abspath(os.path.join(product_abs, clean_rel))
    if os.path.commonpath([product_abs, image_abs]) != product_abs:
        raise HTTPException(status_code=400, detail="Invalid image path")
    if not os.path.exists(image_abs):
        raise HTTPException(status_code=404, detail="Reference image file not found")

    return clean_rel, image_abs

def get_image_local_path(image_entry):
    if isinstance(image_entry, dict):
        return image_entry.get("local_path") or image_entry.get("path") or image_entry.get("filename")
    return image_entry

def resolve_primary_reference_image(metadata: dict):
    primary = metadata.get("primary_reference_image")
    primary_path = get_image_local_path(primary)
    if primary_path:
        return {
            "local_path": primary_path,
            "source": primary.get("source", "manual") if isinstance(primary, dict) else "manual",
        }

    for source_key in ("main_images", "variation_images", "description_images"):
        images = metadata.get(source_key) or []
        if images:
            first_image = images[0]
            local_path = get_image_local_path(first_image)
            if local_path:
                return {
                    "local_path": local_path,
                    "source": source_key,
                    "selected_by": "fallback",
                }
    return None

DEFAULT_IMAGE_PROMPT_PRESET = "auto_product_staging"

IMAGE_PROMPT_PRESETS = {
    "auto_product_staging": {
        "label": "Adaptive Product Staging",
        "description": "Creates a polished marketplace-ready product scene with tasteful context.",
        "direction": (
            "Create a premium marketplace-ready product staging photograph for this {product_type}. "
            "Choose one believable placement from {scene}; make the product the clear hero and keep the styling simple, elevated, and commercially useful."
        ),
        "composition": (
            "Keep the full product clearly visible unless the reference itself is a detail angle. Use natural product scale, realistic contact shadows, "
            "clean edges, and a balanced composition where the product occupies roughly 60-75% of the frame. "
            "If it is a bag or accessory, place it on a bed, chair, vanity, shelf, cafe table, entryway bench, or daily-carry surface. "
            "If it is a kitchen tool, place it on a modern kitchen counter or prep surface. Avoid people, hands, mannequins, heavy props, and clutter unless the preset explicitly asks for them."
        ),
        "style": "premium Etsy and Shopify product photography, soft directional natural light, realistic materials, true-to-reference colors, uncluttered styling, sharp focus",
    },
    "auto_lifestyle_model": {
        "label": "Modeled By Someone",
        "description": "Shows the product worn, held, carried, or used by an appropriate person.",
        "direction": (
            "Create a realistic lifestyle image where the {product_type} is modeled or used by a {audience}. "
            "If the item is wearable, jewelry, clothing, a bag, or an accessory, show it naturally worn, held, or carried. "
            "If it is not wearable, show a person using it in a believable everyday scenario only when that helps explain the product."
        ),
        "composition": (
            "Keep the person secondary to the product. Prefer cropped hands, torso, or natural body framing over a face-forward portrait unless the product requires it. "
            "The product must remain easy to inspect, correctly scaled, and visibly faithful to the reference."
        ),
        "style": "natural commercial lifestyle photography, realistic skin tones, soft editorial lighting, authentic everyday setting",
    },
    "auto_in_use": {
        "label": "In Use",
        "description": "Shows the product actively being used in its most likely real-world context.",
        "direction": (
            "Create an in-use product photograph for this {product_type}. "
            "Show the product performing its intended function in {scene}."
        ),
        "composition": (
            "For a bag, show it carried, opened, packed, or set down during daily use. "
            "For a kitchen tool, show it during food preparation. "
            "For beauty, fitness, craft, office, home, or pet products, choose the matching everyday use context."
        ),
        "style": "realistic lifestyle product photography, candid but polished, natural light, practical scene details",
    },
    "clean_catalog": {
        "label": "Clean Catalog Hero",
        "description": "A simple ecommerce hero shot with better lighting and a clean background.",
        "direction": (
            "Create a clean ecommerce catalog hero image of this {product_type}. "
            "Center the product, keep the full silhouette visible, and make it easy to inspect at marketplace thumbnail size."
        ),
        "composition": "Use a simple premium off-white, warm gray, or soft neutral background, remove clutter, keep clean margins, and keep the product isolated as the hero subject.",
        "style": "square 1:1 sharp studio product photography, softbox lighting, crisp edges, true-to-reference color, high detail, consistent marketplace variation gallery",
    },
    "detail_closeup": {
        "label": "Detail Close-up",
        "description": "A closer product detail shot focused on texture, material, finish, or craftsmanship.",
        "direction": (
            "Create a close-up product detail image for this {product_type}. "
            "Emphasize the most important texture, material, finish, hardware, surface quality, or craftsmanship visible in the reference image."
        ),
        "composition": "Use a crop that feels intentional and premium while keeping enough of the product visible to understand what it is.",
        "style": "macro commercial product photography, crisp focus, tactile material detail, controlled highlights",
    },
    "gift_unboxing": {
        "label": "Gift / Unboxing",
        "description": "Show the product in a giftable unboxing or premium packaging scene.",
        "direction": (
            "Create a tasteful gift or unboxing scene for this {product_type}. "
            "Present it as a giftable item without hiding the product."
        ),
        "composition": "Use simple premium packaging, tissue paper, ribbon, box, or a clean tabletop arrangement, with packaging secondary to the product.",
        "style": "warm premium unboxing photography, clean tabletop styling, soft shadows, giftable ecommerce aesthetic",
    },
    "luxury_editorial_plinth": {
        "label": "Luxury Editorial Plinth",
        "description": "A high-end editorial product shot on a minimalist geometric plinth.",
        "direction": (
            "Create a high-end fashion editorial product photograph for this {product_type}. "
            "Place the product upright on a minimalist geometric limestone or stone plinth block when physically plausible."
        ),
        "composition": (
            "Adapt the camera angle to the uploaded reference image unless a side-profile view is clearly safe. "
            "Emphasize the product silhouette, slim structural form, edge lines, and authentic surface details."
        ),
        "style": (
            "neo-minimalist concrete interior, monolithic plaster wall, intersecting architectural angles, neutral taupe and raw sand-stone gray palette, "
            "intense direct cinematic afternoon side sunlight, hard-edged geometric shadow, 35mm lens, luxury brand aesthetic, sharp focus on edges"
        ),
    },
}

def infer_image_prompt_context(metadata: dict, visual_details: str = ""):
    title = metadata.get("title", "") or ""
    specs = metadata.get("specs", {}) or {}
    listing = metadata.get("etsy_listing", {}) or {}
    specs_text = " ".join([f"{k} {v}" for k, v in specs.items()])
    raw_text = " ".join([
        title,
        specs_text,
        metadata.get("description_text", "") or "",
        listing.get("title", "") or "",
        listing.get("category", "") or "",
        visual_details or "",
    ]).lower()

    product_type = "product"
    type_markers = [
        ("bag", ["bag", "purse", "tote", "handbag", "shoulder bag", "crossbody", "backpack", "wallet", "clutch"]),
        ("kitchen tool", ["kitchen", "cooking", "cookware", "utensil", "knife", "spatula", "pan", "baking", "food", "peeler", "grater"]),
        ("jewelry", ["jewelry", "necklace", "bracelet", "earring", "ring", "pendant", "charm"]),
        ("clothing", ["shirt", "dress", "hoodie", "jacket", "pants", "skirt", "sweater", "blouse", "wear", "apparel"]),
        ("shoe", ["shoe", "sneaker", "sandal", "boot", "heel", "slipper"]),
        ("home decor product", ["decor", "vase", "lamp", "rug", "pillow", "blanket", "wall art", "candle", "organizer"]),
        ("beauty product", ["makeup", "beauty", "cosmetic", "skincare", "brush", "mirror", "hair", "nail"]),
        ("office product", ["desk", "office", "stationery", "planner", "notebook", "pen", "keyboard"]),
        ("pet product", ["pet", "dog", "cat", "leash", "collar", "toy"]),
    ]
    for label, keywords in type_markers:
        if any(keyword in raw_text for keyword in keywords):
            product_type = label
            break

    audience = "adult model"
    if any(word in raw_text for word in ["women", "woman", "female", "lady", "ladies", "girl", "girls", "her"]):
        audience = "female adult model"
    elif any(word in raw_text for word in ["men", "man", "male", "gentleman", "boy", "boys", "his"]):
        audience = "male adult model"
    elif any(word in raw_text for word in ["baby", "toddler", "kid", "kids", "child", "children"]):
        audience = "family-friendly model or parent-assisted scene"

    scene = "a clean, realistic lifestyle setting"
    if product_type == "bag":
        scene = "a bedroom, boutique dressing area, cafe table, entryway bench, or everyday city setting"
    elif product_type == "kitchen tool":
        scene = "a bright modern kitchen with a clean counter, fresh ingredients, and natural light"
    elif product_type == "jewelry":
        scene = "a minimal dressing table, soft studio setting, or natural lifestyle portrait setup"
    elif product_type == "clothing":
        scene = "a natural lifestyle wardrobe, streetwear, studio, or home setting"
    elif product_type == "shoe":
        scene = "a clean lifestyle floor, entryway, streetwear setting, or studio setup"
    elif product_type == "home decor product":
        scene = "a styled living room, bedroom, shelf, table, or cozy home interior"
    elif product_type == "beauty product":
        scene = "a bathroom vanity, dressing table, soft studio, or beauty routine setup"
    elif product_type == "office product":
        scene = "a clean desk, workspace, planner setup, or modern office environment"
    elif product_type == "pet product":
        scene = "a clean home or outdoor pet lifestyle scene"

    return {
        "product_title": title or "the product",
        "product_type": product_type,
        "audience": audience,
        "scene": scene,
        "visual_details": visual_details or "the reference product details",
    }

def build_image_to_image_prompt(context: dict, direction: str, composition: str = "", style: str = "", custom_text: str = ""):
    def as_sentence(text: str):
        text = (text or "").strip()
        if not text:
            return ""
        return text if text.endswith((".", "!", "?")) else f"{text}."

    edit_direction = custom_text.strip() or "Create a premium product image using the selected creative direction."
    if direction:
        edit_direction = direction

    prompt_parts = [
        "Use the uploaded reference image as the source of truth.",
        (
            "Carefully preserve the exact product identity, original silhouette, material textures, colors, proportions, "
            "physical shapes, structural profile, and visible details from the reference image."
        ),
        f"Reference image analysis: {context.get('visual_details')}.",
        f"Product context: {context.get('product_title')} ({context.get('product_type')}).",
        f"Creative direction: {as_sentence(edit_direction)}",
    ]

    if composition:
        prompt_parts.append(f"Composition: {as_sentence(composition)}")
    if style:
        prompt_parts.append(f"Photography style: {as_sentence(style)}")

    prompt_parts.extend([
        (
            "Compose the final image as a square 1:1 product listing image with balanced margins on all sides."
        ),
        (
            "The final result should look like a finished Etsy or Shopify listing photo, not an AI concept render."
        ),
        (
            "Make the generated scene realistic with correct product scale, believable placement, natural perspective, "
            "contact shadows, and lighting that matches the new environment."
        ),
        (
            "Unless the creative direction explicitly requests a close-up, keep the product fully visible, sharply focused, and easy to inspect. "
            "Use simple tasteful styling and avoid crowded props, surreal environments, excessive blur, or overdramatic color grading."
        ),
        (
            "Do not redesign the product, do not change its colorway, do not add logos or decorations, "
            "do not add text overlays or watermarks, do not duplicate the product, and do not invent extra parts that are not visible or implied by the reference image."
        ),
    ])

    return " ".join(part for part in prompt_parts if part)

def resolve_image_task_prompt(task, metadata: dict, visual_details: str = ""):
    prompt_mode = task.get("prompt_mode", "custom") if isinstance(task, dict) else getattr(task, "prompt_mode", "custom")
    prompt_preset = task.get("prompt_preset", DEFAULT_IMAGE_PROMPT_PRESET) if isinstance(task, dict) else getattr(task, "prompt_preset", DEFAULT_IMAGE_PROMPT_PRESET)
    custom_prompt = task.get("prompt", "") if isinstance(task, dict) else getattr(task, "prompt", "")
    context = infer_image_prompt_context(metadata, visual_details)

    if prompt_mode == "preset":
        preset = IMAGE_PROMPT_PRESETS.get(prompt_preset, IMAGE_PROMPT_PRESETS[DEFAULT_IMAGE_PROMPT_PRESET])
        return build_image_to_image_prompt(
            context=context,
            direction=preset.get("direction", "").format(**context),
            composition=preset.get("composition", "").format(**context),
            style=preset.get("style", "").format(**context),
        )

    if custom_prompt:
        return build_image_to_image_prompt(
            context=context,
            direction="",
            custom_text=custom_prompt,
        )

    preset = IMAGE_PROMPT_PRESETS[DEFAULT_IMAGE_PROMPT_PRESET]
    return build_image_to_image_prompt(
        context=context,
        direction=preset.get("direction", "").format(**context),
        composition=preset.get("composition", "").format(**context),
        style=preset.get("style", "").format(**context),
    )

@app.get("/api/image-prompt-presets")
def get_image_prompt_presets():
    return {
        "default_prompt_preset": DEFAULT_IMAGE_PROMPT_PRESET,
        "presets": [
            {
                "key": key,
                "label": value["label"],
                "description": value["description"],
            }
            for key, value in IMAGE_PROMPT_PRESETS.items()
        ],
    }

@app.post("/api/set-reference-image")
def set_reference_image(req: ReferenceImageRequest):
    try:
        out_root = get_output_dir()
        product_dir = os.path.join(out_root, req.product_slug)
        meta_path = os.path.join(product_dir, "metadata.json")

        if not os.path.exists(meta_path):
            raise HTTPException(status_code=404, detail="Product not found")

        clean_rel, _ = normalize_product_image_path(product_dir, req.local_path)

        with open(meta_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)

        source = req.source or clean_rel.split("/", 1)[0]
        metadata["primary_reference_image"] = {
            "local_path": clean_rel,
            "source": source,
            "selected_by": "manual",
            "selected_at": datetime.now().isoformat(timespec="seconds"),
        }

        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=4, ensure_ascii=False)

        streamer.publish({"status": "queue_updated"})
        return {
            "status": "success",
            "primary_reference_image": metadata["primary_reference_image"],
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

def run_image_generation_tasks(metadata: dict, product_dir: str, image_tasks: list, image_settings: dict, client):
    selected_image_settings = resolve_fal_image_settings(
        (image_settings or {}).get("model_key")
    )
    global_thinking_level = (image_settings or {}).get("thinking_level", "")

    def normalize_thinking_level(value, settings):
        normalized = (value or "").strip().lower()
        if normalized in ("", "inherit", "off", "none", "disabled"):
            return ""
        if settings.get("supports_thinking") and normalized in settings.get("thinking_levels", []):
            return normalized
        return ""

    global_thinking_level = normalize_thinking_level(global_thinking_level, selected_image_settings)

    streamer.publish({
        "status": "progress",
        "message": "Executing image generation tasks..."
    })
    metadata["image_generation_settings"] = {
        "model_key": selected_image_settings["model_key"],
        "model": selected_image_settings["model"],
        "label": selected_image_settings["label"],
        "thinking_level": global_thinking_level,
        "task_overrides_enabled": True,
        "square_output": "1:1",
    }

    def get_task_value(task, key, default=None):
        if isinstance(task, dict):
            return task.get(key, default)
        return getattr(task, key, default)

    def resolve_task_image_settings(task):
        task_model_key = (get_task_value(task, "model_key", "") or "").strip()
        task_settings = resolve_fal_image_settings(task_model_key or selected_image_settings["model_key"])
        task_thinking = get_task_value(task, "thinking_level", "")
        if task_thinking in (None, "", "inherit"):
            task_thinking = global_thinking_level
        return task_settings, normalize_thinking_level(task_thinking, task_settings)

    def get_abs_path(rel_or_dict):
        local_path = get_image_local_path(rel_or_dict)
        if not local_path:
            return ""
        return os.path.join(product_dir, local_path)

    existing_generated_images = metadata.get("generated_images") or []
    if not isinstance(existing_generated_images, list):
        existing_generated_images = []
    generated_images = list(existing_generated_images)

    run_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    def build_generated_filename(target_folder: str, task, task_index: int, image_index: int):
        prompt_mode = task.get("prompt_mode", "custom") if isinstance(task, dict) else getattr(task, "prompt_mode", "custom")
        prompt_preset = task.get("prompt_preset", DEFAULT_IMAGE_PROMPT_PRESET) if isinstance(task, dict) else getattr(task, "prompt_preset", DEFAULT_IMAGE_PROMPT_PRESET)
        prompt_label = prompt_preset if prompt_mode == "preset" else "custom"
        unique_suffix = uuid.uuid4().hex[:8]
        base_name = sanitize_filename(
            f"gen_{target_folder}_{prompt_label}_{run_stamp}_t{task_index + 1}_i{image_index + 1}_{unique_suffix}"
        )
        return f"{base_name or f'gen_{run_stamp}_{unique_suffix}'}.png"

    for t_idx, task in enumerate(image_tasks):
        task_type = get_task_value(task, "task_type", "batch")
        target_folder = get_task_value(task, "target", "main_images")
        target_label = "selected reference image" if target_folder == "selected_reference" else target_folder
        task_image_settings, task_thinking_level = resolve_task_image_settings(task)

        target_images = []
        if target_folder == "selected_reference":
            selected_reference = resolve_primary_reference_image(metadata)
            if selected_reference:
                target_images = [selected_reference]
                if selected_reference.get("selected_by") == "fallback":
                    streamer.publish({
                        "status": "progress",
                        "message": "No manual reference selected; falling back to the first available product image.",
                    })
        elif task_type == "individual":
            if target_folder == "first_main" and metadata.get("main_images"):
                target_images = [metadata["main_images"][0]]
            elif target_folder == "first_variation" and metadata.get("variation_images"):
                target_images = [metadata["variation_images"][0]]
            elif target_folder == "first_description" and metadata.get("description_images"):
                target_images = [metadata["description_images"][0]]
        else:
            if target_folder == "first_main":
                if metadata.get("main_images"):
                    target_images = [metadata["main_images"][0]]
            else:
                target_images = metadata.get(target_folder, [])

        if not target_images:
            streamer.publish({"status": "progress", "message": f"Task {t_idx+1}: No images found in {target_label}, skipping."})
            continue

        thinking_note = f" ({task_thinking_level} thinking)" if task_thinking_level else ""
        streamer.publish({
            "status": "progress",
            "message": (
                f"Task {t_idx+1}: Generating {len(target_images)} images for {target_label} "
                f"with {task_image_settings['label']}{thinking_note}..."
            )
        })

        for img_idx, img_meta in enumerate(target_images):
            ref_path = get_abs_path(img_meta)
            if not os.path.exists(ref_path):
                streamer.publish({"status": "progress", "message": f"   -> Reference image missing, skipping item {img_idx+1}."})
                continue

            visual_details = generate_image_prompt_details(ref_path, client)
            prompt_style = resolve_image_task_prompt(task, metadata, visual_details)
            final_prompt = prompt_style

            out_filename = build_generated_filename(target_folder, task, t_idx, img_idx)
            out_path = os.path.join(product_dir, out_filename)

            streamer.publish({"status": "progress", "message": f"   -> Processing {img_idx+1}/{len(target_images)}..."})

            res_path = generate_image_with_imagen(
                prompt=final_prompt,
                output_path=out_path,
                client=client,
                reference_image=ref_path,
                fal_model_key=task_image_settings["model_key"],
                fal_thinking_level=task_thinking_level
            )

            if res_path:
                generated_images.append(out_filename)

    metadata["generated_images"] = generated_images
    return generated_images

def background_run_pipeline(slug: str, mode: str, image_tasks: list = None, image_settings: dict = None):
    try:
        out_root = get_output_dir()
        product_dir = os.path.join(out_root, slug)
        meta_path = os.path.join(product_dir, "metadata.json")
        
        if not os.path.exists(meta_path):
            raise Exception("Product metadata not found")
            
        with open(meta_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)
            
            metadata["status"] = "processing"
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=4, ensure_ascii=False)
            
        streamer.publish({"status": "queue_updated"})
        streamer.publish({"status": "progress", "message": f"Processing item: {metadata.get('title')[:30]}..."})

        client = get_genai_client()
        title = metadata.get("title", "")
        price = metadata.get("price", "")

        if mode == "images_only":
            if image_tasks:
                run_image_generation_tasks(metadata, product_dir, image_tasks, image_settings, client)
            else:
                streamer.publish({"status": "progress", "message": "AI Images Only selected, but no image tasks were configured."})

            metadata["status"] = "done"
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=4, ensure_ascii=False)

            streamer.publish({"status": "queue_updated"})
            streamer.publish({"status": "progress", "message": f"Successfully completed image generation: {title[:30]}"})
            return

        # --- PHASE 1: SMART VISUAL EXTRACTION (Or use cache) ---
        image_facts = metadata.get("image_facts")
        if image_facts is not None:
            streamer.publish({"status": "progress", "message": "Phase 1: Reusing cached image facts."})
        else:
            # Curate images to scan: description (up to 6), main (up to 3), variation (up to 2)
            desc_imgs = (metadata.get("description_images") or [])[:6]
            main_imgs = (metadata.get("main_images") or [])[:3]
            
            var_imgs = []
            for item in (metadata.get("variation_images") or [])[:2]:
                if isinstance(item, dict):
                    var_imgs.append(item.get("local_path"))
                else:
                    var_imgs.append(item)

            scan_targets_rel = desc_imgs + main_imgs + var_imgs
            scan_targets_abs = [os.path.join(product_dir, img_rel) for img_rel in scan_targets_rel if img_rel]
            
            if scan_targets_abs:
                streamer.publish({"status": "progress", "message": f"Phase 1: Scanning {len(scan_targets_abs)} product images for visual specs..."})
                try:
                    image_facts = extract_visual_specs(scan_targets_abs, client)
                    metadata["image_facts"] = image_facts
                    # Save progress intermediate
                    with open(meta_path, "w", encoding="utf-8") as f:
                        json.dump(metadata, f, indent=4, ensure_ascii=False)
                except Exception as ex:
                    print(f"Warning: Visual spec extraction failed: {ex}")
                    image_facts = {}
            else:
                image_facts = {}

        # Build description input
        specs_text = "\n".join([f"{k}: {v}" for k, v in metadata.get("specs", {}).items()])
        desc_input = metadata.get("description_text", "")
        if specs_text:
            desc_input = specs_text + "\n\n" + desc_input

        # Fallback to visual scanning ONLY if there is absolutely no text at all
        if not desc_input or len(desc_input.strip()) < 50:
            local_imgs = []
            for m in metadata.get("main_images", [])[:3]:
                local_imgs.append(os.path.join(product_dir, m))
            if local_imgs:
                streamer.publish({"status": "progress", "message": "No text description found. Fallback: visual description scan..."})
                desc_input = generate_description_from_images(local_imgs, client)
            else:
                desc_input = "Generic product details."

        # --- PHASE 1b: VARIATION SPECIFIC EXTRACTION ---
        variation_specs = metadata.get("variation_specs")
        if variation_specs is not None:
            streamer.publish({"status": "progress", "message": "Phase 1b: Reusing cached variation specs."})
        else:
            var_items = metadata.get("variation_images") or []
            if var_items:
                streamer.publish({"status": "progress", "message": f"Phase 1b: Scanning {len(var_items)} variations for sizes & dimensions..."})
                try:
                    variation_specs = extract_variation_specs(
                        variations=var_items,
                        product_dir=product_dir,
                        overall_specs=image_facts,
                        scraped_desc=desc_input,
                        client=client
                    )
                    metadata["variation_specs"] = variation_specs
                    
                    # Update each variation image's detected_specs as well
                    for item, spec in zip(metadata["variation_images"], variation_specs):
                        if isinstance(item, dict):
                            item["detected_specs"] = spec
                    
                    with open(meta_path, "w", encoding="utf-8") as f:
                        json.dump(metadata, f, indent=4, ensure_ascii=False)
                except Exception as ex:
                    print(f"Warning: Variation spec extraction failed: {ex}")
                    variation_specs = []
            else:
                variation_specs = []

        # --- PHASE 2 & 3: COPYWRITING & SELF-REVIEW ---
        streamer.publish({"status": "progress", "message": "Phase 2: Generating enriched copywriting & running Phase 3 self-critique..."})
        presets = load_listing_presets()
        
        etsy_listing = write_etsy_listing(
            title=title, 
            description=desc_input, 
            price=price, 
            client=client, 
            presets=presets, 
            image_facts=image_facts,
            variation_specs=variation_specs
        )
        
        if not etsy_listing:
            raise Exception("Copywriting generation failed.")

        # Save etsy listing info to metadata
        metadata["etsy_listing"] = etsy_listing

        # Image generation if requested
        if mode == "listing_with_images" and image_tasks:
            run_image_generation_tasks(metadata, product_dir, image_tasks, image_settings, client)

        metadata["status"] = "done"
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=4, ensure_ascii=False)

        # Write human-readable listing.txt alongside metadata.json
        try:
            listing_txt_path = os.path.join(product_dir, "listing.txt")
            listing_txt_content = format_listing_txt(etsy_listing)
            with open(listing_txt_path, "w", encoding="utf-8") as f:
                f.write(listing_txt_content)
        except Exception as txt_err:
            print(f"Warning: Could not write listing.txt: {txt_err}")

        streamer.publish({"status": "queue_updated"})
        streamer.publish({"status": "progress", "message": f"Successfully completed: {title[:30]}"})

    except Exception as e:
        # Mark as failed
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                metadata = json.load(f)
            metadata["status"] = "failed"
            metadata["error"] = str(e)
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=4, ensure_ascii=False)
            streamer.publish({"status": "queue_updated"})
        except Exception:
            pass
        streamer.publish({"status": "error", "message": f"Pipeline error: {str(e)}"})

@app.post("/api/run-pipeline")
def run_pipeline_api(req: RunPipelineRequest, background_tasks: BackgroundTasks):
    image_settings = req.image_settings.model_dump() if req.image_settings else {}
    background_tasks.add_task(background_run_pipeline, req.product_slug, req.mode, req.image_tasks, image_settings)
    return {"status": "success", "message": "Pipeline execution started"}

class ExportZipRequest(BaseModel):
    product_slugs: list

@app.post("/api/export-zip")
def export_zip(req: ExportZipRequest):
    try:
        out_root = get_output_dir()
        if not req.product_slugs:
            raise HTTPException(status_code=400, detail="No products selected")
            
        if len(req.product_slugs) == 1:
            slug = req.product_slugs[0]
            product_dir = os.path.join(out_root, slug)
            if not os.path.exists(product_dir):
                raise HTTPException(status_code=404, detail="Product not found")
            zip_path = os.path.join(out_root, f"{slug}.zip")
            shutil.make_archive(zip_path[:-4], 'zip', product_dir)
            return FileResponse(zip_path, media_type='application/zip', filename=f"{slug}.zip")
        else:
            import tempfile
            temp_dir = tempfile.mkdtemp()
            export_dir = os.path.join(temp_dir, "AliExpress_Export")
            os.makedirs(export_dir)
            for slug in req.product_slugs:
                src = os.path.join(out_root, slug)
                if os.path.exists(src):
                    shutil.copytree(src, os.path.join(export_dir, slug))
                    
            zip_path = os.path.join(out_root, "AliExpress_Batch_Export.zip")
            shutil.make_archive(zip_path[:-4], 'zip', export_dir)
            shutil.rmtree(temp_dir)
            return FileResponse(zip_path, media_type='application/zip', filename="AliExpress_Batch_Export.zip")
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/save-listing")
def save_listing(req: ListingSaveRequest):
    try:
        out_root = get_output_dir()
        product_dir = os.path.join(out_root, req.output_dir_name)
        meta_path = os.path.join(product_dir, "metadata.json")
        
        if not os.path.exists(meta_path):
            raise HTTPException(status_code=404, detail="Product not found")
            
        with open(meta_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)
            
        # Update listing details
        if "etsy_listing" not in metadata:
            metadata["etsy_listing"] = {}
            
        metadata["etsy_listing"]["title"] = req.title
        metadata["etsy_listing"]["suggested_price"] = req.suggested_price
        metadata["etsy_listing"]["description"] = req.description
        metadata["etsy_listing"]["tags"] = req.tags
        
        # Also update variation_images if provided in request
        if req.variation_images is not None:
            metadata["variation_images"] = req.variation_images
            
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=4, ensure_ascii=False)
            
        # Also update human-readable listing.txt
        try:
            listing_txt_path = os.path.join(product_dir, "listing.txt")
            listing_txt_content = format_listing_txt(metadata["etsy_listing"])
            with open(listing_txt_path, "w", encoding="utf-8") as f:
                f.write(listing_txt_content)
        except Exception as txt_err:
            print(f"Warning: Could not write listing.txt on save: {txt_err}")
            
        streamer.publish({"status": "queue_updated"})
        return {"status": "success", "message": "Listing saved successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

GENERATION_PRESETS_FILE = os.path.join(os.path.dirname(__file__), "..", "pipeline_presets.json")

class GenerationPreset(BaseModel):
    name: str
    mode: str
    image_tasks: list[ImageTaskConfig]
    image_settings: ImageGenerationSettings = ImageGenerationSettings()

@app.get("/api/image-generation-options")
def get_image_generation_options():
    return {
        "default_model_key": DEFAULT_FAL_MODEL_KEY,
        "models": [
            {
                "key": key,
                "label": config["label"],
                "model": config["model"],
                "supports_thinking": config.get("supports_thinking", False),
                "thinking_levels": config.get("thinking_levels", []),
                "description": config.get("description", ""),
                "recommended_for": config.get("recommended_for", ""),
            }
            for key, config in FAL_IMAGE_MODELS.items()
        ],
        "thinking_levels": [
            {
                "key": "off",
                "label": "Off",
                "description": "Do not send a thinking parameter."
            },
            {
                "key": "minimal",
                "label": "Minimal",
                "description": "Light reasoning for smarter edits at nearly the same cost."
            },
            {
                "key": "high",
                "label": "High",
                "description": "Best for hero/showcase edits where product accuracy matters most."
            },
        ],
    }

@app.get("/api/generation-presets")
def get_generation_presets():
    if os.path.exists(GENERATION_PRESETS_FILE):
        with open(GENERATION_PRESETS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

@app.post("/api/generation-presets")
def save_generation_preset(preset: GenerationPreset):
    presets = {}
    if os.path.exists(GENERATION_PRESETS_FILE):
        with open(GENERATION_PRESETS_FILE, "r", encoding="utf-8") as f:
            try:
                presets = json.load(f)
            except json.JSONDecodeError:
                pass
    presets[preset.name] = {
        "mode": preset.mode,
        "image_tasks": [t.model_dump() if hasattr(t, "model_dump") else t.dict() for t in preset.image_tasks],
        "image_settings": preset.image_settings.model_dump()
    }
    with open(GENERATION_PRESETS_FILE, "w", encoding="utf-8") as f:
        json.dump(presets, f, indent=4)
    return {"status": "success"}

class DeletePresetRequest(BaseModel):
    name: str

@app.post("/api/generation-presets/delete")
def delete_generation_preset(req: DeletePresetRequest):
    presets = {}
    if os.path.exists(GENERATION_PRESETS_FILE):
        with open(GENERATION_PRESETS_FILE, "r", encoding="utf-8") as f:
            try:
                presets = json.load(f)
            except json.JSONDecodeError:
                pass
    if req.name in presets:
        del presets[req.name]
        with open(GENERATION_PRESETS_FILE, "w", encoding="utf-8") as f:
            json.dump(presets, f, indent=4)
    return {"status": "success"}

# Mount web static directory
static_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
