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

def write_etsy_listing(title, description, price="", client=None):
    """Write Etsy title, description, and tags from AliExpress details using Gemini or OpenAI."""
    if not client:
        client = get_genai_client()
        
    print("Generating Etsy-optimized listing content...")
    
    prompt = (
        f"Create an Etsy listing for the following product:\n"
        f"Original Title: {title}\n"
        f"Scraped Description/Info: {description}\n"
        f"Estimated Price: {price}\n\n"
        "Guidelines:\n"
        "1. Write an SEO-friendly, catchy Title under 140 characters.\n"
        "2. Write a detailed, structured Description focusing on value, features, and specs.\n"
        "3. Provide exactly 13 relevant search Tags (keywords or phrases). Each tag must be under 20 characters.\n"
        "4. Suggest a retail price in USD (suggest a reasonable price if no price is provided).\n\n"
        "Output your response strictly as a JSON object with keys: 'title', 'description', 'tags' (list of strings), and 'suggested_price'."
    )
    
    # Try OpenAI first if configured
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
            
            # Apply strict guardrails:
            # A. Condense tags > 20 characters
            listing_data["tags"] = clean_tags(listing_data["tags"], client)
            
            # B. Inject cancellation/return policy footer
            policy_footer = (
                "\n\n---\n"
                "Cancellation Policy: Cancellation is allowed within 5 hours after placing the order.\n"
                "Returns & Refunds Policy: Returns and refunds are accepted for items that arrive damaged or incorrect only."
            )
            listing_data["description"] = listing_data["description"].strip() + policy_footer
            return listing_data
        except Exception as e:
            print(f"Error generating listing content via OpenAI: {e}. Falling back to Gemini...")
            
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
        
        # Apply strict guardrails:
        # A. Condense tags > 20 characters
        listing_data["tags"] = clean_tags(listing_data["tags"], client)
        
        # B. Inject cancellation/return policy footer
        policy_footer = (
            "\n\n---\n"
            "Cancellation Policy: Cancellation is allowed within 5 hours after placing the order.\n"
            "Returns & Refunds Policy: Returns and refunds are accepted for items that arrive damaged or incorrect only."
        )
        listing_data["description"] = listing_data["description"].strip() + policy_footer
        
        return listing_data
        
    except Exception as e:
        print(f"Error generating listing content: {e}")
        return None

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
