import os
import json
import re
import time
from PIL import Image
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from typing import List
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
class EtsyListing(BaseModel):
    title: str = Field(description="Search-optimized Etsy product title, maximum 140 characters")
    description: str = Field(description="High-converting product description highlighting key features and specifications")
    tags: List[str] = Field(description="13 relevant search keywords or short tag phrases for Etsy listings")
    suggested_price: str = Field(description="Suggested Etsy retail price in USD, e.g., '$24.99'")

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

def review_and_refine_listing(listing_data: dict, scraped_text: str, image_facts: dict, client=None) -> dict:
    """Evaluate generated listing quality against image_facts and scraped text, doing a single correction pass if issues are found."""
    if not client:
        client = get_genai_client()

    scraped_part = scraped_text or "None provided"
    facts_part = json.dumps(image_facts, indent=2) if image_facts else "None extracted from images"

    prompt = (
        "You are a strict QA critic for Etsy listings.\n"
        "Analyze the draft Etsy listing against the Scraped Info and the Image Facts extracted from product photos.\n\n"
        "Draft Etsy Listing:\n"
        f"Title: {listing_data.get('title', '')}\n"
        f"Price: {listing_data.get('suggested_price', '')}\n"
        f"Tags: {', '.join(listing_data.get('tags', []))}\n"
        f"Description: {listing_data.get('description', '')}\n\n"
        "Scraped Info:\n"
        f"{scraped_part}\n\n"
        "Image Facts (Extracted directly from product photos/charts):\n"
        f"{facts_part}\n\n"
        "CRITICISM CRITERIA:\n"
        "1. ACCURACY: Check for hallucinations or approximations. If Image Facts specify exact dimensions (e.g. 'Height: 38cm'), does the Description use that exact number? If not, it is an issue. Did the Description invent sizes or facts that are not present in either source?\n"
        "2. TITLE QUALITY: Is the title under 140 chars? Does it mention key attributes (materials, styling) from the facts?\n"
        "3. TAG COMPLIANCE: Are there exactly 13 tags? Is any tag longer than 20 characters?\n"
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

    correction_prompt = (
        "You are an expert copywriter. Revise the following draft Etsy listing based on the critic feedback.\n"
        "Ensure all details are 100% accurate to the product specifications and images.\n\n"
        "Draft Listing:\n"
        f"Title: {listing_data.get('title', '')}\n"
        f"Price: {listing_data.get('suggested_price', '')}\n"
        f"Tags: {', '.join(listing_data.get('tags', []))}\n"
        f"Description: {listing_data.get('description', '')}\n\n"
        "Critic Feedback:\n"
        f"1. Title issues: {verdict.get('title_issues', 'None')}\n"
        f"2. Description issues: {verdict.get('description_issues', 'None')}\n"
        f"3. Tag issues: {verdict.get('tag_issues', 'None')}\n\n"
        "Image Facts (For Reference):\n"
        f"{facts_part}\n\n"
        "Output your corrected listing strictly as a JSON object matching the EtsyListing schema (title, description, tags, suggested_price)."
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

    facts_str = ""
    if image_facts:
        facts_str = "\n".join([f"{k.upper()}: {v}" for k, v in image_facts.items() if v])
    if not facts_str:
        facts_str = "None extracted"

    var_str = ""
    if variation_specs:
        var_str = "\n".join([
            f"- {v.get('name')}: Size = {v.get('size') or 'N/A'}, Dimensions = {v.get('dimensions') or 'N/A'}"
            for v in variation_specs if isinstance(v, dict)
        ])
    if not var_str:
        var_str = "None extracted"

    prompt = (
        f"Create an Etsy listing for the following product:\n"
        f"Original Title: {title}\n"
        f"Scraped Description/Info: {description}\n"
        f"Estimated Price: {price}\n\n"
        "Image Facts (Extracted directly from product photos/spec charts):\n"
        f"{facts_str}\n\n"
        "Variation Specifications (Extracted sizes/dimensions for specific options):\n"
        f"{var_str}\n\n"
        "Guidelines:\n"
        "1. Write an SEO-friendly, catchy Title under 140 characters.\n"
        "2. Write a detailed, structured Description focusing on value, features, and specs.\n"
        "3. DIMENSIONS/SPECS: Prioritize exact measurements from 'Variation Specifications' and 'Image Facts' over the 'Scraped Description' if they conflict. If variations have different sizes (e.g. S, M, L), include a clear size guide listing each variation and its corresponding dimensions in the description.\n"
        "4. Provide exactly 13 relevant search Tags (keywords or phrases). Each tag must be under 20 characters.\n"
        "5. Suggest a retail price in USD (suggest a reasonable price if no price is provided).\n\n"
        "Output your response strictly as a JSON object with keys: 'title', 'description', 'tags' (list of strings), and 'suggested_price'."
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
    listing_data = review_and_refine_listing(listing_data, description, image_facts, client=client)

    # Apply strict tag guidelines
    listing_data["tags"] = clean_tags(listing_data["tags"], client)

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
