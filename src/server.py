import os
import sys
import json
import asyncio
import shutil
import urllib.parse
import urllib.request
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
    generate_image_prompt_details
)
from src.image_gen import (
    load_themes,
    roll_theme_prompts,
    generate_image_with_imagen
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
        for idx, img_url in enumerate(var_list):
            ext = ".jpg"
            for possible_ext in [".png", ".jpeg", ".webp"]:
                if possible_ext in img_url.lower(): ext = possible_ext
            filename = f"var_{idx+1}{ext}"
            dest = os.path.join(dirs["variation_images"], filename)
            if download_image(img_url, dest):
                metadata["variation_images"].append(f"variation_images/{filename}")
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
                            thumb = meta["variation_images"][0]
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


class RunPipelineRequest(BaseModel):
    product_slug: str
    mode: str # "listing_only" | "listing_with_images"
    theme: str = "bauhaus_beige"
    preset: str = "product_staging"

def background_run_pipeline(slug: str, mode: str, theme: str, preset: str):
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
        streamer.publish({"status": "progress", "message": f"Processing queued item: {metadata.get('title')[:30]}..."})

        # Generate Listing Copy
        client = get_genai_client()
        title = metadata.get("title", "")
        price = metadata.get("price", "")
        
        # Build description input
        specs_text = "\n".join([f"{k}: {v}" for k, v in metadata.get("specs", {}).items()])
        desc_input = metadata.get("description_text", "")
        if specs_text:
            desc_input = specs_text + "\n\n" + desc_input

        # Fallback to visual scanning if no text
        if not desc_input or len(desc_input.strip()) < 50:
            local_imgs = []
            for m in metadata.get("main_images", [])[:3]:
                local_imgs.append(os.path.join(product_dir, m))
            if local_imgs:
                streamer.publish({"status": "progress", "message": "Scanning images visually for description..."})
                desc_input = generate_description_from_images(local_imgs, client)
            else:
                desc_input = "Generic product details."

        streamer.publish({"status": "progress", "message": "Generating Etsy listing copywriting..."})
        etsy_listing = write_etsy_listing(title, desc_input, price, client)
        
        if not etsy_listing:
            raise Exception("Copywriting generation failed.")

        # Save etsy listing info to metadata
        metadata["etsy_listing"] = etsy_listing

        # Image generation if requested
        if mode == "listing_with_images":
            streamer.publish({"status": "progress", "message": "Generating style templates..."})
            ref_image_rel = None
            if metadata.get("main_images"):
                ref_image_rel = metadata["main_images"][0]
            elif metadata.get("variation_images"):
                ref_image_rel = metadata["variation_images"][0]
                
            ref_image = os.path.join(product_dir, ref_image_rel) if ref_image_rel else None
            reference_input = ref_image if ref_image else desc_input
            visual_details = generate_image_prompt_details(reference_input, client)
            
            combined_trigger = f"product, {visual_details}" if visual_details else "product"
            themes_config = load_themes(os.path.join(os.path.dirname(__file__), "..", "themes.yaml"))
            prompts_to_run = roll_theme_prompts(theme, themes_config, combined_trigger, preset_name=preset)
            metadata["prompts"] = prompts_to_run

        metadata["status"] = "done"
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=4, ensure_ascii=False)
            
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
    background_tasks.add_task(background_run_pipeline, req.product_slug, req.mode, req.theme, req.preset)
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

# Mount web static directory
static_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
