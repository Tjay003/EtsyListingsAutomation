import os
import json
import re
import time
from contextvars import ContextVar
from PIL import Image
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from typing import Any, Dict, List
from dotenv import load_dotenv
from src.copywriting_config import (
    build_active_policy,
    effective_limit,
    get_etsy_compatibility,
    get_listing_addons,
    get_tweak_instruction,
    normalize_copywriting_profile,
    risk_override_enabled,
)

# Optional OpenAI fallback import
try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

def generate_content_with_retry(client, model, contents, config=None, max_retries=3, initial_delay=2):
    """Wrapper around client.models.generate_content to handle rate limits and model fallback chain."""
    # Build list of fallback models
    primary_model = model or os.getenv("GEMINI_MODEL", "gemini-flash-latest")
    models_to_try = [primary_model]
    for backup in ["gemini-2.5-flash-lite", "gemini-flash-lite-latest", "gemini-flash-latest"]:
        if backup not in models_to_try:
            models_to_try.append(backup)
            
    last_error = None
    for model_name in models_to_try:
        delay = initial_delay
        print(f"API Attempt using model: {model_name}...")
        for attempt in range(max_retries):
            try:
                if config:
                    return client.models.generate_content(model=model_name, contents=contents, config=config)
                else:
                    return client.models.generate_content(model=model_name, contents=contents)
            except Exception as e:
                err_msg = str(e)
                # Catch 429 rate limit and 503 server overloaded
                is_rate_limit = "429" in err_msg or "resource_exhausted" in err_msg.lower()
                is_server_error = any(x in err_msg.lower() for x in ["503", "unavailable", "service_unavailable", "high demand"])
                
                if is_rate_limit or is_server_error:
                    wait_time = delay
                    match = re.search(r'retry in ([\d\.]+)s', err_msg)
                    if match:
                        wait_time = float(match.group(1)) + 0.5
                    print(f"API temporary failure (Rate limit/Server busy) on {model_name}. Retrying in {wait_time:.1f} seconds (Attempt {attempt + 1}/{max_retries})...")
                    time.sleep(wait_time)
                    delay *= 2
                    last_error = e
                else:
                    # If it's another error (like 404 Model Not Found), fall back immediately to next model in chain
                    print(f"Model {model_name} is unavailable or failed: {e}. Trying backup model...")
                    last_error = e
                    break
        else:
            print(f"Model {model_name} exhausted all {max_retries} retries. Trying backup model...")
            
    # If all fallback models failed, raise the last exception
    raise last_error

# Load key-value pairs from a local .env file if it exists
load_dotenv()

# Determine the Gemini model to use (defaulting to 1.5 Flash to stay within free tier limits)
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")

DEFAULT_OPENAI_MODEL = "gpt-4.1-mini"
COPYWRITING_MODEL_OPTIONS = [
    {
        "key": "gpt-4.1-mini",
        "label": "GPT-4.1 Mini",
        "description": "Default copywriting model. Strong instruction following with much better cost than full GPT-4.1.",
        "cost_tier": "Low",
        "recommended_for": "Daily listing copy, batch runs, and most tweak passes.",
    },
    {
        "key": "gpt-5.6-luna",
        "label": "GPT-5.6 Luna",
        "description": "Quality upgrade for harder copywriting jobs. Higher cost than GPT-4.1 Mini.",
        "cost_tier": "Medium",
        "recommended_for": "Important hero listings, stubborn descriptions, or copy that needs stronger reasoning.",
    },
]
_OPENAI_MODEL_KEYS = {model["key"] for model in COPYWRITING_MODEL_OPTIONS}
_OPENAI_MODEL_OVERRIDE = ContextVar("openai_model_override", default="")
_COPYWRITING_PROFILE_OVERRIDE = ContextVar("copywriting_profile_override", default=None)

def normalize_openai_model(model_key: str | None = None) -> str:
    requested = str(model_key or "").strip()
    if requested in _OPENAI_MODEL_KEYS:
        return requested
    if requested:
        return DEFAULT_OPENAI_MODEL
    env_model = str(os.getenv("OPENAI_MODEL") or "").strip()
    if env_model in _OPENAI_MODEL_KEYS:
        return env_model
    return DEFAULT_OPENAI_MODEL

def get_openai_model() -> str:
    override = _OPENAI_MODEL_OVERRIDE.get()
    return normalize_openai_model(override or os.getenv("OPENAI_MODEL") or DEFAULT_OPENAI_MODEL)

def set_openai_model_override(model_key: str | None = None):
    return _OPENAI_MODEL_OVERRIDE.set(normalize_openai_model(model_key))

def reset_openai_model_override(token):
    _OPENAI_MODEL_OVERRIDE.reset(token)

def get_copywriting_profile() -> dict:
    return normalize_copywriting_profile(_COPYWRITING_PROFILE_OVERRIDE.get())

def set_copywriting_profile_override(profile: dict | None = None):
    return _COPYWRITING_PROFILE_OVERRIDE.set(normalize_copywriting_profile(profile))

def reset_copywriting_profile_override(token):
    _COPYWRITING_PROFILE_OVERRIDE.reset(token)

def openai_model_uses_responses(model_key: str) -> bool:
    return model_key.startswith("gpt-5.6-")

def get_copywriting_model_options() -> dict:
    return {
        "default_model_key": DEFAULT_OPENAI_MODEL,
        "models": COPYWRITING_MODEL_OPTIONS,
    }

# Define the structured output format for the Etsy listing
class SEOStrategy(BaseModel):
    primary_product_noun: str = Field(default="", description="Plain product noun buyers would search, e.g. crossbody bag, ceramic mug")
    top_traits: List[str] = Field(default_factory=list, description="Product traits selected according to the active workspace profile")
    buyer_intents: List[str] = Field(default_factory=list, description="Realistic buyer intents or use cases for this product")
    audience: List[str] = Field(default_factory=list, description="Audience segments selected according to the active workspace profile")
    primary_keywords: List[str] = Field(default_factory=list, description="Most important buyer search phrases for Etsy")
    long_tail_keywords: List[str] = Field(default_factory=list, description="Specific multi-word phrases likely to convert")
    tag_keywords: List[str] = Field(default_factory=list, description="Candidate listing tag phrases")

class EtsyListing(BaseModel):
    title: str = Field(description="Marketplace listing title following the active workspace profile")
    description: str = Field(description="Product description following the active workspace profile")
    tags: List[str] = Field(description="Search tags following the active workspace profile")
    suggested_price: str = Field(description="Suggested retail price")
    category: str = Field(description="Marketplace category or category path")
    seo_strategy: SEOStrategy = Field(default_factory=SEOStrategy, description="Keyword and positioning strategy used to write the listing")
    seo_quality_score: int = Field(default=0, description="Deterministic SEO QA score from 0 to 100")
    seo_qa_notes: List[str] = Field(default_factory=list, description="Issues or warnings from deterministic SEO QA")
    repair_instructions: List[str] = Field(default_factory=list, description="Exact deterministic repairs required before the listing is publication-ready")
    needs_review: bool = Field(default=False, description="True when deterministic QA found issues that should be checked before publishing")
    review_reasons: List[str] = Field(default_factory=list, description="Short human review reasons")
    etsy_compatible: bool = Field(default=True, description="False when intentional overrides produce fields that do not fit Etsy limits")
    etsy_compatibility_issues: List[str] = Field(default_factory=list, description="Etsy field-limit warnings")
    enabled_risk_overrides: List[str] = Field(default_factory=list, description="Workspace risk overrides active for this listing")

class VisualSpecs(BaseModel):
    dimensions: str = Field(description="Measurements identified according to the active workspace profile")
    materials: str = Field(description="Materials identified according to the active workspace profile")
    colors: str = Field(description="Colors or variations identified according to the active workspace profile")
    capacity: str = Field(description="Capacity details identified according to the active workspace profile")
    other_specs: str = Field(description="Other useful specifications")
    visual_style: str = Field(description="Physical appearance and style description")

class VariationSpec(BaseModel):
    name: str = Field(description="The name or label of this variation (e.g., 'Color: Red', 'Beige')")
    size: str = Field(description="Size name identified for this variation")
    dimensions: str = Field(description="Measurements identified for this variation")
    other_details: str = Field(description="Other details identified for this variation")

class VariationListSpecs(BaseModel):
    variations: List[VariationSpec] = Field(description="List of detected specifications for each variation option in the exact same order as input")

class ReviewVerdict(BaseModel):
    approved: bool = Field(description="True if the listing follows the active workspace profile")
    title_issues: str = Field(description="Feedback/issues about title quality, or empty string if perfect")
    description_issues: str = Field(description="Feedback/issues about description (e.g., missing dimensions or incorrect facts), or empty string if perfect")
    tag_issues: str = Field(description="Feedback/issues about tags (length, quantity, search relevance), or empty string if perfect")
    seo_issues: str = Field(default="", description="Feedback/issues about Etsy search strategy, or empty string if perfect")

def get_genai_client():
    """Initialize and return the Google GenAI client, supporting API Key and GCP Vertex AI."""
    api_key = os.getenv("GEMINI_API_KEY")
    if api_key:
        # Use AI Studio API Key if provided
        return genai.Client(api_key=api_key)
        
    # Check if Vertex AI default configuration is set
    gcp_project = os.getenv("GCP_PROJECT") or os.getenv("GOOGLE_CLOUD_PROJECT")
    if gcp_project:
        print(f"Using Vertex AI with Project ID: {gcp_project}")
        return genai.Client(vertexai=True, project=gcp_project)
        
    print("Warning: Neither GEMINI_API_KEY nor GCP_PROJECT is set. Attempting default auth...")
    return genai.Client()

def get_openai_client():
    """Initialize and return the OpenAI client if key is present."""
    api_key = os.getenv("OPEN_AI_API_KEY") or os.getenv("OPENAI_API_KEY")
    if api_key and OpenAI:
        return OpenAI(api_key=api_key)
    return None

def _response_output_text(response) -> str:
    text = getattr(response, "output_text", "")
    if text:
        return text

    chunks = []
    for output in getattr(response, "output", []) or []:
        content = getattr(output, "content", None)
        if content is None and isinstance(output, dict):
            content = output.get("content")
        for block in content or []:
            block_type = getattr(block, "type", None) or (block.get("type") if isinstance(block, dict) else "")
            if block_type != "output_text":
                continue
            block_text = getattr(block, "text", None) or (block.get("text") if isinstance(block, dict) else "")
            if block_text:
                chunks.append(block_text)
    return "\n".join(chunks)

def _to_responses_content(content):
    if isinstance(content, str):
        return [{"type": "input_text", "text": content}]

    converted = []
    for item in content or []:
        if not isinstance(item, dict):
            converted.append({"type": "input_text", "text": str(item)})
            continue

        item_type = item.get("type")
        if item_type == "text":
            converted.append({"type": "input_text", "text": item.get("text", "")})
        elif item_type == "image_url":
            image_url = item.get("image_url", {})
            if isinstance(image_url, dict):
                image_url = image_url.get("url", "")
            if image_url:
                converted.append({
                    "type": "input_image",
                    "image_url": image_url,
                    "detail": "auto",
                })
    return converted or [{"type": "input_text", "text": ""}]

def openai_generate_content(openai_client, content, json_object: bool = False, max_tokens: int | None = None) -> str:
    """Generate text with the selected OpenAI model, using Responses for newer GPT-5.6 models."""
    openai_model = get_openai_model()

    if openai_model_uses_responses(openai_model):
        response_kwargs = {
            "model": openai_model,
            "input": [{
                "role": "user",
                "content": _to_responses_content(content),
            }],
        }
        if json_object:
            response_kwargs["text"] = {"format": {"type": "json_object"}}
        if max_tokens:
            response_kwargs["max_output_tokens"] = max_tokens
        response = openai_client.responses.create(**response_kwargs)
        return _response_output_text(response)

    completion_kwargs = {
        "model": openai_model,
        "messages": [{"role": "user", "content": content}],
    }
    if json_object:
        completion_kwargs["response_format"] = {"type": "json_object"}
    if max_tokens:
        completion_kwargs["max_tokens"] = max_tokens
    response = openai_client.chat.completions.create(**completion_kwargs)
    return response.choices[0].message.content

def pil_image_to_base64_data_uri(pil_img):
    """Convert a PIL Image to a base64 JPEG data URI for OpenAI multimodal vision input."""
    import base64
    from io import BytesIO
    buffered = BytesIO()
    # Save as JPEG with 85 quality for compression and speed
    pil_img.convert("RGB").save(buffered, format="JPEG", quality=85)
    img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
    return f"data:image/jpeg;base64,{img_str}"

def generate_description_from_images(image_paths, client=None):
    """Scan product images using multimodal Gemini or OpenAI to generate product description."""
    if not client:
        client = get_genai_client()
        
    print("No detailed text description found. Scanning product images visually...")
    pil_images = []
    for path in image_paths:
        if os.path.exists(path):
            try:
                pil_images.append(Image.open(path))
            except Exception as e:
                print(f"Could not load image {path} for analysis: {e}")
                
    if not pil_images:
        return "No visual description available (no images downloaded)."
        
    prompt = (
        f"{build_active_policy(get_copywriting_profile(), 'visual_facts')}\n\n"
        "Analyze these product images and compile a detailed description of the product. "
        "IMPORTANT: If any of these images contain a size chart, dimension diagram, measurement overlay, "
        "or specifications table, look at it closely, read the text inside it, and extract the exact "
        "measurements (such as height, width, length, strap drop, weight capacity, etc.) precisely. "
        "Do not approximate if the exact numbers are printed on any of the images. "
        "Additionally, identify the materials, colors, texture, style details, design highlights, and "
        "any brand names or printed logos. Return a detailed and highly accurate textual summary."
    )
    
    # Try OpenAI first if configured
    openai_client = get_openai_client()
    if openai_client:
        print("Using OpenAI to scan product images visually...")
        try:
            messages = [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": prompt
                        }
                    ]
                }
            ]
            for img in pil_images:
                try:
                    data_uri = pil_image_to_base64_data_uri(img)
                    messages[0]["content"].append({
                        "type": "image_url",
                        "image_url": {"url": data_uri}
                    })
                except Exception as e:
                    print(f"Failed to convert PIL image for OpenAI: {e}")
            
            raw_text = openai_generate_content(openai_client, messages[0]["content"], max_tokens=1000)
            print("Visual description generated successfully via OpenAI.")
            return raw_text
        except Exception as e:
            print(f"Error during OpenAI visual description generation: {e}. Falling back to Gemini...")
            
    try:
        response = generate_content_with_retry(
            client=client,
            model=GEMINI_MODEL,
            contents=[prompt, *pil_images]
        )
        print("Visual description generated successfully.")
        return response.text
    except Exception as e:
        print(f"Error during multimodal description generation: {e}")
        return "Error analyzing product images visually."

def extract_visual_specs(image_paths, client=None):
    """Scan description, main, and variation images visually to extract hard facts, specifications, and dimensions.
    Adheres to strict confidence rules - no guessing.
    """
    if not client:
        client = get_genai_client()
        
    print(f"Extracting visual specs from {len(image_paths)} images...")
    pil_images = []
    for path in image_paths:
        if os.path.exists(path):
            try:
                # Open and ensure small size for speed/token economy
                img = Image.open(path)
                # Keep aspect ratio but cap max dimension to 800px to avoid heavy token usage
                img.thumbnail((800, 800))
                pil_images.append(img)
            except Exception as e:
                print(f"Could not load image {path} for spec extraction: {e}")
                
    if not pil_images:
        print("No images available for visual spec extraction.")
        return {}
        
    prompt = (
        f"{build_active_policy(get_copywriting_profile(), 'visual_facts')}\n\n"
        "Analyze these product images carefully and return dimensions, materials, colors, capacity, "
        "other specifications, and visual style according to the active workspace rules.\n"
        "\nOutput your response strictly as a JSON object matching the requested schema."
    )
    
    # Try OpenAI first if configured
    openai_client = get_openai_client()
    if openai_client:
        print("Using OpenAI to extract visual specs...")
        try:
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt}
                    ]
                }
            ]
            for img in pil_images:
                try:
                    data_uri = pil_image_to_base64_data_uri(img)
                    messages[0]["content"].append({
                        "type": "image_url",
                        "image_url": {"url": data_uri}
                    })
                except Exception as e:
                    print(f"Failed to convert PIL image for OpenAI: {e}")
            
            raw_text = openai_generate_content(openai_client, messages[0]["content"], json_object=True, max_tokens=1000)
            return json.loads(raw_text)
        except Exception as e:
            print(f"Error during OpenAI visual spec extraction: {e}. Falling back to Gemini...")
            
    try:
        response = generate_content_with_retry(
            client=client,
            model=GEMINI_MODEL,
            contents=[prompt, *pil_images],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=VisualSpecs,
            )
        )
        return json.loads(response.text)
    except Exception as e:
        print(f"Error during Gemini visual spec extraction: {e}")
        return {}

def extract_variation_specs(variations, product_dir, overall_specs, scraped_desc, client=None):
    """Scan variation images and names to extract sizes, dimensions, and specifications for each variation.
    Uses overall size charts/specifications and the variation's name and image as context.
    """
    if not client:
        client = get_genai_client()

    print(f"Extracting variation specs for {len(variations)} variations...")

    # Build prompt with overall product context
    specs_part = json.dumps(overall_specs, indent=2) if overall_specs else "None extracted"
    desc_part = scraped_desc or "None provided"

    prompt = (
        f"{build_active_policy(get_copywriting_profile(), 'variation_specs')}\n\n"
        "Analyze the variation options for this product.\n"
        "Your task is to detect the specific size and measurements/dimensions for EACH variation listed below.\n\n"
        "CONTEXT:\n"
        f"1. Overall Product Specifications & Size Charts:\n{specs_part}\n\n"
        f"2. Product Text Description:\n{desc_part}\n\n"
        "VARIATION LIST:\n"
    )

    for idx, var in enumerate(variations):
        name = var.get("name") if isinstance(var, dict) else f"Variation {idx+1}"
        if isinstance(var, dict) and (var.get("alt") or var.get("title")):
            name = f"{var.get('alt') or var.get('title')}"
        prompt += f"- Index {idx}: Name/Label = '{name}'\n"

    prompt += (
        "\nMAPPING RULES:\n"
        "1. Order: You MUST return the variation specifications in the exact same index order as the input list.\n"
        "2. Name Match: Set the 'name' field in each result item to the corresponding Name/Label from the variation list.\n"
        "3. Size Extraction: Look at the variation's name/label. If it contains a size indicator (e.g. 'S', 'M', 'L', 'XL', '20cm', 'small'), set the 'size' field.\n"
        "4. Dimension Matching: Cross-reference the variation's size name with any size charts in the CONTEXT. If the size chart lists measurements for that size (e.g. S: 38x28cm), extract and assign those measurements to the 'dimensions' field of that variation.\n"
        "5. Image Extraction: Below are the variation images. If a variation image itself contains printed text displaying specific sizes, dimensions, or measurements (e.g. a diagram showing the size), extract those measurements for that variation.\n"
        "6. Follow the active factual and inference policies when information is uncertain.\n"
        "\nOutput your response strictly as a JSON object matching the requested schema."
    )

    contents = [prompt]

    # Load variation images and insert them in the contents with text separators
    loaded_images = {}
    for idx, var in enumerate(variations):
        local_path = None
        if isinstance(var, dict):
            local_path = var.get("local_path")
        
        if local_path:
            full_path = os.path.join(product_dir, local_path)
            if os.path.exists(full_path):
                try:
                    img = Image.open(full_path)
                    img.thumbnail((800, 800))
                    # Store to prevent loading the same path multiple times if duplicates exist
                    loaded_images[local_path] = img
                except Exception as e:
                    print(f"Could not load variation image {full_path}: {e}")

    # Build multimodal content payload
    for idx, var in enumerate(variations):
        local_path = var.get("local_path") if isinstance(var, dict) else None
        if local_path and local_path in loaded_images:
            contents.append(f"\n--- Image for Variation Index {idx} ---")
            contents.append(loaded_images[local_path])

    # Try OpenAI first if configured
    openai_client = get_openai_client()
    if openai_client:
        print("Using OpenAI to extract variation specs...")
        try:
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt}
                    ]
                }
            ]
            for idx, var in enumerate(variations):
                local_path = var.get("local_path") if isinstance(var, dict) else None
                if local_path and local_path in loaded_images:
                    messages[0]["content"].append({"type": "text", "text": f"\n--- Image for Variation Index {idx} ---"})
                    data_uri = pil_image_to_base64_data_uri(loaded_images[local_path])
                    messages[0]["content"].append({
                        "type": "image_url",
                        "image_url": {"url": data_uri}
                    })

            raw_text = openai_generate_content(openai_client, messages[0]["content"], json_object=True, max_tokens=1500)
            res_dict = json.loads(raw_text)
            return res_dict.get("variations", [])
        except Exception as e:
            print(f"Error during OpenAI variation spec extraction: {e}. Falling back to Gemini...")

    try:
        response = generate_content_with_retry(
            client=client,
            model=GEMINI_MODEL,
            contents=contents,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=VariationListSpecs,
            )
        )
        res_dict = json.loads(response.text)
        return res_dict.get("variations", [])
    except Exception as e:
        print(f"Error during Gemini variation spec extraction: {e}")
        # Return fallback empty specs for each input variation to keep things robust
        fallback = []
        for idx, var in enumerate(variations):
            name = ""
            if isinstance(var, dict):
                name = var.get("alt") or var.get("title") or var.get("name") or f"Variation {idx+1}"
            else:
                name = f"Variation {idx+1}"
            fallback.append({
                "name": name,
                "size": "",
                "dimensions": "",
                "other_details": ""
            })
        return fallback

def clean_tags(tags, client):
    """Normalize tags according to the active workspace profile."""
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    if not isinstance(tags, list):
        tags = []
        
    profile = get_copywriting_profile()
    max_chars = effective_limit(profile, "etsy_tag_length")
    target_count = effective_limit(profile, "etsy_tag_count")
    preserve_long_tags = risk_override_enabled(profile, "etsy_tag_length")
    openai_client = get_openai_client()
    cleaned = []
    for tag in tags:
        tag = tag.strip().lower()
        if len(tag) <= max_chars or preserve_long_tags:
            cleaned.append(tag)
        else:
            print(f"Tag too long ({len(tag)} chars): '{tag}'. Condensing...")
            
            # Try OpenAI first if configured
            if openai_client:
                try:
                    prompt = f"Shorten this keyword phrase to be under {max_chars} characters (including spaces) for Etsy tags, keeping its search relevance. Output ONLY the shortened phrase, no quotes, no extra words:\n{tag}"
                    short_tag = openai_generate_content(openai_client, prompt, max_tokens=20).strip().replace('"', '').replace("'", "")
                    if len(short_tag) <= max_chars:
                        cleaned.append(short_tag)
                        print(f"Condensed tag via OpenAI: '{tag}' -> '{short_tag}'")
                        continue
                except Exception as e:
                    print(f"Error condensing tag '{tag}' via OpenAI: {e}. Falling back to Gemini...")
            
            # Fallback to Gemini
            try:
                prompt = f"Shorten this keyword phrase to be under {max_chars} characters (including spaces) for Etsy tags, keeping its search relevance. Output ONLY the shortened phrase, no quotes, no extra words:\n{tag}"
                response = generate_content_with_retry(
                    client=client,
                    model=GEMINI_MODEL,
                    contents=prompt
                )
                short_tag = response.text.strip().replace('"', '').replace("'", "")
                if len(short_tag) <= max_chars:
                    cleaned.append(short_tag)
                    print(f"Condensed tag: '{tag}' -> '{short_tag}'")
                else:
                    # Hard fallback: truncate
                    truncated = tag[:max_chars].strip()
                    cleaned.append(truncated)
                    print(f"Fallback truncate tag: '{tag}' -> '{truncated}'")
            except Exception as e:
                print(f"Error condensing tag '{tag}': {e}")
                cleaned.append(tag[:max_chars].strip())
                
    # Deduplicate and limit to 13
    seen = set()
    final_tags = []
    for t in cleaned:
        if t not in seen and t:
            seen.add(t)
            final_tags.append(t)
            
    return final_tags[:target_count]

TAG_COUNT = 13
MAX_ETSY_TAG_CHARS = 20
MAX_ETSY_TITLE_CHARS = 140
MIN_MARKETPLACE_TITLE_CHARS = 80
IDEAL_MARKETPLACE_TITLE_WORDS = 18
MAX_MARKETPLACE_TITLE_PHRASES = 3
GOOGLE_TITLE_CHARS = 60
GOOGLE_DESCRIPTION_CHARS = 155
PINTEREST_TITLE_CHARS = 100
PINTEREST_DESCRIPTION_CHARS = 500

PROHIBITED_LISTING_TERMS = [
    "aliexpress",
    "china",
    "factory",
    "wholesale",
    "dropship",
    "dropshipping",
    "bulk order",
    "bulk pricing",
    "bulk sale",
    "mass production",
    "shipping tracking",
]

SUBJECTIVE_TITLE_TERMS = [
    "beautiful",
    "perfect",
    "wonderful",
    "amazing",
    "best",
    "must have",
    "luxury",
    "designer",
]

RISKY_UNSUPPORTED_CLAIMS = {
    "handmade": ("handmade", "hand made", "hand-crafted", "handcrafted"),
    "eco-friendly": ("eco-friendly", "eco friendly", "sustainable", "recycled"),
    "genuine leather": ("genuine leather", "real leather", "leather"),
    "luxury": ("luxury", "designer"),
}

DESCRIPTION_HYPE_TERMS = [
    "luxury",
    "luxurious",
    "designer",
    "perfect",
    "beautiful",
    "amazing",
    "must-have",
    "must have",
]

TRADEMARK_RISK_TERMS = [
    "pikachu",
    "pokemon",
    "disney",
    "sanrio",
    "hello kitty",
    "barbie",
    "nike",
    "adidas",
    "louis vuitton",
    "chanel",
    "gucci",
]

STOP_WORDS = {
    "and", "for", "with", "the", "a", "an", "of", "to", "in", "on", "by",
    "from", "your", "my", "our", "this", "that", "new", "hot", "sale"
}

def _model_to_dict(value):
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    return value

def _phrase_text(value):
    value = _model_to_dict(value)
    if isinstance(value, dict):
        for key in ("keyword", "phrase", "name", "label", "value", "text"):
            if value.get(key):
                return str(value.get(key)).strip()
        return " ".join(str(v).strip() for v in value.values() if str(v).strip())
    return str(value).strip()

def _strip_variation_label(text):
    clean = str(text or "")
    clean = re.sub(r"\b(color|size|style|option|variant|trait|value)\s*:\s*", "", clean, flags=re.IGNORECASE)
    clean = re.sub(r"[{}'\"`]+", "", clean)
    return re.sub(r"\s+", " ", clean).strip(" ,-")

def _as_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return [_strip_variation_label(_phrase_text(v)) for v in value if _strip_variation_label(_phrase_text(v))]
    if isinstance(value, str):
        return [_strip_variation_label(v) for v in re.split(r"[,;\n]+", value) if _strip_variation_label(v)]
    phrase = _strip_variation_label(_phrase_text(value))
    return [phrase] if phrase else []

def _dedupe_preserve_order(items):
    seen = set()
    result = []
    for item in items:
        clean = _strip_variation_label(_phrase_text(item))
        clean = re.sub(r"\s+", " ", clean.strip())
        if not clean:
            continue
        key = clean.lower()
        if key not in seen:
            seen.add(key)
            result.append(clean)
    return result

def _strip_prohibited_terms(text):
    if risk_override_enabled(get_copywriting_profile(), "supplier_terms"):
        return str(text or "").strip()
    clean = str(text or "")
    for term in PROHIBITED_LISTING_TERMS:
        clean = re.sub(re.escape(term), "", clean, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", clean).strip()

def _strip_subjective_title_terms(text):
    profile = get_copywriting_profile()
    if (
        risk_override_enabled(profile, "promotional_language")
        or risk_override_enabled(profile, "title_style")
    ):
        return str(text or "").strip()
    clean = str(text or "")
    for term in SUBJECTIVE_TITLE_TERMS:
        clean = re.sub(rf"\b{re.escape(term)}\b", "", clean, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", clean).strip(" ,-")

def _strip_description_hype(text):
    if risk_override_enabled(get_copywriting_profile(), "promotional_language"):
        return str(text or "").strip()
    clean = str(text or "")
    replacements = {
        r"\bperfect\s+for\b": "suited for",
        r"\bperfect\s+companion\b": "practical option",
        r"\bperfect\s+blend\b": "practical blend",
        r"\bmust-have\b": "useful",
        r"\bmust\s+have\b": "useful",
    }
    for pattern, replacement in replacements.items():
        clean = re.sub(pattern, replacement, clean, flags=re.IGNORECASE)
    for term in DESCRIPTION_HYPE_TERMS:
        clean = re.sub(rf"\b{re.escape(term)}\b", "", clean, flags=re.IGNORECASE)
    clean = re.sub(r"\b(is|are|making it|makes it)\s+for\b", r"\1 suited for", clean, flags=re.IGNORECASE)
    clean = re.sub(r"[ \t]+([,.;:])", r"\1", clean)
    clean = re.sub(r"[ \t]+", " ", clean)
    clean = re.sub(r"[ \t]*\n[ \t]*", "\n", clean)
    return re.sub(r"\n{3,}", "\n\n", clean).strip()

def _format_listing_description(description):
    """Normalize Etsy-safe description layout without collapsing paragraphs."""
    clean = str(description or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not clean:
        return ""

    clean = re.sub(r"\*\*(.*?)\*\*", r"\1", clean)
    clean = re.sub(r"__(.*?)__", r"\1", clean)
    clean = re.sub(r"(?m)^\s*[\*\u2022]\s+", "- ", clean)
    clean = re.sub(r"(?m)^\s*[-]\s+", "- ", clean)
    clean = re.sub(r"\s+[\*\u2022]\s+(?=[A-Za-z0-9])", "\n- ", clean)
    clean = clean.replace("*", "").replace("_", "")
    clean = re.sub(r"\s+-\s+(?=[A-Za-z0-9][A-Za-z0-9 /&()'-]{1,45}:)", "\n- ", clean)
    clean = re.sub(r"\s*(product details)\s*:\s*", "\n\nPRODUCT DETAILS:\n", clean, flags=re.IGNORECASE)
    clean = re.sub(
        r"\s+(please (?:refer|review)|refer to)\b",
        r"\n\nNOTE:\n\1",
        clean,
        flags=re.IGNORECASE,
    )

    lines = []
    for raw_line in clean.split("\n"):
        line = re.sub(r"[ \t]+", " ", raw_line).strip()
        if not line:
            if lines and lines[-1] != "":
                lines.append("")
            continue
        if line.upper() == "PRODUCT DETAILS:":
            line = "PRODUCT DETAILS:"
            if lines and lines[-1] != "":
                lines.append("")
        elif line.upper() == "NOTE:":
            line = "NOTE:"
            if lines and lines[-1] != "":
                lines.append("")
        lines.append(line)

    clean = "\n".join(lines).strip()
    clean = re.sub(r"\n{3,}", "\n\n", clean)
    return clean

def _apply_description_policy(description):
    if risk_override_enabled(get_copywriting_profile(), "description_structure"):
        clean = str(description or "").replace("\r\n", "\n").replace("\r", "\n").strip()
        return re.sub(r"\n{4,}", "\n\n\n", clean)
    return _format_listing_description(description)

def _trim_at_word(text, limit):
    clean = re.sub(r"\s+", " ", str(text or "")).strip(" |,-")
    if len(clean) <= limit:
        return clean
    trimmed = clean[:limit].rsplit(" ", 1)[0].strip(" |,-")
    return trimmed or clean[:limit].strip(" |,-")

def _first_sentence(text):
    clean = re.sub(r"\s+", " ", str(text or "")).strip()
    if not clean:
        return ""
    match = re.search(r"(.+?[.!?])\s", clean + " ")
    return match.group(1).strip() if match else clean

def _format_image_facts(image_facts):
    if not image_facts:
        return "None extracted"
    lines = [f"{k.upper()}: {v}" for k, v in image_facts.items() if v]
    return "\n".join(lines) if lines else "None extracted"

def _format_variation_specs(variation_specs):
    if not variation_specs:
        return "None extracted"
    lines = []
    for var in variation_specs:
        if not isinstance(var, dict):
            continue
        details = [
            f"Size = {var.get('size') or 'N/A'}",
            f"Dimensions = {var.get('dimensions') or 'N/A'}",
        ]
        other = var.get("other_details")
        if other:
            details.append(f"Details = {other}")
        lines.append(f"- {var.get('name')}: {', '.join(details)}")
    return "\n".join(lines) if lines else "None extracted"

def _guess_primary_product_noun(title, description):
    text = f"{title} {description}".lower()
    product_markers = [
        "crossbody bag", "shoulder bag", "tote bag", "handbag", "backpack", "wallet",
        "necklace", "bracelet", "earrings", "ring", "dress", "shirt", "jacket",
        "mug", "cup", "lamp", "vase", "organizer", "kitchen tool", "spatula",
        "knife", "blanket", "pillow", "rug", "phone case", "pet collar"
    ]
    for marker in product_markers:
        if marker in text:
            return marker
    words = [
        word for word in re.findall(r"[a-z0-9]+", title.lower())
        if len(word) > 2 and word not in STOP_WORDS
    ]
    return " ".join(words[:2]) if words else "product"

def _fallback_seo_strategy(title, description, image_facts=None, variation_specs=None):
    primary_noun = _guess_primary_product_noun(title, description)
    fact_terms = []
    for value in (image_facts or {}).values():
        fact_terms.extend(re.findall(r"[A-Za-z][A-Za-z0-9 -]{2,24}", str(value)))
    title_terms = [
        word for word in re.findall(r"[A-Za-z0-9][A-Za-z0-9 -]{2,24}", str(title))
        if word.lower() not in STOP_WORDS
    ]
    candidates = _dedupe_preserve_order([primary_noun, *title_terms[:8], *fact_terms[:8]])
    return {
        "primary_product_noun": primary_noun,
        "top_traits": candidates[1:6],
        "buyer_intents": ["everyday use"],
        "audience": [],
        "primary_keywords": candidates[:6],
        "long_tail_keywords": candidates[:8],
        "tag_keywords": candidates[:18],
    }

def _coerce_seo_strategy(strategy, title="", description="", image_facts=None, variation_specs=None):
    if isinstance(strategy, SEOStrategy):
        data = _model_to_dict(strategy)
    elif isinstance(strategy, dict):
        data = dict(strategy)
    else:
        data = {}

    fallback = _fallback_seo_strategy(title, description, image_facts, variation_specs)
    for key, value in fallback.items():
        if key == "primary_product_noun":
            data[key] = str(data.get(key) or value).strip()
        else:
            data[key] = _dedupe_preserve_order(_as_list(data.get(key)) or value)
    return data

def build_seo_strategy(title, description, image_facts=None, variation_specs=None, client=None):
    """Create a product-specific keyword strategy before drafting the listing."""
    if not client:
        client = get_genai_client()

    facts_str = _format_image_facts(image_facts)
    var_str = _format_variation_specs(variation_specs)
    prompt = (
        f"{build_active_policy(get_copywriting_profile(), 'seo_strategy')}\n\n"
        "Create the product-specific SEO strategy requested by the active workspace profile.\n\n"
        f"Original Title: {title}\n"
        f"Scraped Description/Info: {description}\n\n"
        "Image Facts:\n"
        f"{facts_str}\n\n"
        "Variation Specifications:\n"
        f"{var_str}\n\n"
        "Output strictly as JSON matching the SEOStrategy schema."
    )

    openai_client = get_openai_client()
    if openai_client:
        try:
            raw_text = openai_generate_content(openai_client, prompt, json_object=True, max_tokens=900)
            return _coerce_seo_strategy(
                json.loads(raw_text),
                title,
                description,
                image_facts,
                variation_specs,
            )
        except Exception as e:
            print(f"Error building SEO strategy via OpenAI: {e}. Falling back to Gemini...")

    try:
        response = generate_content_with_retry(
            client=client,
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=SEOStrategy,
            )
        )
        return _coerce_seo_strategy(
            json.loads(response.text),
            title,
            description,
            image_facts,
            variation_specs,
        )
    except Exception as e:
        print(f"Error building SEO strategy: {e}")
        return _fallback_seo_strategy(title, description, image_facts, variation_specs)

def _tag_phrase_candidates(listing_data, seo_strategy):
    strategy = _coerce_seo_strategy(seo_strategy)
    candidates = []
    candidates.extend(_as_list(listing_data.get("tags")))
    for key in [
        "tag_keywords",
        "primary_keywords",
        "long_tail_keywords",
        "top_traits",
        "buyer_intents",
    ]:
        candidates.extend(_as_list(strategy.get(key)))

    noun = strategy.get("primary_product_noun")
    if noun:
        candidates.append(noun)
        for trait in _as_list(strategy.get("top_traits"))[:6]:
            candidates.append(f"{trait} {noun}")
            candidates.append(f"{noun} {trait}")
    return candidates

def _simple_tag_cleanup(tag):
    profile = get_copywriting_profile()
    max_chars = effective_limit(profile, "etsy_tag_length")
    preserve_long_tags = risk_override_enabled(profile, "etsy_tag_length")
    clean = _strip_description_hype(_strip_prohibited_terms(tag)).lower()
    clean = re.sub(r"[^a-z0-9 &-]", " ", clean)
    clean = re.sub(r"\s+", " ", clean).strip(" -&")
    if len(clean) <= max_chars or preserve_long_tags:
        return clean
    words = [word for word in clean.split() if word not in STOP_WORDS]
    shortened = " ".join(words)
    if len(shortened) <= max_chars:
        return shortened
    while words and len(" ".join(words)) > max_chars:
        words.pop()
    return " ".join(words).strip() or clean[:max_chars].strip()

def complete_tags(listing_data, seo_strategy, client):
    profile = get_copywriting_profile()
    target_count = effective_limit(profile, "etsy_tag_count")
    raw_candidates = _tag_phrase_candidates(listing_data, seo_strategy)
    candidate_tags = []
    for candidate in raw_candidates:
        cleaned = _simple_tag_cleanup(candidate)
        if cleaned:
            candidate_tags.append(cleaned)

    cleaned_tags = clean_tags(candidate_tags, client)
    if len(cleaned_tags) >= target_count:
        return cleaned_tags[:target_count]

    strategy = _coerce_seo_strategy(seo_strategy)
    noun = _simple_tag_cleanup(strategy.get("primary_product_noun") or "product")
    fallback_tags = [
        noun,
        f"{noun} gift",
        f"{noun} idea",
        f"{noun} style",
        "boutique find",
        "everyday item",
        "minimalist gift",
        "modern style",
        "useful gift",
        "gift idea",
        "unique find",
        "curated gift",
        "daily use",
    ]
    for tag in fallback_tags:
        cleaned = _simple_tag_cleanup(tag)
        if cleaned and cleaned not in cleaned_tags:
            cleaned_tags.append(cleaned)
        if len(cleaned_tags) >= target_count:
            break
    return cleaned_tags[:target_count]

def _clean_listing_title(title):
    profile = get_copywriting_profile()
    title_limit = effective_limit(profile, "etsy_title_limit")
    preserve_long_title = risk_override_enabled(profile, "etsy_title_limit")
    clean = _strip_prohibited_terms(title)
    clean = _strip_variation_label(clean)
    clean = re.sub(r"\s*[\|/]\s*", ", ", clean)
    clean = re.sub(r"\s+", " ", clean).strip(" ,-")
    return clean if preserve_long_title else _trim_at_word(clean, title_limit)

def _title_word_count(title):
    return len(re.findall(r"[A-Za-z0-9]+", str(title or "")))

def _title_phrase_count(title):
    return len([part for part in re.split(r"\s*,\s*|\s+:\s+", str(title or "")) if part.strip()])

def _title_has_variation_leakage(title):
    clean = str(title or "")
    return bool(
        re.search(r"\bcolor\s*:", clean, flags=re.IGNORECASE)
        or len(re.findall(r"\bcolor\s*:", clean, flags=re.IGNORECASE)) > 1
        or re.search(r"\b(size|style|option|variant)\s*:", clean, flags=re.IGNORECASE)
    )

def _title_case_phrase(phrase):
    phrase = re.sub(r"\s+", " ", str(phrase or "")).strip(" ,-")
    if not phrase:
        return ""
    return " ".join(word if word.isupper() else word.capitalize() for word in phrase.split())

def _is_keyword_stuffed_title(title):
    clean = str(title or "")
    words = re.findall(r"[A-Za-z0-9]+", clean.lower())
    meaningful = [word for word in words if word not in STOP_WORDS and len(word) > 2]
    repeated_words = len(meaningful) - len(set(meaningful))
    return (
        "|" in clean
        or _title_word_count(clean) > IDEAL_MARKETPLACE_TITLE_WORDS + 3
        or _title_phrase_count(clean) > MAX_MARKETPLACE_TITLE_PHRASES
        or repeated_words > 2
    )

def _phrase_is_useful_title_chunk(phrase, existing_chunks):
    clean = re.sub(r"\s+", " ", str(phrase or "")).strip(" ,-")
    if not clean or _title_word_count(clean) > 5:
        return False
    clean_lower = clean.lower()
    existing_text = " ".join(existing_chunks).lower()
    if clean_lower in existing_text:
        return False
    useful_words = [word for word in re.findall(r"[A-Za-z0-9]+", clean_lower) if word not in STOP_WORDS]
    if not useful_words:
        return False
    return True

def _compose_marketplace_title(original_title, description, seo_strategy):
    profile = get_copywriting_profile()
    strategy = _coerce_seo_strategy(seo_strategy, original_title, description)
    noun = strategy.get("primary_product_noun") or _guess_primary_product_noun(original_title, description)
    noun = _strip_subjective_title_terms(_strip_prohibited_terms(noun))
    noun = re.sub(r"\s+", " ", noun).strip(" ,-") or "Product"

    candidate_chunks = _dedupe_preserve_order(
        _as_list(strategy.get("top_traits"))
        + _as_list(strategy.get("buyer_intents"))
        + _as_list(strategy.get("long_tail_keywords"))
        + _as_list(strategy.get("primary_keywords"))
    )

    chunks = []
    primary_trait = ""
    for candidate in candidate_chunks:
        candidate = _strip_subjective_title_terms(_strip_prohibited_terms(candidate))
        if _phrase_is_useful_title_chunk(candidate, []) and noun.lower() not in candidate.lower():
            primary_trait = candidate
            break

    primary = f"{primary_trait} {noun}".strip() if primary_trait else noun
    chunks.append(_title_case_phrase(primary))

    for candidate in candidate_chunks:
        candidate = _strip_subjective_title_terms(_strip_prohibited_terms(candidate))
        if not _phrase_is_useful_title_chunk(candidate, chunks):
            continue
        if len(chunks) >= MAX_MARKETPLACE_TITLE_PHRASES:
            break
        chunks.append(_title_case_phrase(candidate))

    title = ", ".join(chunks)
    if risk_override_enabled(profile, "etsy_title_limit"):
        return title
    return _trim_at_word(title, effective_limit(profile, "etsy_title_limit"))

def _clean_marketplace_title(title, description, seo_strategy):
    profile = get_copywriting_profile()
    title_limit = effective_limit(profile, "etsy_title_limit")
    if risk_override_enabled(profile, "title_style"):
        clean = _clean_listing_title(title)
        return clean if risk_override_enabled(profile, "etsy_title_limit") else _trim_at_word(clean, title_limit)
    clean = _strip_subjective_title_terms(_clean_listing_title(title))
    if (
        not clean
        or _is_keyword_stuffed_title(clean)
        or _title_has_variation_leakage(clean)
        or len(clean) < MIN_MARKETPLACE_TITLE_CHARS
    ):
        rebuilt = _compose_marketplace_title(clean or title, description, seo_strategy)
        if rebuilt:
            clean = rebuilt
    return clean if risk_override_enabled(profile, "etsy_title_limit") else _trim_at_word(clean, title_limit)

def _normalize_listing_category(listing_data, seo_strategy=None):
    inferred = _infer_listing_category(listing_data, seo_strategy)
    current = str(listing_data.get("category") or "").strip()
    if risk_override_enabled(get_copywriting_profile(), "category_inference") and current:
        return current
    normalized_current = current.lower().replace("&amp;", "&")
    product_text = " ".join([
        listing_data.get("title", ""),
        listing_data.get("description", ""),
        inferred,
        json.dumps(_coerce_seo_strategy(seo_strategy or listing_data.get("seo_strategy"))),
    ]).lower()
    category_text = " ".join([
        listing_data.get("title", ""),
        listing_data.get("description", ""),
        current,
        inferred,
        json.dumps(_coerce_seo_strategy(seo_strategy or listing_data.get("seo_strategy"))),
    ]).lower()

    if any(term in category_text for term in ["backpack", "bookbag", "rucksack"]):
        return "Bags & Purses > Backpacks"
    if "diaper bag" in category_text or "maternity bag" in category_text:
        return "Bags & Purses > Diaper Bags"
    if any(term in product_text for term in ["tote", "handbag", "crossbody", "shoulder bag", "satchel", "messenger bag"]):
        return "Bags & Purses > Handbags"
    if any(term in product_text for term in ["wallet", "card holder", "coin purse"]):
        return "Bags & Purses > Wallets & Money Clips"
    if any(term in product_text for term in ["purse", "bag"]):
        return "Bags & Purses > Handbags"

    vague_categories = {
        "",
        "not categorized",
        "uncategorized",
        "none",
        "n/a",
        "handbags",
        "handbags & purses",
        "bags & purses",
    }
    if normalized_current in vague_categories:
        return inferred
    return current or inferred

def _parse_price_value(value):
    match = re.search(r"(\d+(?:\.\d{1,2})?)", str(value or ""))
    return float(match.group(1)) if match else None

def _format_usd_price(value):
    return f"${float(value):.2f}"

def _estimate_price_from_listing(listing_data, seo_strategy=None):
    text = " ".join([
        listing_data.get("title", ""),
        listing_data.get("description", ""),
        listing_data.get("category", ""),
        json.dumps(_coerce_seo_strategy(seo_strategy or listing_data.get("seo_strategy"))),
    ]).lower()
    if "diaper bag" in text:
        return 39.99
    if "backpack" in text:
        return 29.99
    if "tote" in text or "crossbody" in text or "shoulder bag" in text or "handbag" in text:
        return 26.99
    if "wallet" in text or "coin purse" in text:
        return 18.99
    return 24.99

def _coerce_suggested_price(listing_data, source_price="", seo_strategy=None):
    current = _parse_price_value(listing_data.get("suggested_price"))
    if current and current > 0:
        return _format_usd_price(current)

    source = _parse_price_value(source_price)
    if source and source > 0:
        multiplier = 2.4 if risk_override_enabled(get_copywriting_profile(), "pricing_strategy") else 1.8
        floor = 12 if risk_override_enabled(get_copywriting_profile(), "pricing_strategy") else 8
        return _format_usd_price(max(source * multiplier, source + floor))

    return _format_usd_price(_estimate_price_from_listing(listing_data, seo_strategy))

def _source_supports_claim(source_context, terms):
    source_lower = str(source_context or "").lower()
    return any(term in source_lower for term in terms)

def _infer_listing_category(listing_data, seo_strategy=None):
    strategy = _coerce_seo_strategy(seo_strategy or listing_data.get("seo_strategy"))
    text = " ".join([
        listing_data.get("title", ""),
        listing_data.get("description", ""),
        strategy.get("primary_product_noun", ""),
        " ".join(_as_list(strategy.get("primary_keywords"))[:5]),
    ]).lower()

    category_rules = [
        (("crossbody bag", "shoulder bag", "tote bag", "handbag", "backpack", "wallet", "purse", "bag"), "Bags & Purses"),
        (("necklace", "bracelet", "earrings", "earring", "ring", "jewelry", "jewellery", "pendant"), "Jewelry"),
        (("dress", "shirt", "jacket", "coat", "pants", "skirt", "sweater", "clothing", "apparel"), "Clothing"),
        (("shoe", "sneaker", "sandal", "boot", "slipper"), "Shoes"),
        (("mug", "cup", "plate", "bowl", "spatula", "knife", "kitchen", "cookware", "utensil"), "Home & Living > Kitchen & Dining"),
        (("lamp", "vase", "pillow", "blanket", "rug", "wall art", "decor", "candle"), "Home & Living > Home Decor"),
        (("organizer", "storage", "holder", "rack", "shelf", "desk"), "Home & Living > Storage & Organization"),
        (("phone case", "tablet case", "laptop sleeve", "keyboard", "charger"), "Electronics & Accessories"),
        (("pet", "dog", "cat", "collar", "leash", "pet bed"), "Pet Supplies"),
        (("toy", "game", "puzzle", "doll"), "Toys & Games"),
        (("planner", "notebook", "journal", "pen", "sticker", "stationery"), "Paper & Party Supplies"),
        (("tool", "craft", "supply", "bead", "mold", "template"), "Craft Supplies & Tools"),
    ]
    for needles, category in category_rules:
        if any(needle in text for needle in needles):
            return category

    noun = strategy.get("primary_product_noun") or _guess_primary_product_noun(
        listing_data.get("title", ""),
        listing_data.get("description", ""),
    )
    if noun and noun != "product":
        return noun.title()
    return "General Product"

def _compact_description(description, limit):
    sentence = _first_sentence(description)
    if not sentence:
        return ""
    return _trim_at_word(sentence, limit)

def _ensure_seo_metadata(listing_data, seo_strategy, source_price=""):
    strategy = _coerce_seo_strategy(seo_strategy)
    description = _apply_description_policy(_strip_description_hype(listing_data.get("description", "")))
    listing_data["description"] = description
    title = _clean_marketplace_title(listing_data.get("title", ""), description, strategy)

    listing_data["title"] = title
    listing_data["seo_strategy"] = strategy
    for removed_key in [
        "google_meta_title",
        "google_meta_description",
        "pinterest_title",
        "pinterest_description",
        "image_alt_text",
    ]:
        listing_data.pop(removed_key, None)
    listing_data["category"] = _normalize_listing_category(listing_data, strategy)
    listing_data["suggested_price"] = _coerce_suggested_price(listing_data, source_price, strategy)
    return listing_data

def score_listing_seo(listing_data, source_context=""):
    profile = get_copywriting_profile()
    score = 100
    notes = []
    title = listing_data.get("title", "")
    title_words = re.findall(r"\w+", title)
    title_lower = title.lower()
    tags = listing_data.get("tags") or []
    description = listing_data.get("description", "")
    first_sentence = _first_sentence(description)

    if not title:
        score -= 20
        notes.append("Missing Etsy title.")
    if len(title) > MAX_ETSY_TITLE_CHARS and not risk_override_enabled(profile, "etsy_title_limit"):
        score -= 15
        notes.append("Etsy title is over 140 characters.")
    if len(title) < MIN_MARKETPLACE_TITLE_CHARS and not risk_override_enabled(profile, "title_style"):
        score -= 12
        notes.append("Etsy title is short; add more objective search detail while staying readable.")
    if len(title_words) > IDEAL_MARKETPLACE_TITLE_WORDS and not risk_override_enabled(profile, "title_style"):
        score -= 8
        notes.append("Etsy title is over the preferred readability target.")
    if _title_phrase_count(title) > MAX_MARKETPLACE_TITLE_PHRASES and not risk_override_enabled(profile, "title_style"):
        score -= 8
        notes.append("Etsy title uses too many comma/colon phrase chunks.")
    if _title_has_variation_leakage(title) and not risk_override_enabled(profile, "title_style"):
        score -= 20
        notes.append("Etsy title appears to contain raw variation labels such as Color/Size.")
    if "|" in title and not risk_override_enabled(profile, "title_style"):
        score -= 6
        notes.append("Etsy title still uses pipe-separated keyword formatting.")
    if _is_keyword_stuffed_title(title) and not risk_override_enabled(profile, "title_style"):
        score -= 10
        notes.append("Etsy title reads like a keyword list instead of one clean shopper-facing title.")
    if any(term in title_lower for term in SUBJECTIVE_TITLE_TERMS) and not risk_override_enabled(profile, "promotional_language"):
        score -= 5
        notes.append("Etsy title includes subjective wording better suited for the description.")
    if len(set(word.lower() for word in title_words)) < max(1, len(title_words) - 2):
        score -= 5
        notes.append("Etsy title repeats too many words.")
    if (
        any(term in f"{title} {description}".lower() for term in PROHIBITED_LISTING_TERMS)
        and not risk_override_enabled(profile, "supplier_terms")
    ):
        score -= 20
        notes.append("Listing contains prohibited supplier/platform language.")
    listing_text = " ".join([
        title,
        description,
        " ".join(str(tag) for tag in tags),
    ]).lower()
    for claim, support_terms in RISKY_UNSUPPORTED_CLAIMS.items():
        if (
            any(term in listing_text for term in support_terms)
            and not _source_supports_claim(source_context, support_terms)
            and not risk_override_enabled(profile, "factual_accuracy")
            and not risk_override_enabled(profile, "positioning_claims")
        ):
            score -= 8
            notes.append(f"Potential unsupported claim: {claim}.")
    if any(term in listing_text for term in TRADEMARK_RISK_TERMS) and not risk_override_enabled(profile, "trademark_language"):
        score -= 15
        notes.append("Possible trademark/IP term detected; review before publishing.")

    if len(tags) != TAG_COUNT and not risk_override_enabled(profile, "etsy_tag_count"):
        score -= 15
        notes.append("Etsy tags should contain exactly 13 entries.")
    if any(len(str(tag)) > MAX_ETSY_TAG_CHARS for tag in tags) and not risk_override_enabled(profile, "etsy_tag_length"):
        score -= 15
        notes.append("One or more Etsy tags exceed 20 characters.")
    if len({str(tag).lower() for tag in tags}) != len(tags):
        score -= 8
        notes.append("Etsy tags include duplicates.")

    if not first_sentence:
        score -= 10
        notes.append("Description is missing a clear first sentence.")
    elif len(first_sentence) > 180:
        score -= 5
        notes.append("First description sentence is long; keep the product identity clear early.")
    if "product details:" not in description.lower() and not risk_override_enabled(profile, "description_structure"):
        score -= 10
        notes.append("Description is missing a Product Details section with confirmed facts.")

    category = str(listing_data.get("category") or "").strip()
    if not category or category.lower() in {"not categorized", "uncategorized", "none", "n/a", "general product"}:
        score -= 12
        notes.append("Category is missing or too vague.")

    price_value = _parse_price_value(listing_data.get("suggested_price"))
    if not price_value or price_value <= 0:
        score -= 10
        notes.append("Suggested price is missing or zero.")

    score = max(0, min(100, score))
    return score, notes

def build_listing_repair_instructions(listing_data, source_context=""):
    """Return exact deterministic repairs for the model's final correction pass."""
    repairs = []
    profile = get_copywriting_profile()
    title = str(listing_data.get("title") or "").strip()
    title_words = re.findall(r"\w+", title)
    title_lower = title.lower()
    description = str(listing_data.get("description") or "").strip()
    description_lower = description.lower()
    tags = listing_data.get("tags") or []
    listing_text = " ".join([title, description, " ".join(str(tag) for tag in tags)]).lower()
    category = str(listing_data.get("category") or "").strip()
    category_lower = category.lower()

    if not title:
        repairs.append("Write one Etsy title using the primary product noun early, objective supported traits, and one real use case if supported.")
    elif len(title) < MIN_MARKETPLACE_TITLE_CHARS and not risk_override_enabled(profile, "title_style"):
        repairs.append("Rewrite the title to about 80-125 characters while staying readable; add only objective supported search details from the source facts.")
    if len(title) > MAX_ETSY_TITLE_CHARS and not risk_override_enabled(profile, "etsy_title_limit"):
        repairs.append("Shorten the title to 140 characters or less without removing the main product noun.")
    if len(title_words) > IDEAL_MARKETPLACE_TITLE_WORDS and not risk_override_enabled(profile, "title_style"):
        repairs.append("Simplify the title to roughly 18 words or fewer so it reads like one shopper-facing title.")
    if (_title_phrase_count(title) > MAX_MARKETPLACE_TITLE_PHRASES or "|" in title) and not risk_override_enabled(profile, "title_style"):
        repairs.append("Rewrite the title as one natural Etsy title with no pipe separators and no more than three comma or colon chunks.")
    if (
        _title_has_variation_leakage(title)
        or re.search(r"\{[^}]+['\"]?(trait|value)['\"]?[^}]*\}", title_lower)
    ) and not risk_override_enabled(profile, "title_style"):
        repairs.append("Remove raw variation labels and dict-shaped text from the title, including Color:, Size:, trait, and value fragments.")
    if _is_keyword_stuffed_title(title) and not risk_override_enabled(profile, "title_style"):
        repairs.append("Rewrite the title so it is not a keyword list; keep the product noun first and use natural phrasing.")
    if any(term in title_lower for term in SUBJECTIVE_TITLE_TERMS) and not risk_override_enabled(profile, "promotional_language"):
        repairs.append("Remove subjective or risky title words such as perfect, beautiful, luxury, designer, handmade, and eco-friendly unless directly supported.")

    if not description:
        repairs.append("Write a description with a safe lifestyle/story opening followed by a Product Details: section using only confirmed facts.")
    else:
        if not _first_sentence(description):
            repairs.append("Add a clear first sentence that naturally includes the main product keyword for SEO.")
        if "product details:" not in description_lower and not risk_override_enabled(profile, "description_structure"):
            repairs.append("Add a Product Details: section after the story opening and list only confirmed facts from the source, image facts, or variation specs.")
        if re.search(r"\b(is|are|making it|makes it)\s+for\b", description_lower):
            repairs.append("Fix awkward grammar left by cleanup, such as 'is for' or 'making it for', while keeping cautious factual wording.")

    if any(term in listing_text for term in PROHIBITED_LISTING_TERMS) and not risk_override_enabled(profile, "supplier_terms"):
        repairs.append("Remove supplier/platform language such as AliExpress, factory, wholesale, dropshipping, bulk order, bulk pricing, or bulk sale.")
    for claim, support_terms in RISKY_UNSUPPORTED_CLAIMS.items():
        if (
            any(term in listing_text for term in support_terms)
            and not _source_supports_claim(source_context, support_terms)
            and not risk_override_enabled(profile, "factual_accuracy")
            and not risk_override_enabled(profile, "positioning_claims")
        ):
            repairs.append(f"Remove or soften unsupported {claim} claims unless the exact source context supports them.")
    if any(term in listing_text for term in TRADEMARK_RISK_TERMS) and not risk_override_enabled(profile, "trademark_language"):
        repairs.append("Possible trademark/IP term detected; keep it only if it is the literal product identity and mark for human review.")

    if len(tags) != TAG_COUNT and not risk_override_enabled(profile, "etsy_tag_count"):
        repairs.append("Return exactly 13 Etsy tags.")
    if any(len(str(tag)) > MAX_ETSY_TAG_CHARS for tag in tags) and not risk_override_enabled(profile, "etsy_tag_length"):
        repairs.append("Shorten every Etsy tag to 20 characters or less.")
    if len({str(tag).lower() for tag in tags}) != len(tags):
        repairs.append("Remove duplicate Etsy tags and replace them with distinct relevant buyer search phrases.")

    if not category or category_lower in {"not categorized", "uncategorized", "none", "n/a", "general product"}:
        repairs.append("Choose a specific Etsy-style category path; never return Not categorized.")
    product_category_text = " ".join([
        title,
        description,
        json.dumps(_coerce_seo_strategy(listing_data.get("seo_strategy"))),
    ]).lower()
    if "wallet" in category_lower and any(term in product_category_text for term in ["shoulder bag", "crossbody", "tote", "handbag", "satchel", "messenger bag"]):
        repairs.append("Change category to Bags & Purses > Handbags unless the product is clearly a wallet.")

    price_value = _parse_price_value(listing_data.get("suggested_price"))
    if not price_value or price_value <= 0:
        repairs.append("Set a realistic non-zero USD suggested retail price.")

    return _dedupe_preserve_order(repairs)

def finalize_listing_seo(listing_data, seo_strategy, client, source_price="", source_context=""):
    listing_data = dict(listing_data or {})
    strategy = _coerce_seo_strategy(
        listing_data.get("seo_strategy") or seo_strategy,
        listing_data.get("title", ""),
        listing_data.get("description", ""),
    )
    listing_data["seo_strategy"] = strategy
    listing_data["tags"] = complete_tags(listing_data, strategy, client)
    listing_data = _ensure_seo_metadata(listing_data, strategy, source_price)
    score, notes = score_listing_seo(listing_data, source_context)
    repairs = build_listing_repair_instructions(listing_data, source_context)
    listing_data["seo_quality_score"] = score
    listing_data["seo_qa_notes"] = notes
    listing_data["repair_instructions"] = repairs
    listing_data["needs_review"] = (
        score < 85
        or bool(repairs)
        or any("trademark" in note.lower() for note in notes)
    )
    listing_data["review_reasons"] = _dedupe_preserve_order([*notes, *repairs]) if listing_data["needs_review"] else []
    compatibility = get_etsy_compatibility(listing_data, get_copywriting_profile())
    listing_data["etsy_compatible"] = compatibility["etsy_compatible"]
    listing_data["etsy_compatibility_issues"] = compatibility["issues"]
    listing_data["enabled_risk_overrides"] = compatibility["enabled_risk_overrides"]
    return listing_data

def refine_listing_from_qa_notes(listing_data: dict, qa_notes: list, source_context: str, image_facts: dict, seo_strategy: dict, client=None) -> dict:
    """Run one strict correction pass using deterministic QA notes."""
    if not qa_notes:
        return listing_data
    if not client:
        client = get_genai_client()

    facts_part = json.dumps(image_facts or {}, indent=2)
    strategy_part = json.dumps(seo_strategy or listing_data.get("seo_strategy") or {}, indent=2)
    prompt = (
        f"{build_active_policy(get_copywriting_profile(), 'strict_qa_repair')}\n\n"
        "Revise the listing and fix every Required Repair that remains applicable under the active workspace profile.\n\n"
        "Current Listing:\n"
        f"{json.dumps(listing_data, indent=2, ensure_ascii=False)}\n\n"
        "Required Repairs:\n"
        f"{json.dumps(qa_notes, indent=2, ensure_ascii=False)}\n\n"
        "Source Context:\n"
        f"{source_context or 'None'}\n\n"
        "Image Facts:\n"
        f"{facts_part}\n\n"
        "SEO Strategy:\n"
        f"{strategy_part}\n\n"
        "Output strictly as JSON matching the EtsyListing schema."
    )

    openai_client = get_openai_client()
    if openai_client:
        try:
            raw_text = openai_generate_content(openai_client, prompt, json_object=True, max_tokens=1400)
            return json.loads(raw_text)
        except Exception as e:
            print(f"Error during strict QA correction pass via OpenAI: {e}. Falling back to Gemini...")

    try:
        response = generate_content_with_retry(
            client=client,
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=EtsyListing,
            )
        )
        return json.loads(response.text)
    except Exception as e:
        print(f"Error during strict QA correction pass via Gemini: {e}")
        return listing_data

def tweak_etsy_listing(
    existing_listing: dict,
    preset_key: str = "custom",
    instruction: str = "",
    fields: list | None = None,
    source_context: str = "",
    image_facts: dict | None = None,
    variation_specs: list | None = None,
    price: str = "",
    presets: dict | None = None,
    client=None,
) -> dict | None:
    """Revise selected listing fields using the current output as the primary reference."""
    base_listing = dict(existing_listing or {})
    if not base_listing:
        return None

    allowed_fields = {"title", "category", "description", "tags"}
    selected_fields = [field for field in (fields or allowed_fields) if field in allowed_fields]
    if not selected_fields:
        selected_fields = ["title", "category", "description", "tags"]

    if not client:
        client = get_genai_client()
    presets = presets or {}
    image_facts = image_facts or {}
    variation_specs = variation_specs or []

    preset_key = str(preset_key or "custom").strip() or "custom"
    profile = get_copywriting_profile()
    preset_instruction = get_tweak_instruction(profile, preset_key)
    custom_instruction = str(instruction or "").strip()
    custom_rules = str(presets.get("custom_prompt_rules") or "").strip()
    if custom_rules == profile.get("master_rules", "").strip():
        custom_rules = ""

    strategy = _coerce_seo_strategy(
        base_listing.get("seo_strategy"),
        base_listing.get("title", ""),
        base_listing.get("description", ""),
        image_facts,
        variation_specs,
    )

    owner_rules = ""
    if custom_rules:
        owner_rules = (
            "SHOP OWNER COPYWRITING RULES (high priority):\n"
            f"{custom_rules}\n"
            "Follow these unless they conflict with factual accuracy, source support, Etsy compliance, or marketplace safety.\n\n"
        )

    prompt = (
        f"{build_active_policy(profile)}\n\n"
        "You are tweaking an existing Etsy listing, not writing a brand-new product analysis.\n"
        "Use the Current Listing as the primary reference. Use Supporting Facts only to prevent or correct factual mistakes.\n"
        "Do not scan or request images. Follow the active inference and factual policies for uncertain details.\n"
        "Only revise the selected fields. Copy all unselected fields exactly from the Current Listing.\n"
        "If the description contains a policy/footer section, keep it intact unless the selected instruction explicitly asks to remove or rewrite it.\n"
        "Return clean plain text inside the structured response.\n\n"
        f"{owner_rules}"
        f"Selected Fields: {', '.join(selected_fields)}\n"
        f"Preset: {preset_key}\n"
        f"Preset Instruction: {preset_instruction}\n"
        f"Custom Instruction: {custom_instruction or 'None'}\n\n"
        "Current Listing:\n"
        f"{json.dumps(base_listing, indent=2, ensure_ascii=False)}\n\n"
        "Supporting Facts:\n"
        f"{source_context or 'None'}\n\n"
        "Cached Image Facts:\n"
        f"{json.dumps(image_facts, indent=2, ensure_ascii=False)}\n\n"
        "Cached Variation Specs:\n"
        f"{json.dumps(variation_specs, indent=2, ensure_ascii=False)}\n\n"
        "SEO Strategy:\n"
        f"{json.dumps(strategy, indent=2, ensure_ascii=False)}\n\n"
        "Output strictly as JSON matching the EtsyListing schema, including title, description, tags, suggested_price, category, and seo_strategy."
    )

    candidate = None
    openai_client = get_openai_client()
    if openai_client:
        try:
            raw_text = openai_generate_content(openai_client, prompt, json_object=True, max_tokens=1500)
            candidate = json.loads(raw_text)
        except Exception as e:
            print(f"Error during OpenAI listing tweak: {e}. Falling back to Gemini...")
            candidate = None

    if candidate is None:
        try:
            response = generate_content_with_retry(
                client=client,
                model=GEMINI_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=EtsyListing,
                )
            )
            candidate = json.loads(response.text)
        except Exception as e:
            print(f"Error during Gemini listing tweak: {e}")
            return None

    revised = dict(base_listing)
    for field in selected_fields:
        if field not in candidate:
            continue
        value = candidate.get(field)
        if field == "tags":
            if isinstance(value, str):
                value = [part.strip() for part in re.split(r",|\n", value) if part.strip()]
            revised[field] = _as_list(value)
        elif field == "description":
            revised[field] = _apply_description_policy(_strip_description_hype(value))
        elif field == "title":
            revised[field] = str(value or "").strip()
        elif field == "category":
            revised[field] = str(value or "").strip()

    revised["seo_strategy"] = candidate.get("seo_strategy") or revised.get("seo_strategy") or strategy
    original_price = base_listing.get("suggested_price", "")
    revised["suggested_price"] = original_price

    revised = finalize_listing_seo(
        revised,
        revised.get("seo_strategy") or strategy,
        client,
        source_price=original_price or price,
        source_context=source_context,
    )

    for field in allowed_fields:
        if field not in selected_fields and field in base_listing:
            revised[field] = base_listing[field]
    revised["suggested_price"] = original_price

    score, notes = score_listing_seo(revised, source_context)
    repairs = build_listing_repair_instructions(revised, source_context)
    revised["seo_quality_score"] = score
    revised["seo_qa_notes"] = notes
    revised["repair_instructions"] = repairs
    revised["needs_review"] = (
        score < 85
        or bool(repairs)
        or any("trademark" in note.lower() for note in notes)
    )
    revised["review_reasons"] = _dedupe_preserve_order([*notes, *repairs]) if revised["needs_review"] else []
    return revised

def _apply_presets_to_listing(listing_data: dict, presets: dict) -> dict:
    """Inject preset add-ons into the listing description and apply policy override."""
    presets = {**get_listing_addons(get_copywriting_profile()), **(presets or {})}
    desc = _apply_description_policy(listing_data.get("description", ""))

    # Prepend shop intro if set
    shop_intro = (presets.get("shop_intro") or "").strip()
    if shop_intro:
        desc = shop_intro + "\n\n" + desc

    # Determine policy footer (custom override or default)
    custom_policy = (presets.get("custom_policy") or "").strip()
    default_policy = (
        "\n\n---\n"
        "Cancellation Policy: Cancellation is allowed within 5 hours after placing the order.\n"
        "Returns & Refunds Policy: Returns and refunds are accepted for items that arrive damaged or incorrect only."
    )
    policy_block = ("\n\n---\n" + custom_policy) if custom_policy else default_policy

    # Append optional add-ons before the policy block
    shipping_note = (presets.get("shipping_note") or "").strip()
    materials_disclaimer = (presets.get("materials_disclaimer") or "").strip()

    addons = []
    if shipping_note:
        addons.append(shipping_note)
    if materials_disclaimer:
        addons.append(materials_disclaimer)

    if addons:
        desc = desc + "\n\n" + "\n".join(addons)

    desc += policy_block
    desc = _apply_description_policy(desc)
    listing_data["description"] = desc
    return listing_data

def review_and_refine_listing(listing_data: dict, scraped_text: str, image_facts: dict, seo_strategy: dict = None, client=None) -> dict:
    """Evaluate generated listing quality against image_facts and scraped text, doing a single correction pass if issues are found."""
    if not client:
        client = get_genai_client()

    scraped_part = scraped_text or "None provided"
    facts_part = json.dumps(image_facts, indent=2) if image_facts else "None extracted from images"
    strategy_part = json.dumps(seo_strategy or listing_data.get("seo_strategy") or {}, indent=2)

    prompt = (
        f"{build_active_policy(get_copywriting_profile(), 'quality_review')}\n\n"
        "Analyze the draft against the source context and report only issues that remain disallowed by the active profile.\n\n"
        "Draft Etsy Listing:\n"
        f"Title: {listing_data.get('title', '')}\n"
        f"Category: {listing_data.get('category', '')}\n"
        f"Price: {listing_data.get('suggested_price', '')}\n"
        f"Tags: {', '.join(listing_data.get('tags', []))}\n"
        f"Description: {listing_data.get('description', '')}\n\n"
        "SEO Strategy:\n"
        f"{strategy_part}\n\n"
        "Scraped Info:\n"
        f"{scraped_part}\n\n"
        "Image Facts (Extracted directly from product photos/charts):\n"
        f"{facts_part}\n\n"
        "\nOutput your response strictly as a JSON object matching the requested schema."
    )

    verdict = {"approved": True}
    openai_client = get_openai_client()
    if openai_client:
        try:
            raw_text = openai_generate_content(openai_client, prompt, json_object=True, max_tokens=500)
            verdict = json.loads(raw_text)
        except Exception as e:
            print(f"Error during OpenAI self-review: {e}. Falling back to Gemini...")
            openai_client = None

    if not openai_client:
        try:
            response = generate_content_with_retry(
                client=client,
                model=GEMINI_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=ReviewVerdict,
                )
            )
            verdict = json.loads(response.text)
        except Exception as e:
            print(f"Error during Gemini self-review: {e}")
            verdict = {"approved": True}

    if verdict.get("approved"):
        print("Self-review: Listing approved with no changes.")
        return listing_data

    # Listing needs correction
    print("Self-review: Issues found. Running correction pass...")
    print(f" - Title issues: {verdict.get('title_issues', 'None')}")
    print(f" - Description issues: {verdict.get('description_issues', 'None')}")
    print(f" - Tag issues: {verdict.get('tag_issues', 'None')}")
    if verdict.get("seo_issues"):
        print(f" - SEO issues: {verdict.get('seo_issues')}")

    correction_prompt = (
        f"{build_active_policy(get_copywriting_profile(), 'correction')}\n\n"
        "Revise the draft based on the critic feedback. Apply only feedback that remains applicable under the active profile.\n\n"
        "Draft Listing:\n"
        f"Title: {listing_data.get('title', '')}\n"
        f"Category: {listing_data.get('category', '')}\n"
        f"Price: {listing_data.get('suggested_price', '')}\n"
        f"Tags: {', '.join(listing_data.get('tags', []))}\n"
        f"Description: {listing_data.get('description', '')}\n\n"
        "Critic Feedback:\n"
        f"1. Title issues: {verdict.get('title_issues', 'None')}\n"
        f"2. Description issues: {verdict.get('description_issues', 'None')}\n"
        f"3. Tag issues: {verdict.get('tag_issues', 'None')}\n"
        f"4. SEO issues: {verdict.get('seo_issues', 'None')}\n\n"
        "SEO Strategy:\n"
        f"{strategy_part}\n\n"
        "Image Facts (For Reference):\n"
        f"{facts_part}\n\n"
        "Original Scraped Info (For Reference):\n"
        f"{scraped_part}\n\n"
        "Output your corrected listing strictly as a JSON object matching the EtsyListing schema, including title, description, tags, suggested_price, category, and seo_strategy."
    )

    corrected_data = listing_data
    if openai_client:
        try:
            raw_text = openai_generate_content(openai_client, correction_prompt, json_object=True, max_tokens=1000)
            corrected_data = json.loads(raw_text)
        except Exception as e:
            print(f"Error during OpenAI correction pass: {e}. Falling back to Gemini...")
            openai_client = None

    if not openai_client:
        try:
            response = generate_content_with_retry(
                client=client,
                model=GEMINI_MODEL,
                contents=correction_prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=EtsyListing,
                )
            )
            corrected_data = json.loads(response.text)
        except Exception as e:
            print(f"Error during Gemini correction pass: {e}")

    print("Correction pass complete.")
    return corrected_data

def write_etsy_listing(title, description, price="", client=None, presets: dict = None, image_facts: dict = None, variation_specs: list = None, copywriting_depth: str = "balanced"):
    """Write Etsy title, description, and tags from AliExpress details using Gemini or OpenAI."""
    if not client:
        client = get_genai_client()
    if presets is None:
        presets = {}
    if image_facts is None:
        image_facts = {}
    copywriting_depth = str(copywriting_depth or "balanced").strip().lower()
    quality_mode = copywriting_depth == "quality"
    profile = get_copywriting_profile()

    print("Generating Etsy-optimized listing content...")

    facts_str = _format_image_facts(image_facts)
    var_str = _format_variation_specs(variation_specs)
    seo_strategy = build_seo_strategy(
        title=title,
        description=description,
        image_facts=image_facts,
        variation_specs=variation_specs,
        client=client,
    )
    seo_strategy_str = json.dumps(seo_strategy, indent=2)

    custom_rules = presets.get("custom_prompt_rules", "").strip()
    if custom_rules == profile.get("master_rules", "").strip():
        custom_rules = ""
    owner_rules = ""
    if custom_rules:
        owner_rules = (
            "SHOP OWNER COPYWRITING RULES (high priority):\n"
            f"{custom_rules}\n"
            "Follow these unless they conflict with factual accuracy, source support, Etsy compliance, or marketplace safety.\n\n"
        )

    prompt = (
        f"{build_active_policy(profile, 'listing_draft')}\n\n"
        f"Create an Etsy listing for the following product:\n"
        f"Original Title: {title}\n"
        f"Scraped Description/Info: {description}\n"
        f"Estimated Price: {price}\n\n"
        "Image Facts (Extracted directly from product photos/spec charts):\n"
        f"{facts_str}\n\n"
        "Variation Specifications (Extracted sizes/dimensions for specific options):\n"
        f"{var_str}\n\n"
        "SEO Strategy (use this as the source of keyword priorities):\n"
        f"{seo_strategy_str}\n\n"
        f"{owner_rules}"
        f"Copywriting depth: {copywriting_depth}.\n"
        "Output your response strictly as a JSON object matching the EtsyListing schema."
    )

    listing_data = None
    openai_client = get_openai_client()
    if openai_client:
        print("Generating Etsy-optimized listing content via OpenAI...")
        try:
            raw_text = openai_generate_content(openai_client, prompt, json_object=True)
            listing_data = json.loads(raw_text)
        except Exception as e:
            print(f"Error generating listing content via OpenAI: {e}. Falling back to Gemini...")

    if not listing_data:
        try:
            response = generate_content_with_retry(
                client=client,
                model=GEMINI_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=EtsyListing,
                )
            )
            listing_data = json.loads(response.text)
        except Exception as e:
            print(f"Error generating listing content: {e}")
            return None

    # Run self-review critic and optional correction pass
    listing_data["seo_strategy"] = listing_data.get("seo_strategy") or seo_strategy
    listing_data = review_and_refine_listing(listing_data, description, image_facts, seo_strategy=seo_strategy, client=client)

    # Apply strict tag and Etsy title guidelines
    source_context = "\n".join([
        str(title or ""),
        str(description or ""),
        facts_str,
        var_str,
    ])
    listing_data = finalize_listing_seo(
        listing_data,
        seo_strategy,
        client,
        source_price=price,
        source_context=source_context,
    )
    repair_instructions = listing_data.get("repair_instructions") or []
    if quality_mode and (listing_data.get("seo_quality_score", 0) < 90 or repair_instructions):
        print("Strict QA: Running one quality correction pass for deterministic repairs...")
        listing_data = refine_listing_from_qa_notes(
            listing_data,
            repair_instructions or listing_data.get("seo_qa_notes", []),
            source_context,
            image_facts,
            seo_strategy,
            client=client,
        )
        listing_data = finalize_listing_seo(
            listing_data,
            seo_strategy,
            client,
            source_price=price,
            source_context=source_context,
        )
    
    if not listing_data.get("category") or str(listing_data.get("category")).strip().lower() == "not categorized":
        listing_data["category"] = _infer_listing_category(listing_data, seo_strategy)

    # Inject presets and policy
    listing_data = _apply_presets_to_listing(listing_data, presets)

    return listing_data

def generate_image_prompt_details(image_path_or_text, client=None):
    """Generate visual details from either a local product image path (preferred) or text description."""
    if not client:
        client = get_genai_client()
        
    if not image_path_or_text:
        return ""
        
    # Check if the input is a valid file path to an image on disk
    if isinstance(image_path_or_text, str) and os.path.exists(image_path_or_text) and image_path_or_text.lower().endswith(('.png', '.jpg', '.jpeg')):
        print(f"Analyzing reference image for visual prompt details: {image_path_or_text}")
        prompt = (
            "Analyze this product image. Write a highly detailed description of the product's appearance "
            "designed specifically for a text-to-image prompt (FLUX/Midjourney). Describe the exact shape, "
            "the texture, the colors, materials, straps, details, and the overall styling. Be descriptive and detailed "
            "(about 50-70 words). Do not include any introductory or concluding text, do not write 'Here is'."
        )
        
        # Try OpenAI first if configured
        openai_client = get_openai_client()
        if openai_client:
            print("Using OpenAI to analyze reference image for visual details...")
            try:
                pil_img = Image.open(image_path_or_text)
                data_uri = pil_image_to_base64_data_uri(pil_img)
                visual_details = openai_generate_content(
                    openai_client,
                    [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": data_uri}},
                    ],
                    max_tokens=250,
                ).strip().replace('\n', ' ').strip()
                if visual_details.startswith('"') and visual_details.endswith('"'):
                    visual_details = visual_details[1:-1]
                print(f"Extracted visual details via OpenAI: {visual_details}")
                return visual_details
            except Exception as e:
                print(f"Error generating visual details from image via OpenAI: {e}. Falling back to Gemini...")
                
        try:
            pil_img = Image.open(image_path_or_text)
            response = generate_content_with_retry(
                client=client,
                model=GEMINI_MODEL,
                contents=[prompt, pil_img]
            )
            visual_details = response.text.strip().replace('\n', ' ').strip()
            if visual_details.startswith('"') and visual_details.endswith('"'):
                visual_details = visual_details[1:-1]
            print(f"Extracted visual details from reference image: {visual_details}")
            return visual_details
        except Exception as e:
            print(f"Error generating visual details from image: {e}")
            
    # Fallback to text description analysis
    print("Generating visual details from text description fallback...")
    prompt = (
        "Based on the following product details, write a concise description of its physical appearance "
        "ideal for a text-to-image prompt (like Midjourney/FLUX). Focus strictly on its shape, materials, "
        "color pattern, and design highlights. Keep it under 25 words, separated by commas. "
        "Do not write introductory text, do not use bullet points.\n\n"
        f"Product Details:\n{image_path_or_text}"
    )
    
    # Try OpenAI first if configured
    openai_client = get_openai_client()
    if openai_client:
        try:
            visual_details = openai_generate_content(openai_client, prompt, max_tokens=100).strip().replace('\n', ' ').strip()
            if visual_details.startswith('"') and visual_details.endswith('"'):
                visual_details = visual_details[1:-1]
            print(f"Extracted visual details from text via OpenAI: {visual_details}")
            return visual_details
        except Exception as e:
            print(f"Error generating visual details from text via OpenAI: {e}. Falling back to Gemini...")
            
    try:
        response = generate_content_with_retry(
            client=client,
            model=GEMINI_MODEL,
            contents=prompt
        )
        visual_details = response.text.strip().replace('\n', ' ').strip()
        if visual_details.startswith('"') and visual_details.endswith('"'):
            visual_details = visual_details[1:-1]
        print(f"Extracted visual details from text: {visual_details}")
        return visual_details
    except Exception as e:
        print(f"Error generating visual details from text: {e}")
        return ""
