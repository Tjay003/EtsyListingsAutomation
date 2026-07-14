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
    primary_keywords: List[str] = Field(default_factory=list, description="Most important buyer search phrases for Etsy")
    long_tail_keywords: List[str] = Field(default_factory=list, description="Specific multi-word phrases likely to convert")
    tag_keywords: List[str] = Field(default_factory=list, description="Candidate Etsy tags, preferably 20 characters or less")

class EtsyListing(BaseModel):
    title: str = Field(description="One Etsy-ready marketplace title, maximum 140 characters")
    description: str = Field(description="Etsy product description with a safe lifestyle/story opening followed by confirmed product details. Make sure to use double newlines (\\n\\n) between paragraphs, features, and specs to avoid a single dense block of text.")
    tags: List[str] = Field(description="13 relevant search keywords or short tag phrases for Etsy listings")
    suggested_price: str = Field(description="Suggested Etsy retail price in USD, e.g., '$24.99'")
    category: str = Field(description="The most accurate Etsy category path or specific category name (e.g., 'Home & Living > Home Decor' or 'Crossbody Bags')")
    seo_strategy: SEOStrategy = Field(default_factory=SEOStrategy, description="Keyword and positioning strategy used to write the listing")
    seo_quality_score: int = Field(default=0, description="Deterministic SEO QA score from 0 to 100")
    seo_qa_notes: List[str] = Field(default_factory=list, description="Issues or warnings from deterministic SEO QA")
    repair_instructions: List[str] = Field(default_factory=list, description="Exact deterministic repairs required before the listing is publication-ready")
    needs_review: bool = Field(default=False, description="True when deterministic QA found issues that should be checked before publishing")
    review_reasons: List[str] = Field(default_factory=list, description="Short human review reasons")

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
    clean = str(text or "")
    for term in PROHIBITED_LISTING_TERMS:
        clean = re.sub(re.escape(term), "", clean, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", clean).strip()

def _strip_subjective_title_terms(text):
    clean = str(text or "")
    for term in SUBJECTIVE_TITLE_TERMS:
        clean = re.sub(rf"\b{re.escape(term)}\b", "", clean, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", clean).strip(" ,-")

def _strip_description_hype(text):
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
    clean = re.sub(r"\s+([,.;:])", r"\1", clean)
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
        "- Include a mix of exact product phrases, broad category phrases, use-case phrases, and style/material phrases.\n\n"
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
    clean = _strip_description_hype(_strip_prohibited_terms(tag)).lower()
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
    clean = _strip_variation_label(clean)
    clean = re.sub(r"\s*[\|/]\s*", ", ", clean)
    clean = re.sub(r"\s+", " ", clean).strip(" ,-")
    return _trim_at_word(clean, MAX_ETSY_TITLE_CHARS)

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
    return _trim_at_word(title, MAX_ETSY_TITLE_CHARS)

def _clean_marketplace_title(title, description, seo_strategy):
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
    return _trim_at_word(clean, MAX_ETSY_TITLE_CHARS)

def _normalize_listing_category(listing_data, seo_strategy=None):
    inferred = _infer_listing_category(listing_data, seo_strategy)
    current = str(listing_data.get("category") or "").strip()
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
        # Supplier prices are usually lower than Etsy retail; use a simple margin floor.
        return _format_usd_price(max(source * 1.8, source + 8))

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
    description = _strip_description_hype(listing_data.get("description", ""))
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
    if len(title) < MIN_MARKETPLACE_TITLE_CHARS:
        score -= 12
        notes.append("Etsy title is short; add more objective search detail while staying readable.")
    if len(title_words) > IDEAL_MARKETPLACE_TITLE_WORDS:
        score -= 8
        notes.append("Etsy title is over the preferred readability target.")
    if _title_phrase_count(title) > MAX_MARKETPLACE_TITLE_PHRASES:
        score -= 8
        notes.append("Etsy title uses too many comma/colon phrase chunks.")
    if _title_has_variation_leakage(title):
        score -= 20
        notes.append("Etsy title appears to contain raw variation labels such as Color/Size.")
    if "|" in title:
        score -= 6
        notes.append("Etsy title still uses pipe-separated keyword formatting.")
    if _is_keyword_stuffed_title(title):
        score -= 10
        notes.append("Etsy title reads like a keyword list instead of one clean shopper-facing title.")
    if any(term in title_lower for term in SUBJECTIVE_TITLE_TERMS):
        score -= 5
        notes.append("Etsy title includes subjective wording better suited for the description.")
    if len(set(word.lower() for word in title_words)) < max(1, len(title_words) - 2):
        score -= 5
        notes.append("Etsy title repeats too many words.")
    if any(term in f"{title} {description}".lower() for term in PROHIBITED_LISTING_TERMS):
        score -= 20
        notes.append("Listing contains prohibited supplier/platform language.")
    listing_text = " ".join([
        title,
        description,
        " ".join(str(tag) for tag in tags),
    ]).lower()
    for claim, support_terms in RISKY_UNSUPPORTED_CLAIMS.items():
        if any(term in listing_text for term in support_terms) and not _source_supports_claim(source_context, support_terms):
            score -= 8
            notes.append(f"Potential unsupported claim: {claim}.")
    if any(term in listing_text for term in TRADEMARK_RISK_TERMS):
        score -= 15
        notes.append("Possible trademark/IP term detected; review before publishing.")

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
    if "product details:" not in description.lower():
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
    elif len(title) < MIN_MARKETPLACE_TITLE_CHARS:
        repairs.append("Rewrite the title to about 80-125 characters while staying readable; add only objective supported search details from the source facts.")
    if len(title) > MAX_ETSY_TITLE_CHARS:
        repairs.append("Shorten the title to 140 characters or less without removing the main product noun.")
    if len(title_words) > IDEAL_MARKETPLACE_TITLE_WORDS:
        repairs.append("Simplify the title to roughly 18 words or fewer so it reads like one shopper-facing title.")
    if _title_phrase_count(title) > MAX_MARKETPLACE_TITLE_PHRASES or "|" in title:
        repairs.append("Rewrite the title as one natural Etsy title with no pipe separators and no more than three comma or colon chunks.")
    if _title_has_variation_leakage(title) or re.search(r"\{[^}]+['\"]?(trait|value)['\"]?[^}]*\}", title_lower):
        repairs.append("Remove raw variation labels and dict-shaped text from the title, including Color:, Size:, trait, and value fragments.")
    if _is_keyword_stuffed_title(title):
        repairs.append("Rewrite the title so it is not a keyword list; keep the product noun first and use natural phrasing.")
    if any(term in title_lower for term in SUBJECTIVE_TITLE_TERMS):
        repairs.append("Remove subjective or risky title words such as perfect, beautiful, luxury, designer, handmade, and eco-friendly unless directly supported.")

    if not description:
        repairs.append("Write a description with a safe lifestyle/story opening followed by a Product Details: section using only confirmed facts.")
    else:
        if not _first_sentence(description):
            repairs.append("Add a clear first sentence that naturally includes the main product keyword for SEO.")
        if "product details:" not in description_lower:
            repairs.append("Add a Product Details: section after the story opening and list only confirmed facts from the source, image facts, or variation specs.")
        if re.search(r"\b(is|are|making it|makes it)\s+for\b", description_lower):
            repairs.append("Fix awkward grammar left by cleanup, such as 'is for' or 'making it for', while keeping cautious factual wording.")

    if any(term in listing_text for term in PROHIBITED_LISTING_TERMS):
        repairs.append("Remove supplier/platform language such as AliExpress, factory, wholesale, dropshipping, bulk order, bulk pricing, or bulk sale.")
    for claim, support_terms in RISKY_UNSUPPORTED_CLAIMS.items():
        if any(term in listing_text for term in support_terms) and not _source_supports_claim(source_context, support_terms):
            repairs.append(f"Remove or soften unsupported {claim} claims unless the exact source context supports them.")
    if any(term in listing_text for term in TRADEMARK_RISK_TERMS):
        repairs.append("Possible trademark/IP term detected; keep it only if it is the literal product identity and mark for human review.")

    if len(tags) != TAG_COUNT:
        repairs.append("Return exactly 13 Etsy tags.")
    if any(len(str(tag)) > MAX_ETSY_TAG_CHARS for tag in tags):
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
        "You are revising an Etsy listing in STRICT QUALITY mode.\n"
        "Fix every item listed in Required Repairs. Accuracy is more important than rich marketing copy.\n"
        "Use only facts supported by Source Context, Image Facts, or SEO Strategy. If a detail is uncertain, omit it.\n"
        "Keep the description cautious but readable: start with a safe lifestyle/story opening, then add a Product Details section with only confirmed facts.\n"
        "Do not invent materials, dimensions, pockets, waterproofing, handmade/eco/luxury/designer claims, compatibility, or capacity.\n"
        "Write one natural Etsy title, ideally 80-125 characters, with the product noun early and no raw Color:/Size: labels.\n\n"
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
            openai_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
            response = openai_client.chat.completions.create(
                model=openai_model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                max_tokens=1400,
            )
            return json.loads(response.choices[0].message.content)
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
        f"Description: {listing_data.get('description', '')}\n\n"
        "SEO Strategy:\n"
        f"{strategy_part}\n\n"
        "Scraped Info:\n"
        f"{scraped_part}\n\n"
        "Image Facts (Extracted directly from product photos/charts):\n"
        f"{facts_part}\n\n"
        "CRITICISM CRITERIA:\n"
        "1. ACCURACY: Check for hallucinations or approximations. If Image Facts specify exact dimensions (e.g. 'Height: 38cm'), does the Description use that exact number? If not, it is an issue. Did the Description invent sizes or facts that are not present in either source?\n"
        "2. TITLE QUALITY: Is there one clean Etsy-ready title? Is it under 140 chars, ideally 80-125 chars, readable, and clear in the first 50-60 characters? Does it avoid raw variation labels like 'Color:', use no more than 3 comma/colon chunks, and avoid tag-list formatting, repeated words, and subjective/risky words like perfect, beautiful, luxury, designer, handmade, or eco-friendly unless directly supported?\n"
        "3. DESCRIPTION STRUCTURE: Does the description start with a safe lifestyle/story opening that naturally includes the main product keyword but does not add concrete unsupported facts? Does it then move into a clear Product Details section that only lists confirmed facts?\n"
        "4. TAG COMPLIANCE: Are there exactly 13 unique multi-word tags where possible? Is every tag 20 characters or less? Do the tags cover product identity, traits, use cases, style/material, and long-tail phrases without repetition?\n"
        "5. ETSY SEO: Do the title, first description sentence, specific category path, and tags work together without keyword stuffing? Is the suggested price a realistic USD price and not blank or 0?\n"
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
        "Make sure the description starts with a safe lifestyle/story opening for readability and SEO, then moves into a Product Details section containing only confirmed facts.\n"
        "Use double newlines (\\n\\n) to separate the story opening, Product Details, notes, and policy/footer sections so it is clean, structured, and highly readable.\n"
        "Use one clean Etsy marketplace title, ideally 80-125 characters, with the main product noun early and objective differentiators after it. Keep it buyer-friendly, not keyword-stuffed. Remove raw variation labels like 'Color:' and avoid risky claims unless source-supported. Put extra keyword coverage in tags and the description instead of creating separate metadata fields.\n\n"
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
    owner_rules = ""
    if custom_rules:
        owner_rules = (
            "SHOP OWNER COPYWRITING RULES (high priority):\n"
            f"{custom_rules}\n"
            "Follow these unless they conflict with factual accuracy, source support, Etsy compliance, or marketplace safety.\n\n"
        )

    quality_rules = ""
    if quality_mode:
        quality_rules = (
            "STRICT QUALITY MODE:\n"
            "- Be conservative. If a product detail is not directly supported by source text, specs, variation specs, or extracted image facts, omit it.\n"
            "- A light storytelling style is allowed for lifestyle context and shopper flow, but concrete product facts must stay source-backed.\n"
            "- The opening paragraph can explain how the item fits into a routine, outfit, room, or simple use moment, but must not imply unsupported features or performance.\n"
            "- Do not mention materials, dimensions, capacity, pockets, closures, waterproofing, handmade/eco/luxury/designer positioning, compatibility, or gift/audience claims unless supported.\n"
            "- Use cautious wording for visible styling only. Do not turn visual guesses into hard product facts.\n"
            "- If a trademark/brand/character term appears, keep it only when it is the literal product identity and expect human review.\n\n"
        )

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
        f"{owner_rules}"
        f"{quality_rules}"
        "Guidelines:\n"
        "1. Etsy-first title: write ONE clean title for the Etsy title field. Use this pattern: [primary product keyword] + [1-2 objective differentiators such as material/color/style] + [real use case if relevant].\n"
        "2. Title style: keep the title under 140 characters and ideally 80-125 characters. Use no more than 3 comma/colon-separated chunks. Do not write a long list of tags in the title. Never include raw variation labels such as 'Color:' or 'Size:'. Avoid repeated words, sale/shipping language, and subjective/risky words like perfect, beautiful, amazing, luxury, designer, handmade, or eco-friendly unless directly supported by the source facts.\n"
        "3. Description structure: start with a safe lifestyle/story opening paragraph of 2-3 sentences. The first sentence must naturally include the main product keyword for SEO, but the story must stay general and must not introduce concrete unsupported facts.\n"
        "4. Product Details section: after the story opening, add a clear 'Product Details:' section. List only confirmed facts from the source title, specs, Image Facts, or Variation Specifications. If a detail is unknown, leave it out instead of guessing.\n"
        "5. Buyer note: when useful, add a short cautious note such as 'Please review the photos for exact color, texture, and proportions.' Do not use this note to hide invented details.\n"
        "6. Formatting: use double newlines (\\n\\n) to separate the story opening, Product Details, optional note, and policy/footer sections. Do NOT output the description as a single dense paragraph.\n"
        "7. DIMENSIONS/SPECS: Prioritize exact measurements from 'Variation Specifications' and 'Image Facts'. If dimensions are unclear, missing, or empty, DO NOT mention dimensions at all. Do not invent or guess them.\n"
        "8. Category: choose a specific Etsy-style category path where possible, e.g. 'Bags & Purses > Backpacks' instead of a vague category. Never return 'Not categorized'.\n"
        "9. Etsy tags: provide exactly 13 unique relevant search tags. Each tag must be under 20 characters. Prefer multi-word phrases. Cover product identity, material/color/style, use case, audience/gift intent only if relevant, and long-tail niche phrases. Do not repeat the same root phrase across many tags.\n"
        "10. Etsy SEO balance: use natural keyword phrases in the title, tags, and first description paragraph. Do not keyword-stuff the story opening.\n"
        "11. Suggest a realistic retail price in USD. Never return blank, 0, or '0'. If source price is low supplier pricing, suggest a realistic Etsy retail price.\n"
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
