import os
import json
import re
import time
from PIL import Image
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from typing import Any, Dict, List
from dotenv import load_dotenv

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

# Define the structured output format for the Etsy listing
class SEOStrategy(BaseModel):
    primary_product_noun: str = Field(default="", description="Plain product noun buyers would search, e.g. crossbody bag, ceramic mug")
    top_traits: List[str] = Field(default_factory=list, description="Objective traits from source facts such as color, material, size, style, shape")
    buyer_intents: List[str] = Field(default_factory=list, description="Realistic buyer intents or use cases for this product")
    audience: List[str] = Field(default_factory=list, description="Relevant audience segments only when supported by the product")
    primary_keywords: List[str] = Field(default_factory=list, description="Most important buyer search phrases for Etsy and Google")
    long_tail_keywords: List[str] = Field(default_factory=list, description="Specific multi-word phrases likely to convert")
    tag_keywords: List[str] = Field(default_factory=list, description="Candidate Etsy tags, preferably 20 characters or less")
    google_keywords: List[str] = Field(default_factory=list, description="Natural phrases useful for Google title and description")
    pinterest_keywords: List[str] = Field(default_factory=list, description="Broad and exact phrases useful for Pinterest discovery")

class EtsyListing(BaseModel):
    title: str = Field(description="Search-optimized Etsy product title, maximum 140 characters")
    description: str = Field(description="High-converting product description highlighting key features and specifications. Make sure to use double newlines (\\n\\n) between paragraphs, features, and specs to avoid a single dense block of text.")
    tags: List[str] = Field(description="13 relevant search keywords or short tag phrases for Etsy listings")
    suggested_price: str = Field(description="Suggested Etsy retail price in USD, e.g., '$24.99'")
    category: str = Field(description="The most accurate Etsy category path or specific category name (e.g., 'Home & Living > Home Decor' or 'Crossbody Bags')")
    seo_strategy: SEOStrategy = Field(default_factory=SEOStrategy, description="Keyword and positioning strategy used to write the listing")
    google_meta_title: str = Field(default="", description="Google-focused title, ideally 50-60 characters and readable")
    google_meta_description: str = Field(default="", description="Google-focused meta description, ideally 145-160 characters")
    pinterest_title: str = Field(default="", description="Pinterest product Pin title, readable and keyword-rich")
    pinterest_description: str = Field(default="", description="Pinterest product Pin description with broad and exact discovery phrases")
    image_alt_text: List[str] = Field(default_factory=list, description="Accurate SEO alt text ideas for listing/product images")
    seo_quality_score: int = Field(default=0, description="Deterministic SEO QA score from 0 to 100")
    seo_qa_notes: List[str] = Field(default_factory=list, description="Issues or warnings from deterministic SEO QA")

class VisualSpecs(BaseModel):
    dimensions: str = Field(description="Exact measurements extracted from text/labels in the images, or empty string if not clearly shown")
    materials: str = Field(description="Materials labeled or clearly described, or empty string if not clearly shown")
    colors: str = Field(description="Exact colors or variations, or empty string if not clearly shown")
    capacity: str = Field(description="Capacity details (e.g. holds A4/laptop), or empty string if not clearly shown")
    other_specs: str = Field(description="Any other printed specifications, or empty string if not clearly shown")
    visual_style: str = Field(description="Brief physical appearance description (e.g. woven texture, hollow-out design, wood base, strap style), or empty string if not clearly shown")

class VariationSpec(BaseModel):
    name: str = Field(description="The name or label of this variation (e.g., 'Color: Red', 'Beige')")
    size: str = Field(description="Detected size name (e.g., 'S', 'M', 'L', 'Small', '30x40cm'), or empty if not applicable or not found")
    dimensions: str = Field(description="Specific measurements for this variation (e.g., '38cm x 28cm x 10cm', '12 inches'), or empty if not clearly determined")
    other_details: str = Field(description="Any other features specific to this variation (e.g., material, pattern, weight capacity), or empty")

class VariationListSpecs(BaseModel):
    variations: List[VariationSpec] = Field(description="List of detected specifications for each variation option in the exact same order as input")

class ReviewVerdict(BaseModel):
    approved: bool = Field(description="True if the listing meets all quality guidelines, has no hallucinations, and aligns with visual specifications, False otherwise")
    title_issues: str = Field(description="Feedback/issues about title quality, or empty string if perfect")
    description_issues: str = Field(description="Feedback/issues about description (e.g., missing dimensions or incorrect facts), or empty string if perfect")
    tag_issues: str = Field(description="Feedback/issues about tags (length, quantity, search relevance), or empty string if perfect")
    seo_issues: str = Field(default="", description="Feedback/issues about Google/Pinterest metadata and overall SEO strategy, or empty string if perfect")

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
            openai_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
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
            
            response = openai_client.chat.completions.create(
                model=openai_model,
                messages=messages,
                max_tokens=1000
            )
            print("Visual description generated successfully via OpenAI.")
            return response.choices[0].message.content
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
        "Analyze these product images carefully. Extract key specifications and facts to help generate an Etsy listing.\n"
        "STRICT CONFORMANCE RULES (NO GUESSING):\n"
        "1. DIMENSIONS: Only extract exact measurements (height, width, depth, capacity, weight limit, drop length, etc.) if they are clearly printed as text/diagrams in the images. If not clearly shown, leave this field as an empty string. DO NOT guess, estimate, or approximate.\n"
        "2. MATERIALS: Only extract materials (e.g. wool, canvas, alloy) if they are explicitly printed or clearly labeled. If not explicitly shown, leave as an empty string. DO NOT infer materials from appearance alone.\n"
        "3. COLORS: Extract the exact color names shown in variations or text labels. If not shown, leave empty.\n"
        "4. CAPACITY: Extract specific capacity info (e.g. fits a 13-inch laptop, fits A4 documents) only if explicitly labeled. Otherwise leave empty.\n"
        "5. OTHER SPECS: Any other printed specifications/tables shown in the images. Otherwise leave empty.\n"
        "6. VISUAL STYLE: Briefly describe the actual appearance of the product (texture, woven/smooth, shape) to help write the description.\n"
        "\nOutput your response strictly as a JSON object matching the requested schema."
    )
    
    # Try OpenAI first if configured
    openai_client = get_openai_client()
    if openai_client:
        print("Using OpenAI to extract visual specs...")
        try:
            openai_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
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
            
            response = openai_client.chat.completions.create(
                model=openai_model,
                messages=messages,
                response_format={"type": "json_object"},
                max_tokens=1000
            )
            return json.loads(response.choices[0].message.content)
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
        "You are an expert product spec analyzer. Analyze the variation options for this product.\n"
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
        "\nSTRICT CONFORMANCE & MAPPING RULES:\n"
        "1. Order: You MUST return the variation specifications in the exact same index order as the input list.\n"
        "2. Name Match: Set the 'name' field in each result item to the corresponding Name/Label from the variation list.\n"
        "3. Size Extraction: Look at the variation's name/label. If it contains a size indicator (e.g. 'S', 'M', 'L', 'XL', '20cm', 'small'), set the 'size' field.\n"
        "4. Dimension Matching: Cross-reference the variation's size name with any size charts in the CONTEXT. If the size chart lists measurements for that size (e.g. S: 38x28cm), extract and assign those measurements to the 'dimensions' field of that variation.\n"
        "5. Image Extraction: Below are the variation images. If a variation image itself contains printed text displaying specific sizes, dimensions, or measurements (e.g. a diagram showing the size), extract those measurements for that variation.\n"
        "6. No Guessing: If you cannot determine any size or dimensions for a variation, leave those fields as empty strings. DO NOT guess or approximate.\n"
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
            openai_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
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

            response = openai_client.chat.completions.create(
                model=openai_model,
                messages=messages,
                response_format={"type": "json_object"},
                max_tokens=1500
            )
            res_dict = json.loads(response.choices[0].message.content)
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
    """Ensure all tags are under 20 characters, split/condensing any that exceed the limit."""
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    if not isinstance(tags, list):
        tags = []
        
    openai_client = get_openai_client()
    cleaned = []
    for tag in tags:
        tag = tag.strip().lower()
        if len(tag) <= 20:
            cleaned.append(tag)
        else:
            print(f"Tag too long ({len(tag)} chars): '{tag}'. Condensing...")
            
            # Try OpenAI first if configured
            if openai_client:
                try:
                    openai_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
                    prompt = f"Shorten this keyword phrase to be under 20 characters (including spaces) for Etsy tags, keeping its search relevance. Output ONLY the shortened phrase, no quotes, no extra words:\n{tag}"
                    response = openai_client.chat.completions.create(
                        model=openai_model,
                        messages=[{"role": "user", "content": prompt}],
                        max_tokens=20
                    )
                    short_tag = response.choices[0].message.content.strip().replace('"', '').replace("'", "")
                    if len(short_tag) <= 20:
                        cleaned.append(short_tag)
                        print(f"Condensed tag via OpenAI: '{tag}' -> '{short_tag}'")
                        continue
                except Exception as e:
                    print(f"Error condensing tag '{tag}' via OpenAI: {e}. Falling back to Gemini...")
            
            # Fallback to Gemini
            try:
                prompt = f"Shorten this keyword phrase to be under 20 characters (including spaces) for Etsy tags, keeping its search relevance. Output ONLY the shortened phrase, no quotes, no extra words:\n{tag}"
                response = generate_content_with_retry(
                    client=client,
                    model=GEMINI_MODEL,
                    contents=prompt
                )
                short_tag = response.text.strip().replace('"', '').replace("'", "")
                if len(short_tag) <= 20:
                    cleaned.append(short_tag)
                    print(f"Condensed tag: '{tag}' -> '{short_tag}'")
                else:
                    # Hard fallback: truncate
                    truncated = tag[:20].strip()
                    cleaned.append(truncated)
                    print(f"Fallback truncate tag: '{tag}' -> '{truncated}'")
            except Exception as e:
                print(f"Error condensing tag '{tag}': {e}")
                cleaned.append(tag[:20].strip())
                
    # Deduplicate and limit to 13
    seen = set()
    final_tags = []
    for t in cleaned:
        if t not in seen and t:
            seen.add(t)
            final_tags.append(t)
            
    return final_tags[:13]

TAG_COUNT = 13
MAX_ETSY_TAG_CHARS = 20
MAX_ETSY_TITLE_CHARS = 140
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
    "bulk",
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

def _as_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        return [v.strip() for v in re.split(r"[,;\n]+", value) if v.strip()]
    return [str(value).strip()] if str(value).strip() else []

def _dedupe_preserve_order(items):
    seen = set()
    result = []
    for item in items:
        clean = re.sub(r"\s+", " ", str(item).strip())
        if not clean:
            continue
        key = clean.lower()
        if key not in seen:
            seen.add(key)
            result.append(clean)
    return result

def _strip_prohibited_terms(text):
    clean = str(text or "")
    for term in PROHIBITED_LISTING_TERMS:
        clean = re.sub(re.escape(term), "", clean, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", clean).strip()

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
        "google_keywords": candidates[:8],
        "pinterest_keywords": candidates[:10],
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
        "Create a practical SEO strategy for an Etsy product listing using only the facts provided.\n"
        "Do not invent materials, dimensions, personalization, handmade status, brand names, or target audiences.\n"
        "Do not use supplier/platform terms such as AliExpress, China, factory, wholesale, bulk, or dropshipping.\n\n"
        f"Original Title: {title}\n"
        f"Scraped Description/Info: {description}\n\n"
        "Image Facts:\n"
        f"{facts_str}\n\n"
        "Variation Specifications:\n"
        f"{var_str}\n\n"
        "Strategy rules:\n"
        "- primary_product_noun must be a plain buyer-searchable noun phrase.\n"
        "- top_traits must be objective traits only: color, material, size, shape, style, function, capacity, or texture.\n"
        "- primary_keywords and long_tail_keywords should be natural buyer phrases, not keyword salad.\n"
        "- tag_keywords should include at least 18 candidates where possible, each preferably 20 characters or less.\n"
        "- Include a mix of exact product phrases, broad category phrases, use-case phrases, and style/material phrases.\n"
        "- Pinterest keywords may be broader than Etsy tags, but must still describe this product.\n\n"
        "Output strictly as JSON matching the SEOStrategy schema."
    )

    openai_client = get_openai_client()
    if openai_client:
        try:
            openai_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
            response = openai_client.chat.completions.create(
                model=openai_model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                max_tokens=900
            )
            return _coerce_seo_strategy(
                json.loads(response.choices[0].message.content),
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
        "pinterest_keywords",
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
    clean = _strip_prohibited_terms(tag).lower()
    clean = re.sub(r"[^a-z0-9 &-]", " ", clean)
    clean = re.sub(r"\s+", " ", clean).strip(" -&")
    if len(clean) <= MAX_ETSY_TAG_CHARS:
        return clean
    words = [word for word in clean.split() if word not in STOP_WORDS]
    shortened = " ".join(words)
    if len(shortened) <= MAX_ETSY_TAG_CHARS:
        return shortened
    while words and len(" ".join(words)) > MAX_ETSY_TAG_CHARS:
        words.pop()
    return " ".join(words).strip() or clean[:MAX_ETSY_TAG_CHARS].strip()

def complete_tags(listing_data, seo_strategy, client):
    raw_candidates = _tag_phrase_candidates(listing_data, seo_strategy)
    candidate_tags = []
    for candidate in raw_candidates:
        cleaned = _simple_tag_cleanup(candidate)
        if cleaned:
            candidate_tags.append(cleaned)

    cleaned_tags = clean_tags(candidate_tags, client)
    if len(cleaned_tags) >= TAG_COUNT:
        return cleaned_tags[:TAG_COUNT]

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
        if len(cleaned_tags) >= TAG_COUNT:
            break
    return cleaned_tags[:TAG_COUNT]

def _clean_listing_title(title):
    clean = _strip_prohibited_terms(title)
    clean = re.sub(r"\s*[\|/]\s*", ", ", clean)
    clean = re.sub(r"\s+", " ", clean).strip(" ,-")
    return _trim_at_word(clean, MAX_ETSY_TITLE_CHARS)

def _compact_description(description, limit):
    sentence = _first_sentence(description)
    if not sentence:
        return ""
    return _trim_at_word(sentence, limit)

def _ensure_seo_metadata(listing_data, seo_strategy):
    strategy = _coerce_seo_strategy(seo_strategy)
    title = _clean_listing_title(listing_data.get("title", ""))
    description = listing_data.get("description", "")
    noun = strategy.get("primary_product_noun") or _guess_primary_product_noun(title, description)
    keywords = _dedupe_preserve_order(
        _as_list(strategy.get("google_keywords"))
        + _as_list(strategy.get("primary_keywords"))
        + _as_list(strategy.get("pinterest_keywords"))
    )

    listing_data["title"] = title
    if not listing_data.get("google_meta_title"):
        listing_data["google_meta_title"] = _trim_at_word(title, GOOGLE_TITLE_CHARS)
    else:
        listing_data["google_meta_title"] = _trim_at_word(listing_data.get("google_meta_title"), GOOGLE_TITLE_CHARS)

    if not listing_data.get("google_meta_description"):
        meta_desc = _compact_description(description, GOOGLE_DESCRIPTION_CHARS)
        if not meta_desc:
            meta_desc = _trim_at_word(f"{title} with {', '.join(keywords[:3])}", GOOGLE_DESCRIPTION_CHARS)
        listing_data["google_meta_description"] = meta_desc
    else:
        listing_data["google_meta_description"] = _trim_at_word(listing_data.get("google_meta_description"), GOOGLE_DESCRIPTION_CHARS)

    if not listing_data.get("pinterest_title"):
        listing_data["pinterest_title"] = _trim_at_word(title, PINTEREST_TITLE_CHARS)
    else:
        listing_data["pinterest_title"] = _trim_at_word(listing_data.get("pinterest_title"), PINTEREST_TITLE_CHARS)

    if not listing_data.get("pinterest_description"):
        pinterest_terms = ", ".join(keywords[:6])
        base = _first_sentence(description) or title
        if pinterest_terms:
            base = f"{base} Discover details for {pinterest_terms}."
        listing_data["pinterest_description"] = _trim_at_word(base, PINTEREST_DESCRIPTION_CHARS)
    else:
        listing_data["pinterest_description"] = _trim_at_word(listing_data.get("pinterest_description"), PINTEREST_DESCRIPTION_CHARS)

    alt_text = _as_list(listing_data.get("image_alt_text"))
    if not alt_text:
        trait_text = ", ".join(_as_list(strategy.get("top_traits"))[:3])
        alt_base = f"{title}"
        if trait_text and trait_text.lower() not in alt_base.lower():
            alt_base = f"{alt_base} showing {trait_text}"
        alt_text = [
            _trim_at_word(alt_base, 120),
            _trim_at_word(f"Close view of {noun} details", 120),
            _trim_at_word(f"{noun} styled for product listing photo", 120),
        ]
    listing_data["image_alt_text"] = _dedupe_preserve_order(alt_text)[:5]
    listing_data["seo_strategy"] = strategy
    return listing_data

def score_listing_seo(listing_data):
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
    if len(title) > MAX_ETSY_TITLE_CHARS:
        score -= 15
        notes.append("Etsy title is over 140 characters.")
    if len(title_words) > 15:
        score -= 8
        notes.append("Etsy title is over the preferred 15-word readability target.")
    if "|" in title:
        score -= 6
        notes.append("Etsy title still uses pipe-separated keyword formatting.")
    if any(term in title_lower for term in SUBJECTIVE_TITLE_TERMS):
        score -= 5
        notes.append("Etsy title includes subjective wording better suited for the description.")
    if len(set(word.lower() for word in title_words)) < max(1, len(title_words) - 2):
        score -= 5
        notes.append("Etsy title repeats too many words.")
    if any(term in f"{title} {description}".lower() for term in PROHIBITED_LISTING_TERMS):
        score -= 20
        notes.append("Listing contains prohibited supplier/platform language.")

    if len(tags) != TAG_COUNT:
        score -= 15
        notes.append("Etsy tags should contain exactly 13 entries.")
    if any(len(str(tag)) > MAX_ETSY_TAG_CHARS for tag in tags):
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

    for field, label, limit in [
        ("google_meta_title", "Google meta title", GOOGLE_TITLE_CHARS),
        ("google_meta_description", "Google meta description", GOOGLE_DESCRIPTION_CHARS),
        ("pinterest_title", "Pinterest title", PINTEREST_TITLE_CHARS),
        ("pinterest_description", "Pinterest description", PINTEREST_DESCRIPTION_CHARS),
    ]:
        value = listing_data.get(field, "")
        if not value:
            score -= 5
            notes.append(f"{label} is missing.")
        elif len(value) > limit:
            score -= 3
            notes.append(f"{label} is longer than the preferred limit.")

    if not listing_data.get("image_alt_text"):
        score -= 5
        notes.append("Image alt text suggestions are missing.")

    score = max(0, min(100, score))
    return score, notes

def finalize_listing_seo(listing_data, seo_strategy, client):
    listing_data = dict(listing_data or {})
    strategy = _coerce_seo_strategy(
        listing_data.get("seo_strategy") or seo_strategy,
        listing_data.get("title", ""),
        listing_data.get("description", ""),
    )
    listing_data["seo_strategy"] = strategy
    listing_data["tags"] = complete_tags(listing_data, strategy, client)
    listing_data = _ensure_seo_metadata(listing_data, strategy)
    score, notes = score_listing_seo(listing_data)
    listing_data["seo_quality_score"] = score
    listing_data["seo_qa_notes"] = notes
    return listing_data

def _apply_presets_to_listing(listing_data: dict, presets: dict) -> dict:
    """Inject preset add-ons into the listing description and apply policy override."""
    desc = listing_data.get("description", "").strip()

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
        "You are a strict QA critic for Etsy listings.\n"
        "Analyze the draft Etsy listing against the Scraped Info and the Image Facts extracted from product photos.\n\n"
        "Draft Etsy Listing:\n"
        f"Title: {listing_data.get('title', '')}\n"
        f"Category: {listing_data.get('category', '')}\n"
        f"Price: {listing_data.get('suggested_price', '')}\n"
        f"Tags: {', '.join(listing_data.get('tags', []))}\n"
        f"Google Meta Title: {listing_data.get('google_meta_title', '')}\n"
        f"Google Meta Description: {listing_data.get('google_meta_description', '')}\n"
        f"Pinterest Title: {listing_data.get('pinterest_title', '')}\n"
        f"Pinterest Description: {listing_data.get('pinterest_description', '')}\n"
        f"Image Alt Text: {json.dumps(listing_data.get('image_alt_text', []))}\n"
        f"Description: {listing_data.get('description', '')}\n\n"
        "SEO Strategy:\n"
        f"{strategy_part}\n\n"
        "Scraped Info:\n"
        f"{scraped_part}\n\n"
        "Image Facts (Extracted directly from product photos/charts):\n"
        f"{facts_part}\n\n"
        "CRITICISM CRITERIA:\n"
        "1. ACCURACY: Check for hallucinations or approximations. If Image Facts specify exact dimensions (e.g. 'Height: 38cm'), does the Description use that exact number? If not, it is an issue. Did the Description invent sizes or facts that are not present in either source?\n"
        "2. TITLE QUALITY: Is the title under 140 chars, preferably under 15 words, readable, and clear in the first 50-60 characters? Does it avoid pipe-separated keyword stuffing, repeated words, and subjective words like perfect or beautiful?\n"
        "3. TAG COMPLIANCE: Are there exactly 13 unique multi-word tags where possible? Is every tag 20 characters or less? Do the tags cover product identity, traits, use cases, style/material, and long-tail phrases without repetition?\n"
        "4. GOOGLE/PINTEREST SEO: Are Google and Pinterest titles/descriptions present, natural, and specific? Does image alt text accurately describe the product without keyword stuffing?\n"
        "\nOutput your response strictly as a JSON object matching the requested schema."
    )

    verdict = {"approved": True}
    openai_client = get_openai_client()
    if openai_client:
        try:
            openai_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
            response = openai_client.chat.completions.create(
                model=openai_model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                max_tokens=500
            )
            verdict = json.loads(response.choices[0].message.content)
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
        "You are an expert copywriter. Revise the following draft Etsy listing based on the critic feedback.\n"
        "Ensure all details are 100% accurate to the product specifications and images.\n"
        "Make sure to preserve and use double newlines (\\n\\n) to separate sections, paragraphs, list items, and key specifications in the description so it is clean, structured, and highly readable.\n"
        "Keep the Etsy title clear and buyer-friendly, not keyword-stuffed. Generate all SEO metadata fields.\n\n"
        "Draft Listing:\n"
        f"Title: {listing_data.get('title', '')}\n"
        f"Category: {listing_data.get('category', '')}\n"
        f"Price: {listing_data.get('suggested_price', '')}\n"
        f"Tags: {', '.join(listing_data.get('tags', []))}\n"
        f"Google Meta Title: {listing_data.get('google_meta_title', '')}\n"
        f"Google Meta Description: {listing_data.get('google_meta_description', '')}\n"
        f"Pinterest Title: {listing_data.get('pinterest_title', '')}\n"
        f"Pinterest Description: {listing_data.get('pinterest_description', '')}\n"
        f"Image Alt Text: {json.dumps(listing_data.get('image_alt_text', []))}\n"
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
        "Output your corrected listing strictly as a JSON object matching the EtsyListing schema, including title, description, tags, suggested_price, category, seo_strategy, google_meta_title, google_meta_description, pinterest_title, pinterest_description, and image_alt_text."
    )

    corrected_data = listing_data
    if openai_client:
        try:
            openai_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
            response = openai_client.chat.completions.create(
                model=openai_model,
                messages=[{"role": "user", "content": correction_prompt}],
                response_format={"type": "json_object"},
                max_tokens=1000
            )
            corrected_data = json.loads(response.choices[0].message.content)
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

def write_etsy_listing(title, description, price="", client=None, presets: dict = None, image_facts: dict = None, variation_specs: list = None):
    """Write Etsy title, description, and tags from AliExpress details using Gemini or OpenAI."""
    if not client:
        client = get_genai_client()
    if presets is None:
        presets = {}
    if image_facts is None:
        image_facts = {}

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
    if custom_rules:
        custom_rules_str = f"8. CUSTOM INSTRUCTIONS: {custom_rules}\n"
    else:
        custom_rules_str = ""

    prompt = (
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
        "Guidelines:\n"
        "1. Etsy title: clearly state the product noun and top objective traits upfront. Keep it under 140 characters and preferably under 15 words. The first 50-60 characters must be readable in Google/Etsy search. Do not use pipe-separated keyword stuffing.\n"
        "2. Etsy title style: use commas or a colon only if helpful. Avoid repeated words, sale/shipping language, and subjective words like perfect, beautiful, amazing, or must-have.\n"
        "3. Description: first sentence must clearly identify the product in natural shopper language. Then write a detailed, structured Description focusing on value, features, and specs. Use double newlines (\\n\\n) to separate sections, paragraphs, list items, and key specifications. Do NOT output the description as a single dense paragraph.\n"
        "4. DIMENSIONS/SPECS: Prioritize exact measurements from 'Variation Specifications' and 'Image Facts'. If dimensions are unclear, missing, or empty, DO NOT mention dimensions at all. Do not invent or guess them.\n"
        "5. Etsy tags: provide exactly 13 unique relevant search tags. Each tag must be under 20 characters. Prefer multi-word phrases. Cover product identity, material/color/style, use case, audience/gift intent only if relevant, and long-tail niche phrases. Do not repeat the same root phrase across many tags.\n"
        "6. Cross-platform SEO: also generate google_meta_title, google_meta_description, pinterest_title, pinterest_description, and 3-5 image_alt_text suggestions. Keep these natural and accurate to the product.\n"
        "7. Suggest a retail price in USD (suggest a reasonable price if no price is provided).\n"
        f"{custom_rules_str}\n"
        "Output your response strictly as a JSON object matching the EtsyListing schema."
    )

    listing_data = None
    openai_client = get_openai_client()
    if openai_client:
        print("Generating Etsy-optimized listing content via OpenAI...")
        try:
            openai_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
            response = openai_client.chat.completions.create(
                model=openai_model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"}
            )
            raw_text = response.choices[0].message.content
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

    # Apply strict tag and cross-platform SEO guidelines
    listing_data = finalize_listing_seo(listing_data, seo_strategy, client)
    
    if not listing_data.get("category"):
        listing_data["category"] = "Not categorized"

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
                openai_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
                
                response = openai_client.chat.completions.create(
                    model=openai_model,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt},
                                {"type": "image_url", "image_url": {"url": data_uri}}
                            ]
                        }
                    ],
                    max_tokens=250
                )
                visual_details = response.choices[0].message.content.strip().replace('\n', ' ').strip()
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
            openai_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
            response = openai_client.chat.completions.create(
                model=openai_model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=100
            )
            visual_details = response.choices[0].message.content.strip().replace('\n', ' ').strip()
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
