import os
import sys
import json
import asyncio
from fastapi import FastAPI, BackgroundTasks, HTTPException, Query
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Add workspace directory to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.scraper import scrape_aliexpress, sanitize_filename
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

async def run_pipeline(url: str, theme: str, product_trigger: str, headed: bool):
    try:
        client = get_genai_client()
        streamer.publish({"status": "progress", "message": "Initializing client..."})
        
        # Phase 1: Scrape
        streamer.publish({"status": "progress", "message": "Scraping product from AliExpress (Playwright)..."})
        scraped = scrape_aliexpress(url, headless=not headed)
        
        title = scraped.get("title", "")
        price = scraped.get("price", "")
        description = scraped.get("description_text", "")
        image_paths = scraped.get("image_paths", [])
        
        if not title:
            streamer.publish({"status": "error", "message": "Failed to scrape product. No title found."})
            return
            
        streamer.publish({"status": "progress", "message": f"Scraped Title: '{title[:45]}...'"})
        
        # Check description
        if not description or len(description.strip()) < 50:
            if image_paths:
                streamer.publish({"status": "progress", "message": "No description text found. Scanning images visually..."})
                description = generate_description_from_images(image_paths, client)
            else:
                description = "Generic product details (no description extracted)."
                
        # Phase 2: Copywriting
        streamer.publish({"status": "progress", "message": "Generating Etsy listing copywriting..."})
        etsy_listing = write_etsy_listing(title, description, price, client)
        
        if not etsy_listing:
            streamer.publish({"status": "error", "message": "Copywriting generation failed."})
            return
            
        streamer.publish({"status": "progress", "message": "Etsy details generated successfully."})
        
        # Phase 3: Image Prompts
        streamer.publish({"status": "progress", "message": "Analyzing image styles..."})
        reference_input = image_paths[0] if (image_paths and os.path.exists(image_paths[0])) else description
        visual_details = generate_image_prompt_details(reference_input, client)
        
        if visual_details:
            combined_trigger = f"{product_trigger}, {visual_details}"
        else:
            combined_trigger = product_trigger
            
        themes_config = load_themes("themes.yaml")
        prompts_to_run = roll_theme_prompts(theme, themes_config, combined_trigger)
        
        # Create output dir
        product_slug = sanitize_filename(etsy_listing.get('title') or "etsy_listing")
        product_output_dir = os.path.join("outputs", product_slug)
        os.makedirs(product_output_dir, exist_ok=True)
        
        generated_images = []
        for i, image_item in enumerate(prompts_to_run):
            img_name = image_item["name"]
            prompt = image_item["prompt"]
            
            output_image_name = f"{img_name}.png"
            output_image_path = os.path.join(product_output_dir, output_image_name)
            
            streamer.publish({"status": "progress", "message": f"Rendering lifestyle photo {i+1}/{len(prompts_to_run)} ({img_name})..."})
            
            ref_image = image_paths[0] if image_paths else None
            local_path = generate_image_with_imagen(prompt, output_image_path, client, reference_image=ref_image)
            
            if local_path:
                web_path = f"/outputs/{product_slug}/{output_image_name}"
                generated_images.append(web_path)
                
        # Phase 4: Save metadata
        metadata_path = os.path.join(product_output_dir, "metadata.json")
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(etsy_listing, f, indent=4, ensure_ascii=False)
            
        streamer.publish({
            "status": "done",
            "message": "Automation pipeline completed successfully!",
            "listing": etsy_listing,
            "images": generated_images,
            "output_dir_name": product_slug
        })
        
    except Exception as e:
        streamer.publish({"status": "error", "message": f"Pipeline error: {str(e)}"})

@app.post("/api/scrape-and-generate")
def start_pipeline(
    background_tasks: BackgroundTasks,
    url: str = Query(...),
    theme: str = Query("bauhaus_beige"),
    product_trigger: str = Query("product"),
    headed: bool = Query(False)
):
    background_tasks.add_task(run_pipeline, url, theme, product_trigger, headed)
    return {"message": "Pipeline execution started."}

@app.post("/api/save-listing")
def save_listing(req: ListingSaveRequest):
    try:
        product_output_dir = os.path.join("outputs", req.output_dir_name)
        if not os.path.exists(product_output_dir):
            raise HTTPException(status_code=404, detail="Listing output directory not found")
            
        metadata_path = os.path.join(product_output_dir, "metadata.json")
        updated_data = {
            "title": req.title,
            "description": req.description,
            "suggested_price": req.suggested_price,
            "tags": req.tags
        }
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(updated_data, f, indent=4, ensure_ascii=False)
            
        return {"status": "success", "message": "Listing data saved successfully!"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Mount directories
os.makedirs("outputs", exist_ok=True)
app.mount("/outputs", StaticFiles(directory="outputs"), name="outputs")

# Mount web static directory
static_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
