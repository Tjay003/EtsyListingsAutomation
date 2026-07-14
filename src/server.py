import os
import sys
import json
import asyncio
import logging
import re
import shutil
import threading
import urllib.parse
import urllib.request
import uuid
from datetime import datetime
from logging.handlers import RotatingFileHandler
from fastapi import FastAPI, BackgroundTasks, Depends, Header, HTTPException, Query, Request
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
    tweak_etsy_listing,
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

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LOG_DIR = os.path.join(PROJECT_ROOT, "logs")
os.makedirs(LOG_DIR, exist_ok=True)

pipeline_logger = logging.getLogger("etsy_pipeline")
pipeline_logger.setLevel(logging.INFO)
pipeline_logger.propagate = False

if not pipeline_logger.handlers:
    log_handler = RotatingFileHandler(
        os.path.join(LOG_DIR, "pipeline.log"),
        maxBytes=2_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    log_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    pipeline_logger.addHandler(log_handler)

def summarize_stream_event(data: dict) -> dict:
    if not isinstance(data, dict):
        return {"event": str(data)}

    summary = {
        "status": data.get("status"),
        "title": data.get("title"),
        "message": data.get("message"),
        "slug": data.get("slug") or data.get("output_dir_name"),
    }
    if "generated_images" in data:
        generated_images = data.get("generated_images") or []
        summary["generated_images"] = len(generated_images) if isinstance(generated_images, list) else "present"
    if "listing" in data:
        summary["listing"] = "present" if data.get("listing") else "empty"
    return {key: value for key, value in summary.items() if value not in (None, "")}

def sanitize_user_token(token: str | None = None) -> str:
    sanitized = re.sub(r"[^a-zA-Z0-9_-]", "", token or "")[:64]
    return sanitized or "default"

def get_user_token(
    x_user_token: str | None = Header(default=None),
    token: str | None = Query(default=None),
) -> str:
    return sanitize_user_token(x_user_token or token)

def get_output_base_dir() -> str:
    # Read fresh from env
    load_dotenv(dotenv_path=env_path, override=True)
    out_dir = os.environ.get("OUTPUT_DIR")
    if not out_dir:
        out_dir = os.path.expanduser("~/Downloads/AliExpressQueue")
    os.makedirs(out_dir, exist_ok=True)
    return out_dir

def get_output_dir(user_token: str = "default") -> str:
    out_dir = os.path.join(get_output_base_dir(), sanitize_user_token(user_token))
    os.makedirs(out_dir, exist_ok=True)
    return out_dir

def is_hosted_mode() -> bool:
    load_dotenv(dotenv_path=env_path, override=True)
    return os.environ.get("HOSTED_MODE", "").strip().lower() in {"1", "true", "yes", "on"}

def resolve_user_path(user_token: str, *parts: str) -> str:
    root = os.path.abspath(get_output_dir(user_token))
    target = os.path.abspath(os.path.join(root, *parts))
    try:
        if os.path.commonpath([root, target]) != root:
            raise ValueError
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path")
    return target

def resolve_product_dir(user_token: str, slug: str) -> str:
    if not slug or slug in {".", ".."} or "/" in slug or "\\" in slug:
        raise HTTPException(status_code=400, detail="Invalid product slug")
    return resolve_user_path(user_token, slug)

def resolve_product_path(user_token: str, slug: str, *parts: str) -> str:
    product_dir = os.path.abspath(resolve_product_dir(user_token, slug))
    target = os.path.abspath(os.path.join(product_dir, *parts))
    try:
        if os.path.commonpath([product_dir, target]) != product_dir:
            raise ValueError
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path")
    return target

def build_product_image_url(slug: str, image_path: str, user_token: str) -> str:
    slug_part = urllib.parse.quote(slug, safe="")
    image_part = urllib.parse.quote(image_path, safe="/")
    token_part = urllib.parse.quote(sanitize_user_token(user_token), safe="")
    return f"/api/product-image/{slug_part}/{image_part}?token={token_part}"

class PipelineCancelled(Exception):
    pass

pipeline_cancel_requests = set()
pipeline_cancel_lock = threading.Lock()

def pipeline_cancel_key(user_token: str, slug: str) -> str:
    return f"{sanitize_user_token(user_token)}:{slug}"

def request_pipeline_cancel(user_token: str, slug: str):
    with pipeline_cancel_lock:
        pipeline_cancel_requests.add(pipeline_cancel_key(user_token, slug))

def clear_pipeline_cancel(user_token: str, slug: str):
    with pipeline_cancel_lock:
        pipeline_cancel_requests.discard(pipeline_cancel_key(user_token, slug))

def is_pipeline_cancel_requested(user_token: str, slug: str) -> bool:
    with pipeline_cancel_lock:
        return pipeline_cancel_key(user_token, slug) in pipeline_cancel_requests

def check_pipeline_cancelled(user_token: str, slug: str):
    if is_pipeline_cancel_requested(user_token, slug):
        raise PipelineCancelled("Pipeline cancelled by user")

def mark_pipeline_cancelled(user_token: str, slug: str, meta_path: str, metadata: dict | None = None):
    if metadata is None:
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                metadata = json.load(f)
        except Exception:
            metadata = {}
    metadata["status"] = "cancelled"
    metadata["cancel_requested"] = False
    metadata["cancelled_at"] = datetime.now().isoformat(timespec="seconds")
    metadata["error"] = "Pipeline cancelled by user"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=4, ensure_ascii=False)
    streamer.publish({"status": "queue_updated"}, user_token)
    streamer.publish({
        "status": "cancelled",
        "title": "Pipeline Cancelled",
        "message": f"Stopped processing {metadata.get('title', slug)[:60]}.",
        "slug": slug,
    }, user_token)

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
        self.listeners = {}

    def subscribe(self, user_token: str = "default"):
        queue = asyncio.Queue()
        token = sanitize_user_token(user_token)
        self.listeners.setdefault(token, []).append(queue)
        return queue

    def unsubscribe(self, queue, user_token: str = "default"):
        token = sanitize_user_token(user_token)
        listeners = self.listeners.get(token, [])
        if queue in listeners:
            listeners.remove(queue)
        if not listeners and token in self.listeners:
            del self.listeners[token]

    def publish(self, data, user_token: str = "default"):
        token = sanitize_user_token(user_token)
        try:
            pipeline_logger.info(
                "[%s] %s",
                token,
                json.dumps(summarize_stream_event(data), ensure_ascii=False),
            )
        except Exception:
            pass
        for queue in list(self.listeners.get(token, [])):
            queue.put_nowait(data)

streamer = ProgressStreamer()

class ListingSaveRequest(BaseModel):
    title: str
    category: str = ""
    suggested_price: str
    description: str
    tags: list
    output_dir_name: str
    variation_images: list = None

class ListingTweakRequest(BaseModel):
    output_dir_name: str
    preset_key: str = "custom"
    instruction: str = ""
    fields: list | None = None
    context_mode: str = "existing_output"
    current_listing: dict | None = None

class SettingsUpdateRequest(BaseModel):
    output_dir: str

@app.get("/api/settings")
def get_settings():
    return {"output_dir": get_output_base_dir(), "hosted_mode": is_hosted_mode()}

@app.post("/api/settings")
def update_settings(req: SettingsUpdateRequest):
    if is_hosted_mode():
        raise HTTPException(status_code=403, detail="Output directory is locked in hosted mode")
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
        "--- COPYWRITING AND COMPLIANCE RULES ---\n"
        "1. ABSOLUTE PROHIBITIONS: Never mention \"China\", \"AliExpress\", \"mass production\", \"factory\", \"bulk\", \"wholesale\", or \"shipping tracking variations\". Reframe everything around a \"curated, small-batch, premium boutique model\".\n"
        "2. TITLE RESTRICTIONS: Do not keyword-stuff titles or use pipe-separated keyword chains. Write one clear Etsy-ready buyer-friendly title under 140 characters, ideally 80-125 characters when enough supported details exist. Put the product noun and strongest objective identifiers in the first 50-60 characters.\n"
        "3. DESCRIPTION FORMATTING: Optimize for readability and scanning. Avoid large text walls. For all bulleted lists or technical attribute breakdowns, you must strictly use a literal hyphen (-) instead of bullet dots (•, *, or circle symbols). ABSOLUTELY NO MARKDOWN FORMATTING: Do not use asterisks (**) or underscores (_) to bold or italicize text, as Etsy does not support markdown. Use ALL CAPS for section headers instead. Ensure key traits like color, exact size, and materials appear clearly in the first two sentences.\n"
        "4. TITLE-TAG MATCH: Ensure the 2 or 3 most important keyword phrases in the Title exactly match 2 or 3 of the Tags.\n"
        "5. OCCASION TARGETING: If applicable, weave in 1 or 2 tags targeting gift intent (e.g., \"Gifts for Her\", \"Anniversary Gift\")."
    )
}

DEFAULT_PRESETS["custom_prompt_rules"] = (
    "You are an expert e-commerce copywriter and Etsy SEO strategist specializing in premium boutique branding. Transform raw supplier/manufacturer details into a polished, readable, high-converting Etsy listing while staying factually conservative.\n"
    "--- COPYWRITING AND COMPLIANCE RULES ---\n"
    "1. ABSOLUTE PROHIBITIONS: Never mention \"China\", \"AliExpress\", \"mass production\", \"factory\", \"wholesale\", \"dropshipping\", \"shipping tracking variations\", \"bulk order\", \"bulk pricing\", or \"bulk sale\". Do not claim small-batch, handmade, luxury, designer, eco-friendly, or premium materials unless directly supported by the source facts. Use a curated boutique tone without inventing business-model claims.\n"
    "2. TITLE RESTRICTIONS: Do not keyword-stuff titles or use pipe-separated keyword chains. Write one clear Etsy-ready buyer-friendly title under 140 characters, ideally 80-125 characters when enough supported details exist. Put the product noun and strongest objective identifiers in the first 50-60 characters.\n"
    "3. DESCRIPTION FORMATTING: Optimize for readability and scanning. Avoid large text walls. Use plain Etsy-safe text only: no markdown bold/italic, no asterisks for emphasis, and no underscores. For list items or attribute breakdowns, use a literal hyphen (-). Section headers may use ALL CAPS or clear title case, but keep them consistent.\n"
    "4. FACT SAFETY: Mention color, exact size, materials, capacity, closures, pockets, compatibility, gift audience, and care details only when supported by source text, image facts, or variation specs. If a detail is unknown, leave it out instead of guessing.\n"
    "5. TITLE-TAG MATCH: Ensure the 2 or 3 most important keyword phrases in the title exactly match 2 or 3 of the tags when possible, while keeping tags under 20 characters.\n"
    "6. OCCASION TARGETING: If clearly applicable, include 1 or 2 gift/use-intent tags such as \"gift for her\" or \"travel bag\", but do not force audience or occasion claims onto unrelated products."
)

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
    """Build a readable Etsy copywriting export."""
    tags = listing.get("tags", []) or []

    sections = [
        f"TITLE:\n{listing.get('title', '')}",
        f"CATEGORY:\n{listing.get('category', '')}",
        f"PRICE:\n{listing.get('suggested_price', '')}",
        f"TAGS:\n{', '.join(tags)}",
        f"DESCRIPTION:\n{listing.get('description', '')}",
    ]

    return "\n\n".join(sections)

def build_listing_tweak_source_context(metadata: dict) -> str:
    """Build concise factual context for copy tweaks without rescanning images."""
    specs = metadata.get("specs") or {}
    variation_specs = metadata.get("variation_specs") or []
    image_facts = metadata.get("image_facts") or {}
    context_parts = [
        f"Original product title: {metadata.get('title', '')}",
        f"Original price: {metadata.get('price', '')}",
        "Supplier/source text:",
        metadata.get("description_text", "") or "",
        "Scraped specs:",
        json.dumps(specs, indent=2, ensure_ascii=False),
        "Cached image facts:",
        json.dumps(image_facts, indent=2, ensure_ascii=False),
        "Cached variation specs:",
        json.dumps(variation_specs, indent=2, ensure_ascii=False),
    ]
    return "\n".join(str(part) for part in context_parts if part is not None).strip()

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
async def status_stream(user_token: str = Depends(get_user_token)):
    queue = streamer.subscribe(user_token)
    async def event_generator():
        try:
            while True:
                data = await queue.get()
                yield f"data: {json.dumps(data)}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            streamer.unsubscribe(queue, user_token)

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

def background_queue_product(req_data: dict, user_token: str = "default"):
    try:
        user_token = sanitize_user_token(user_token)
        title = req_data.get("title", "Untitled Product")
        slug = sanitize_filename(title)
        
        out_root = get_output_dir(user_token)
        product_dir = os.path.join(out_root, slug)
        
        dirs = {
            "main_images": os.path.join(product_dir, "main_images"),
            "variation_images": os.path.join(product_dir, "variation_images"),
            "description_images": os.path.join(product_dir, "description_images"),
        }
        for d in dirs.values():
            os.makedirs(d, exist_ok=True)
            
        streamer.publish({"status": "progress", "message": f"Downloading assets for: {title[:30]}..."}, user_token)

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
        streamer.publish({"status": "queue_updated"}, user_token)

        # Helper to update progress inside loop
        def report_progress():
            nonlocal downloaded_assets
            downloaded_assets += 1
            metadata["download_progress"] = f"{downloaded_assets}/{total_assets}"
            with open(meta_path, "w", encoding="utf-8") as fm:
                json.dump(metadata, fm, indent=4, ensure_ascii=False)
            streamer.publish({"status": "queue_updated"}, user_token)

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

        streamer.publish({
            "status": "notification",
            "level": "success",
            "title": "Product Download Finished",
            "message": f"{title[:60]} is ready in the queue.",
            "slug": slug,
        }, user_token)
        streamer.publish({"status": "progress", "message": f"Finished downloading: {title[:30]}"}, user_token)
        # Broadcast final queue update
        streamer.publish({"status": "queue_updated"}, user_token)


    except Exception as e:
        streamer.publish({
            "status": "error",
            "title": "Queue Download Failed",
            "message": f"Queue error: {str(e)}",
        }, user_token)

@app.post("/api/queue-product")
def queue_product(req: QueueProductRequest, background_tasks: BackgroundTasks, user_token: str = Depends(get_user_token)):
    background_tasks.add_task(background_queue_product, req.model_dump(), user_token)
    return {"status": "success", "message": "Product added to queue"}

# --- QUEUE MANAGEMENT ---
@app.get("/api/queue")
def list_queue(user_token: str = Depends(get_user_token)):
    out_root = get_output_dir(user_token)
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
                            meta["thumbnail_path"] = build_product_image_url(item, thumb, user_token)
                        else:
                            meta["thumbnail_path"] = None
                            
                        products.append(meta)
                except Exception:
                    pass
    return {"queue": products}

@app.post("/api/delete-queue-item")
def delete_queue_item(payload: dict, user_token: str = Depends(get_user_token)):
    slug = payload.get("slug")
    if not slug:
        raise HTTPException(status_code=400, detail="Missing slug")
    
    product_dir = resolve_product_dir(user_token, slug)
    if os.path.exists(product_dir) and os.path.isdir(product_dir):
        try:
            shutil.rmtree(product_dir)
            streamer.publish({"status": "queue_updated"}, user_token)
            return {"status": "success", "message": "Product deleted successfully"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to delete product: {str(e)}")
    else:
        raise HTTPException(status_code=404, detail="Product not found")


@app.get("/api/product-image/{slug}/{image_path:path}")
def serve_product_image(slug: str, image_path: str, user_token: str = Depends(get_user_token)):
    file_path = resolve_product_path(user_token, slug, image_path)
    if os.path.exists(file_path) and os.path.isfile(file_path):
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

class GeneratedImageTweakRequest(BaseModel):
    product_slug: str
    generated_image: str
    reference_image: str = ""
    prompt_mode: str = "preset"
    prompt_preset: str = "auto_product_staging"
    prompt: str = ""
    model_key: str = DEFAULT_FAL_MODEL_KEY
    thinking_level: str = "off"

class CopywritingOptions(BaseModel):
    depth: str = "quality" # "fast" | "balanced" | "quality" | "deep"

class RunPipelineRequest(BaseModel):
    product_slug: str
    mode: str # "listing_only" | "listing_with_images" | "images_only"
    image_tasks: list[ImageTaskConfig] = []
    image_settings: ImageGenerationSettings = ImageGenerationSettings()
    copywriting_options: CopywritingOptions = CopywritingOptions()

class CancelPipelineRequest(BaseModel):
    product_slug: str

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

def normalize_generated_image_path(metadata: dict, product_dir: str, local_path: str):
    if not local_path:
        raise HTTPException(status_code=400, detail="Missing generated image path")

    clean_rel = local_path.replace("\\", "/").lstrip("/")
    generated_images = metadata.get("generated_images") or []
    if not isinstance(generated_images, list):
        generated_images = []

    matched_entry = None
    for entry in generated_images:
        entry_path = get_image_local_path(entry)
        if entry_path and entry_path.replace("\\", "/").lstrip("/") == clean_rel:
            matched_entry = entry
            break

    if matched_entry is None:
        raise HTTPException(status_code=404, detail="Generated image not found in product metadata")

    product_abs = os.path.abspath(product_dir)
    image_abs = os.path.abspath(os.path.join(product_abs, clean_rel))
    try:
        if os.path.commonpath([product_abs, image_abs]) != product_abs:
            raise ValueError
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid generated image path")
    if not os.path.exists(image_abs):
        raise HTTPException(status_code=404, detail="Generated image file not found")

    return clean_rel, image_abs, matched_entry

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
def set_reference_image(req: ReferenceImageRequest, user_token: str = Depends(get_user_token)):
    try:
        product_dir = resolve_product_dir(user_token, req.product_slug)
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

        streamer.publish({"status": "queue_updated"}, user_token)
        return {
            "status": "success",
            "primary_reference_image": metadata["primary_reference_image"],
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

def run_image_generation_tasks(
    metadata: dict,
    product_dir: str,
    image_tasks: list,
    image_settings: dict,
    client,
    user_token: str = "default",
    product_slug: str = "",
    meta_path: str | None = None,
):
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
    }, user_token)
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

    def get_source_label(entry, source_folder: str, source_index: int):
        if isinstance(entry, dict):
            return entry.get("alt") or entry.get("title") or f"{source_folder} {source_index + 1}"
        return f"{source_folder} {source_index + 1}"

    def build_target_record(entry, source_folder: str, source_index: int):
        local_path = get_image_local_path(entry)
        if not local_path:
            return None
        return {
            "entry": entry,
            "local_path": local_path,
            "source_folder": source_folder,
            "source_index": source_index,
            "source_label": get_source_label(entry, source_folder, source_index),
        }

    def unique_target_records(records):
        seen = set()
        unique = []
        for record in records:
            if not record:
                continue
            key = record["local_path"].replace("\\", "/")
            if key in seen:
                continue
            seen.add(key)
            unique.append(record)
        return unique

    def resolve_task_target_records(task_type: str, target_folder: str):
        if target_folder == "selected_reference":
            selected_reference = resolve_primary_reference_image(metadata)
            if selected_reference:
                source = selected_reference.get("source") or "selected_reference"
                return unique_target_records([build_target_record(selected_reference, source, 0)])
            return []

        if task_type == "individual":
            first_map = {
                "first_main": "main_images",
                "first_variation": "variation_images",
                "first_description": "description_images",
            }
            source_folder = first_map.get(target_folder, target_folder)
            entries = metadata.get(source_folder) or []
            if entries:
                return unique_target_records([build_target_record(entries[0], source_folder, 0)])
            return []

        if target_folder == "first_main":
            entries = metadata.get("main_images") or []
            if entries:
                return unique_target_records([build_target_record(entries[0], "main_images", 0)])
            return []

        entries = metadata.get(target_folder) or []
        return unique_target_records([
            build_target_record(entry, target_folder, index)
            for index, entry in enumerate(entries)
        ])

    existing_generated_images = metadata.get("generated_images") or []
    if not isinstance(existing_generated_images, list):
        existing_generated_images = []
    generated_images = list(existing_generated_images)

    run_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    def maybe_cancel():
        if product_slug:
            check_pipeline_cancelled(user_token, product_slug)

    def save_partial_generated_images():
        metadata["generated_images"] = generated_images
        if meta_path:
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=4, ensure_ascii=False)

    def build_generated_filename(target_folder: str, task, task_index: int, image_index: int):
        prompt_mode = task.get("prompt_mode", "custom") if isinstance(task, dict) else getattr(task, "prompt_mode", "custom")
        prompt_preset = task.get("prompt_preset", DEFAULT_IMAGE_PROMPT_PRESET) if isinstance(task, dict) else getattr(task, "prompt_preset", DEFAULT_IMAGE_PROMPT_PRESET)
        prompt_label = prompt_preset if prompt_mode == "preset" else "custom"
        unique_suffix = uuid.uuid4().hex[:8]
        target_slug = re.sub(r"[^A-Za-z0-9_-]+", "_", target_folder).strip("_")[:18] or "target"
        prompt_slug = re.sub(r"[^A-Za-z0-9_-]+", "_", prompt_label).strip("_")[:18] or "prompt"
        base_name = (
            f"gen_{run_stamp}_{unique_suffix}_"
            f"t{task_index + 1}_i{image_index + 1}_{target_slug}_{prompt_slug}"
        )
        return f"{base_name}.png"

    for t_idx, task in enumerate(image_tasks):
        maybe_cancel()
        task_type = get_task_value(task, "task_type", "batch")
        target_folder = get_task_value(task, "target", "main_images")
        target_label = "selected reference image" if target_folder == "selected_reference" else target_folder
        task_image_settings, task_thinking_level = resolve_task_image_settings(task)

        target_records = []
        if target_folder == "selected_reference":
            selected_reference = resolve_primary_reference_image(metadata)
            if selected_reference and selected_reference.get("selected_by") == "fallback":
                streamer.publish({
                    "status": "progress",
                    "message": "No manual reference selected; falling back to the first available product image.",
                }, user_token)
        target_records = resolve_task_target_records(task_type, target_folder)

        if not target_records:
            streamer.publish({"status": "progress", "message": f"Task {t_idx+1}: No images found in {target_label}, skipping."}, user_token)
            continue

        thinking_note = f" ({task_thinking_level} thinking)" if task_thinking_level else ""
        streamer.publish({
            "status": "progress",
            "message": (
                f"Task {t_idx+1}: Generating {len(target_records)} images for {target_label} "
                f"with {task_image_settings['label']}{thinking_note}..."
            )
        }, user_token)

        for img_idx, target_record in enumerate(target_records):
            maybe_cancel()
            ref_path = get_abs_path(target_record["entry"])
            if not os.path.exists(ref_path):
                streamer.publish({"status": "progress", "message": f"   -> Reference image missing, skipping item {img_idx+1}."}, user_token)
                continue

            visual_details = generate_image_prompt_details(ref_path, client)
            maybe_cancel()
            prompt_style = resolve_image_task_prompt(task, metadata, visual_details)
            final_prompt = prompt_style

            out_filename = build_generated_filename(target_folder, task, t_idx, img_idx)
            out_path = os.path.join(product_dir, out_filename)

            streamer.publish({
                "status": "progress",
                "message": (
                    f"   -> Processing {img_idx+1}/{len(target_records)} "
                    f"from {target_record['local_path']}..."
                ),
            }, user_token)

            res_path = generate_image_with_imagen(
                prompt=final_prompt,
                output_path=out_path,
                client=client,
                reference_image=ref_path,
                fal_model_key=task_image_settings["model_key"],
                fal_thinking_level=task_thinking_level
            )

            if res_path:
                generated_images.append({
                    "local_path": out_filename,
                    "source_image": target_record["local_path"],
                    "source_folder": target_record["source_folder"],
                    "source_index": target_record["source_index"],
                    "source_label": target_record["source_label"],
                    "task_type": task_type,
                    "task_target": target_folder,
                    "prompt_mode": get_task_value(task, "prompt_mode", "custom"),
                    "prompt_preset": get_task_value(task, "prompt_preset", ""),
                    "model_key": task_image_settings["model_key"],
                    "thinking_level": task_thinking_level or "off",
                })
                save_partial_generated_images()
            maybe_cancel()

    metadata["generated_images"] = generated_images
    return generated_images

COPYWRITING_DEPTH_CONFIG = {
    "fast": {
        "desc_images": 1,
        "main_images": 1,
        "variation_images": 0,
        "variation_spec_cap": 3,
        "visual_scan": "when_text_weak",
        "variation_scan": "if_size_signal",
    },
    "balanced": {
        "desc_images": 3,
        "main_images": 2,
        "variation_images": 1,
        "variation_spec_cap": 5,
        "visual_scan": "always",
        "variation_scan": "if_size_signal",
    },
    "quality": {
        "desc_images": 4,
        "main_images": 2,
        "variation_images": 1,
        "variation_spec_cap": 5,
        "visual_scan": "always",
        "variation_scan": "if_size_signal",
    },
    "deep": {
        "desc_images": 6,
        "main_images": 3,
        "variation_images": 2,
        "variation_spec_cap": None,
        "visual_scan": "always",
        "variation_scan": "always",
    },
}

COPYWRITING_DEPTH_RANK = {
    "fast": 1,
    "balanced": 2,
    "deep": 3,
    "quality": 4,
}

SIZE_SIGNAL_RE = re.compile(
    r"\b(size|sizes|dimension|dimensions|height|width|depth|length|capacity|"
    r"weight|drop|strap|handle|inch|inches|cm|mm|meter|litre|liter|a4|"
    r"small|medium|large|xl|xs|s\b|m\b|l\b)\b|"
    r"\d+(?:\.\d+)?\s*(?:cm|mm|m|in|inch|inches|kg|g|lb|oz|l|liter|litre)|"
    r"\d+\s*[xX×]\s*\d+",
    re.IGNORECASE,
)

def normalize_copywriting_depth(copywriting_options: dict | None = None) -> str:
    depth = str((copywriting_options or {}).get("depth") or "quality").strip().lower()
    return depth if depth in COPYWRITING_DEPTH_CONFIG else "quality"

def can_reuse_copywriting_cache(cached_depth: str | None, requested_depth: str) -> bool:
    cached_rank = COPYWRITING_DEPTH_RANK.get(str(cached_depth or "").strip().lower(), 0)
    requested_rank = COPYWRITING_DEPTH_RANK.get(requested_depth, COPYWRITING_DEPTH_RANK["quality"])
    return cached_rank >= requested_rank

def has_size_signal(*values) -> bool:
    joined = " ".join(str(value or "") for value in values)
    return bool(SIZE_SIGNAL_RE.search(joined))

def has_useful_text_for_copywriting(desc_input: str, specs: dict) -> bool:
    spec_values = " ".join(str(value or "") for value in (specs or {}).values())
    combined = f"{desc_input or ''} {spec_values}".strip()
    return len(combined) >= 180 and len(re.findall(r"[A-Za-z0-9]+", combined)) >= 35

def get_image_path_from_entry(entry):
    if isinstance(entry, dict):
        return entry.get("local_path") or entry.get("path") or entry.get("url") or ""
    return str(entry or "")

def get_variation_signal_text(var_items: list) -> str:
    chunks = []
    for item in var_items or []:
        if isinstance(item, dict):
            chunks.extend([
                item.get("alt", ""),
                item.get("title", ""),
                item.get("name", ""),
                item.get("label", ""),
                json.dumps(item.get("detected_specs", ""), ensure_ascii=False) if item.get("detected_specs") else "",
            ])
        else:
            chunks.append(str(item or ""))
    return " ".join(chunks)

def should_scan_variation_specs(depth: str, var_items: list, desc_input: str, specs_text: str, image_facts: dict) -> bool:
    if not var_items:
        return False
    config = COPYWRITING_DEPTH_CONFIG[depth]
    if config["variation_scan"] == "always":
        return True
    signal_text = " ".join([
        desc_input or "",
        specs_text or "",
        json.dumps(image_facts or {}, ensure_ascii=False),
        get_variation_signal_text(var_items),
    ])
    return has_size_signal(signal_text)

def cap_variation_items(depth: str, var_items: list) -> list:
    cap = COPYWRITING_DEPTH_CONFIG[depth]["variation_spec_cap"]
    if cap is None:
        return var_items
    return var_items[:cap]

def background_run_pipeline(slug: str, mode: str, image_tasks: list = None, image_settings: dict = None, copywriting_options: dict = None, user_token: str = "default"):
    meta_path = None
    metadata = {}
    try:
        user_token = sanitize_user_token(user_token)
        product_dir = resolve_product_dir(user_token, slug)
        meta_path = os.path.join(product_dir, "metadata.json")
        
        if not os.path.exists(meta_path):
            raise Exception("Product metadata not found")
            
        with open(meta_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)
            
        metadata["status"] = "processing"
        metadata["cancel_requested"] = is_pipeline_cancel_requested(user_token, slug)
        if not metadata["cancel_requested"]:
            metadata.pop("cancelled_at", None)
            metadata.pop("error", None)
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=4, ensure_ascii=False)
            
        streamer.publish({"status": "queue_updated"}, user_token)
        streamer.publish({"status": "progress", "message": f"Processing item: {metadata.get('title')[:30]}..."}, user_token)
        check_pipeline_cancelled(user_token, slug)

        client = get_genai_client()
        title = metadata.get("title", "")
        price = metadata.get("price", "")
        copywriting_depth = normalize_copywriting_depth(copywriting_options)
        depth_config = COPYWRITING_DEPTH_CONFIG[copywriting_depth]
        check_pipeline_cancelled(user_token, slug)

        if mode == "images_only":
            generated_images = []
            if image_tasks:
                generated_images = run_image_generation_tasks(
                    metadata,
                    product_dir,
                    image_tasks,
                    image_settings,
                    client,
                    user_token,
                    slug,
                    meta_path,
                )
            else:
                streamer.publish({"status": "progress", "message": "AI Images Only selected, but no image tasks were configured."}, user_token)

            check_pipeline_cancelled(user_token, slug)
            metadata["status"] = "done"
            metadata["cancel_requested"] = False
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=4, ensure_ascii=False)

            streamer.publish({"status": "queue_updated"}, user_token)
            streamer.publish({
                "status": "done",
                "title": "Image Generation Finished",
                "message": f"Generated images for {title[:60]}",
                "output_dir_name": slug,
                "generated_images": generated_images or metadata.get("generated_images", []),
            }, user_token)
            return

        # Build description input early so copywriting depth can decide whether scans are needed.
        specs_text = "\n".join([f"{k}: {v}" for k, v in metadata.get("specs", {}).items()])
        desc_input = metadata.get("description_text", "")
        if specs_text:
            desc_input = specs_text + "\n\n" + desc_input

        streamer.publish({
            "status": "progress",
            "message": f"Copywriting depth: {copywriting_depth.title()}",
        }, user_token)
        check_pipeline_cancelled(user_token, slug)

        # --- PHASE 1: SMART VISUAL EXTRACTION (Or use cache) ---
        image_facts = metadata.get("image_facts")
        image_facts_depth = metadata.get("image_facts_depth")
        if image_facts is not None and can_reuse_copywriting_cache(image_facts_depth, copywriting_depth):
            streamer.publish({"status": "progress", "message": f"Phase 1: Reusing cached image facts ({image_facts_depth or 'legacy'})."}, user_token)
        else:
            if image_facts is not None:
                streamer.publish({
                    "status": "progress",
                    "message": f"Phase 1: Refreshing image facts for {copywriting_depth.title()} quality.",
                }, user_token)
            should_scan_visuals = (
                depth_config["visual_scan"] == "always"
                or not has_useful_text_for_copywriting(desc_input, metadata.get("specs", {}))
            )
            desc_imgs = (metadata.get("description_images") or [])[:depth_config["desc_images"]]
            main_imgs = (metadata.get("main_images") or [])[:depth_config["main_images"]]
            
            var_imgs = []
            for item in (metadata.get("variation_images") or [])[:depth_config["variation_images"]]:
                if isinstance(item, dict):
                    var_imgs.append(item.get("local_path"))
                else:
                    var_imgs.append(item)

            scan_targets_rel = desc_imgs + main_imgs + var_imgs
            scan_targets_abs = [os.path.join(product_dir, img_rel) for img_rel in scan_targets_rel if img_rel]
            
            if not should_scan_visuals:
                streamer.publish({"status": "progress", "message": "Phase 1: Skipping visual scan; text/specs are enough for selected depth."}, user_token)
                image_facts = {}
            elif scan_targets_abs:
                check_pipeline_cancelled(user_token, slug)
                streamer.publish({"status": "progress", "message": f"Phase 1: Scanning {len(scan_targets_abs)} product images for visual specs..."}, user_token)
                try:
                    image_facts = extract_visual_specs(scan_targets_abs, client)
                    check_pipeline_cancelled(user_token, slug)
                    metadata["image_facts"] = image_facts
                    metadata["image_facts_depth"] = copywriting_depth
                    # Save progress intermediate
                    with open(meta_path, "w", encoding="utf-8") as f:
                        json.dump(metadata, f, indent=4, ensure_ascii=False)
                except Exception as ex:
                    print(f"Warning: Visual spec extraction failed: {ex}")
                    image_facts = {}
            else:
                image_facts = {}

        # Fallback to visual scanning ONLY if there is absolutely no text at all
        if not desc_input or len(desc_input.strip()) < 50:
            check_pipeline_cancelled(user_token, slug)
            local_imgs = []
            for m in metadata.get("main_images", [])[:max(1, depth_config["main_images"])]:
                local_imgs.append(os.path.join(product_dir, m))
            if local_imgs:
                streamer.publish({"status": "progress", "message": "No text description found. Fallback: visual description scan..."}, user_token)
                desc_input = generate_description_from_images(local_imgs, client)
                check_pipeline_cancelled(user_token, slug)
            else:
                desc_input = "Generic product details."

        # --- PHASE 1b: VARIATION SPECIFIC EXTRACTION ---
        check_pipeline_cancelled(user_token, slug)
        variation_specs = metadata.get("variation_specs")
        variation_specs_depth = metadata.get("variation_specs_depth")
        if variation_specs is not None and can_reuse_copywriting_cache(variation_specs_depth, copywriting_depth):
            streamer.publish({"status": "progress", "message": f"Phase 1b: Reusing cached variation specs ({variation_specs_depth or 'legacy'})."}, user_token)
        else:
            if variation_specs is not None:
                streamer.publish({
                    "status": "progress",
                    "message": f"Phase 1b: Refreshing variation specs for {copywriting_depth.title()} quality.",
                }, user_token)
            var_items = metadata.get("variation_images") or []
            should_scan_variations = should_scan_variation_specs(copywriting_depth, var_items, desc_input, specs_text, image_facts)
            capped_var_items = cap_variation_items(copywriting_depth, var_items)
            if should_scan_variations and capped_var_items:
                if len(capped_var_items) < len(var_items):
                    streamer.publish({
                        "status": "progress",
                        "message": (
                            f"Phase 1b: Scanning {len(capped_var_items)} of {len(var_items)} "
                            "variations for size/dimension clues."
                        ),
                    }, user_token)
                else:
                    streamer.publish({"status": "progress", "message": f"Phase 1b: Scanning {len(capped_var_items)} variations for sizes & dimensions..."}, user_token)
                try:
                    check_pipeline_cancelled(user_token, slug)
                    variation_specs = extract_variation_specs(
                        variations=capped_var_items,
                        product_dir=product_dir,
                        overall_specs=image_facts,
                        scraped_desc=desc_input,
                        client=client
                    )
                    check_pipeline_cancelled(user_token, slug)
                    metadata["variation_specs"] = variation_specs
                    metadata["variation_specs_depth"] = copywriting_depth
                    
                    # Update each variation image's detected_specs as well
                    for item, spec in zip(capped_var_items, variation_specs):
                        if isinstance(item, dict):
                            item["detected_specs"] = spec
                    
                    with open(meta_path, "w", encoding="utf-8") as f:
                        json.dump(metadata, f, indent=4, ensure_ascii=False)
                except Exception as ex:
                    print(f"Warning: Variation spec extraction failed: {ex}")
                    variation_specs = []
            else:
                if var_items:
                    streamer.publish({
                        "status": "progress",
                        "message": "Phase 1b: Skipping variation scan; no size/dimension signals found for selected depth.",
                    }, user_token)
                variation_specs = []

        # --- PHASE 2 & 3: COPYWRITING & SELF-REVIEW ---
        check_pipeline_cancelled(user_token, slug)
        streamer.publish({"status": "progress", "message": "Phase 2: Generating enriched copywriting & running Phase 3 self-critique..."}, user_token)
        presets = load_listing_presets()
        
        etsy_listing = write_etsy_listing(
            title=title, 
            description=desc_input, 
            price=price, 
            client=client, 
            presets=presets, 
            image_facts=image_facts,
            variation_specs=variation_specs,
            copywriting_depth=copywriting_depth,
        )
        check_pipeline_cancelled(user_token, slug)
        
        if not etsy_listing:
            raise Exception("Copywriting generation failed.")

        # Save etsy listing info to metadata
        metadata["etsy_listing"] = etsy_listing

        # Image generation if requested
        generated_images = []
        if mode == "listing_with_images" and image_tasks:
            check_pipeline_cancelled(user_token, slug)
            generated_images = run_image_generation_tasks(
                metadata,
                product_dir,
                image_tasks,
                image_settings,
                client,
                user_token,
                slug,
                meta_path,
            )

        check_pipeline_cancelled(user_token, slug)
        metadata["status"] = "done"
        metadata["cancel_requested"] = False
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

        streamer.publish({"status": "queue_updated"}, user_token)
        streamer.publish({
            "status": "done",
            "title": "Listing Finished",
            "message": f"Copywriting completed for {title[:60]}",
            "output_dir_name": slug,
            "listing": etsy_listing,
            "generated_images": generated_images or metadata.get("generated_images", []),
        }, user_token)

    except PipelineCancelled:
        try:
            if meta_path:
                mark_pipeline_cancelled(user_token, slug, meta_path, metadata)
        except Exception:
            pass
    except Exception as e:
        # Mark as failed
        try:
            if not meta_path:
                raise RuntimeError("No metadata path")
            with open(meta_path, "r", encoding="utf-8") as f:
                metadata = json.load(f)
            metadata["status"] = "failed"
            metadata["error"] = str(e)
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=4, ensure_ascii=False)
            streamer.publish({"status": "queue_updated"}, user_token)
        except Exception:
            pass
        streamer.publish({
            "status": "error",
            "title": "Pipeline Failed",
            "message": f"Pipeline error: {str(e)}",
            "slug": slug,
        }, user_token)
    finally:
        try:
            clear_pipeline_cancel(user_token, slug)
        except Exception:
            pass

@app.post("/api/run-pipeline")
def run_pipeline_api(req: RunPipelineRequest, background_tasks: BackgroundTasks, user_token: str = Depends(get_user_token)):
    image_settings = req.image_settings.model_dump() if req.image_settings else {}
    copywriting_options = req.copywriting_options.model_dump() if req.copywriting_options else {}
    clear_pipeline_cancel(user_token, req.product_slug)
    background_tasks.add_task(background_run_pipeline, req.product_slug, req.mode, req.image_tasks, image_settings, copywriting_options, user_token)
    return {"status": "success", "message": "Pipeline execution started"}

@app.post("/api/cancel-pipeline")
def cancel_pipeline_api(req: CancelPipelineRequest, user_token: str = Depends(get_user_token)):
    slug = req.product_slug
    product_dir = resolve_product_dir(user_token, slug)
    meta_path = os.path.join(product_dir, "metadata.json")
    if not os.path.exists(meta_path):
        raise HTTPException(status_code=404, detail="Product not found")

    with open(meta_path, "r", encoding="utf-8") as f:
        metadata = json.load(f)

    status = metadata.get("status", "queued")
    if status not in {"processing", "cancelling"}:
        return {
            "status": "idle",
            "message": f"No active pipeline is running for {metadata.get('title', slug)[:60]}",
        }

    request_pipeline_cancel(user_token, slug)
    metadata["status"] = "cancelling"
    metadata["cancel_requested"] = True
    metadata["cancel_requested_at"] = datetime.now().isoformat(timespec="seconds")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=4, ensure_ascii=False)

    streamer.publish({"status": "queue_updated"}, user_token)
    streamer.publish({
        "status": "progress",
        "message": f"Cancel requested for {metadata.get('title', slug)[:60]}. Waiting for the current API call to finish safely...",
        "slug": slug,
    }, user_token)
    return {"status": "success", "message": "Pipeline cancellation requested"}

@app.post("/api/tweak-listing")
def tweak_listing(req: ListingTweakRequest, user_token: str = Depends(get_user_token)):
    try:
        if req.context_mode != "existing_output":
            raise HTTPException(status_code=400, detail="Only existing_output tweak context is supported in this version.")

        product_dir = resolve_product_dir(user_token, req.output_dir_name)
        meta_path = os.path.join(product_dir, "metadata.json")

        if not os.path.exists(meta_path):
            raise HTTPException(status_code=404, detail="Product not found")

        with open(meta_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)

        current_listing = req.current_listing if isinstance(req.current_listing, dict) and req.current_listing else metadata.get("etsy_listing")
        if not isinstance(current_listing, dict) or not current_listing:
            raise HTTPException(status_code=400, detail="This product has no generated Etsy listing to tweak yet.")

        allowed_fields = {"title", "category", "description", "tags"}
        requested_fields = req.fields or ["title", "category", "description", "tags"]
        fields = [field for field in requested_fields if field in allowed_fields]
        if not fields:
            raise HTTPException(status_code=400, detail="Select at least one copy field to tweak.")

        listing = tweak_etsy_listing(
            existing_listing=current_listing,
            preset_key=req.preset_key,
            instruction=req.instruction,
            fields=fields,
            source_context=build_listing_tweak_source_context(metadata),
            image_facts=metadata.get("image_facts") or {},
            variation_specs=metadata.get("variation_specs") or [],
            price=metadata.get("price", ""),
            presets=load_listing_presets(),
            client=get_genai_client(),
        )

        if not listing:
            raise HTTPException(status_code=500, detail="Copy tweak failed.")

        return {"status": "success", "listing": listing}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/tweak-generated-image")
def tweak_generated_image(req: GeneratedImageTweakRequest, user_token: str = Depends(get_user_token)):
    try:
        product_dir = resolve_product_dir(user_token, req.product_slug)
        meta_path = os.path.join(product_dir, "metadata.json")
        if not os.path.exists(meta_path):
            raise HTTPException(status_code=404, detail="Product not found")

        with open(meta_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)

        parent_rel, parent_abs, parent_entry = normalize_generated_image_path(
            metadata,
            product_dir,
            req.generated_image,
        )

        model_settings = resolve_fal_image_settings(req.model_key)
        thinking_level = (req.thinking_level or "").strip().lower()
        if not model_settings.get("supports_thinking") or thinking_level not in model_settings.get("thinking_levels", []):
            thinking_level = ""

        reference_rel = ""
        reference_abs = ""
        reference_image_used = False
        reference_image_ignored = False
        if req.reference_image:
            reference_rel, reference_abs = normalize_product_image_path(product_dir, req.reference_image)

        reference_images = [parent_abs]
        if reference_abs:
            if model_settings.get("input_image_list"):
                reference_images.append(reference_abs)
                reference_image_used = True
            else:
                reference_image_ignored = True

        client = get_genai_client()
        visual_details = generate_image_prompt_details(parent_abs, client)
        prompt_mode = "custom" if req.prompt_mode == "custom" and req.prompt.strip() else "preset"
        task = {
            "prompt_mode": prompt_mode,
            "prompt_preset": req.prompt_preset or DEFAULT_IMAGE_PROMPT_PRESET,
            "prompt": req.prompt or "",
        }
        base_prompt = resolve_image_task_prompt(task, metadata, visual_details)
        reference_note = (
            "If a second reference image is provided, use it only to preserve the original product identity, "
            "shape, materials, colors, and important product details."
            if len(reference_images) > 1
            else "Use the selected generated image as the edit target and preserve the product identity."
        )
        final_prompt = (
            "Edit the selected generated product image into a refined final listing image. "
            "Keep the useful composition from the selected generated image unless the instruction asks for a scene change. "
            f"{reference_note} "
            f"{base_prompt}"
        )

        run_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        prompt_label = task["prompt_preset"] if prompt_mode == "preset" else "custom"
        prompt_slug = re.sub(r"[^A-Za-z0-9_-]+", "_", prompt_label).strip("_")[:18] or "prompt"
        out_filename = f"tweak_{run_stamp}_{uuid.uuid4().hex[:8]}_{prompt_slug}.png"
        out_path = os.path.join(product_dir, out_filename)

        res_path = generate_image_with_imagen(
            prompt=final_prompt,
            output_path=out_path,
            client=client,
            reference_image=parent_abs,
            reference_images=reference_images,
            fal_model_key=model_settings["model_key"],
            fal_thinking_level=thinking_level,
        )

        if not res_path:
            raise HTTPException(status_code=500, detail="Image tweak generation failed")

        generated_images = metadata.get("generated_images") or []
        if not isinstance(generated_images, list):
            generated_images = []

        source_label = ""
        if isinstance(parent_entry, dict):
            source_label = parent_entry.get("source_label") or parent_entry.get("prompt_preset") or "generated image"

        new_entry = {
            "local_path": out_filename,
            "is_tweak": True,
            "parent_image": parent_rel,
            "reference_image": reference_rel,
            "reference_image_used": reference_image_used,
            "reference_image_ignored": reference_image_ignored,
            "source_image": parent_rel,
            "source_folder": "generated_images",
            "source_label": f"Tweak of {source_label}" if source_label else "Tweaked image",
            "prompt_mode": prompt_mode,
            "prompt_preset": task["prompt_preset"] if prompt_mode == "preset" else "",
            "custom_prompt": req.prompt or "",
            "model_key": model_settings["model_key"],
            "thinking_level": thinking_level or "off",
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        generated_images.append(new_entry)
        metadata["generated_images"] = generated_images

        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=4, ensure_ascii=False)

        streamer.publish({"status": "queue_updated"}, user_token)
        return {
            "status": "success",
            "generated_image": new_entry,
            "generated_images": generated_images,
            "reference_image_ignored": reference_image_ignored,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class ExportZipRequest(BaseModel):
    product_slugs: list

@app.post("/api/export-zip")
def export_zip(req: ExportZipRequest, user_token: str = Depends(get_user_token)):
    try:
        out_root = get_output_dir(user_token)
        if not req.product_slugs:
            raise HTTPException(status_code=400, detail="No products selected")
            
        if len(req.product_slugs) == 1:
            slug = req.product_slugs[0]
            product_dir = resolve_product_dir(user_token, slug)
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
                src = resolve_product_dir(user_token, slug)
                if os.path.exists(src):
                    shutil.copytree(src, os.path.join(export_dir, slug))
                    
            zip_path = os.path.join(out_root, "AliExpress_Batch_Export.zip")
            shutil.make_archive(zip_path[:-4], 'zip', export_dir)
            shutil.rmtree(temp_dir)
            return FileResponse(zip_path, media_type='application/zip', filename="AliExpress_Batch_Export.zip")
            
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/save-listing")
def save_listing(req: ListingSaveRequest, user_token: str = Depends(get_user_token)):
    try:
        product_dir = resolve_product_dir(user_token, req.output_dir_name)
        meta_path = os.path.join(product_dir, "metadata.json")
        
        if not os.path.exists(meta_path):
            raise HTTPException(status_code=404, detail="Product not found")
            
        with open(meta_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)
            
        # Update listing details
        if "etsy_listing" not in metadata:
            metadata["etsy_listing"] = {}
            
        metadata["etsy_listing"]["title"] = req.title
        metadata["etsy_listing"]["category"] = req.category
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
            
        streamer.publish({"status": "queue_updated"}, user_token)
        return {"status": "success", "message": "Listing saved successfully"}
    except HTTPException:
        raise
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
                "input_image_list": config.get("input_image_list", False),
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
