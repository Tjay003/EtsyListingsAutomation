import os
import io
import random
import yaml
from PIL import Image
from google import genai
from google.genai import types
from src.ai_helper import get_genai_client

FAL_IMAGE_MODELS = {
    "flux-kontext-dev": {
        "model": "fal-ai/flux-kontext/dev",
        "label": "Flux Kontext Dev",
        "square_argument": ("resolution_mode", "1:1"),
        "input_image_argument": "image_url",
        "input_image_list": False,
        "description": "Lower-cost Flux Kontext testing model.",
        "recommended_for": "Testing product edits before using the Pro model.",
    },
    "flux-kontext-pro": {
        "model": "fal-ai/flux-pro/kontext",
        "label": "Flux Kontext Pro",
        "square_argument": ("aspect_ratio", "1:1"),
        "input_image_argument": "image_url",
        "input_image_list": False,
        "description": "Default balanced image-to-image model for accurate product edits.",
        "recommended_for": "Variation batches and reliable day-to-day listing images.",
    },
    "nano-banana-2-edit": {
        "model": "fal-ai/nano-banana-2/edit",
        "label": "Nano Banana 2 Edit",
        "square_argument": ("aspect_ratio", "1:1"),
        "input_image_argument": "image_urls",
        "input_image_list": True,
        "extra_arguments": {
            "resolution": "1K",
            "limit_generations": True,
        },
        "supports_thinking": True,
        "thinking_levels": ["minimal", "high"],
        "description": "Smarter Google image-edit model with optional thinking.",
        "recommended_for": "Hero/showcase images where accuracy and scene reasoning matter most.",
    },
}

DEFAULT_FAL_MODEL_KEY = "flux-kontext-pro"

def resolve_fal_image_settings(model_key=None):
    selected_model_key = model_key or DEFAULT_FAL_MODEL_KEY
    if selected_model_key not in FAL_IMAGE_MODELS:
        selected_model_key = DEFAULT_FAL_MODEL_KEY

    model_config = FAL_IMAGE_MODELS[selected_model_key]
    return {
        "model_key": selected_model_key,
        "model": model_config["model"],
        "label": model_config["label"],
        "square_argument": model_config.get("square_argument"),
        "input_image_argument": model_config.get("input_image_argument", "image_url"),
        "input_image_list": model_config.get("input_image_list", False),
        "extra_arguments": model_config.get("extra_arguments", {}),
        "supports_thinking": model_config.get("supports_thinking", False),
        "thinking_levels": model_config.get("thinking_levels", []),
        "description": model_config.get("description", ""),
        "recommended_for": model_config.get("recommended_for", ""),
    }

def generate_image_with_fal(prompt, input_image_path, output_path, model_key=None, thinking_level=None, input_image_paths=None):
    """Generate image-to-image using the configured Fal.ai model."""
    try:
        import fal_client
        import requests
        
        api_key = os.getenv("FAL_KEY")
        if not api_key:
            print("Fal.ai API key (FAL_KEY) not found in environment.")
            return None
            
        os.environ["FAL_KEY"] = api_key
        
        if not model_key:
            env_model = os.getenv("FAL_MODEL")
            model_key = next(
                (key for key, config in FAL_IMAGE_MODELS.items() if config["model"] == env_model),
                DEFAULT_FAL_MODEL_KEY,
            )

        settings = resolve_fal_image_settings(model_key)
        model = settings["model"]
        final_prompt = prompt

        reference_paths = input_image_paths or [input_image_path]
        reference_paths = [path for path in reference_paths if path and os.path.exists(path)]
        if not reference_paths:
            print("No valid Fal.ai reference images were provided.")
            return None

        if not settings.get("input_image_list") and len(reference_paths) > 1:
            reference_paths = reference_paths[:1]

        print(f"Uploading {len(reference_paths)} reference image(s) to Fal.ai...")
        image_urls = [fal_client.upload_file(path) for path in reference_paths]
        
        thinking_level = (thinking_level or "").strip().lower()
        active_thinking = ""
        if settings.get("supports_thinking") and thinking_level in settings.get("thinking_levels", []):
            active_thinking = thinking_level

        thinking_note = f" with {active_thinking} thinking" if active_thinking else ""
        print(f"Generating Fal.ai img2img ({settings['label']}{thinking_note}) using {len(image_urls)} reference image(s)...")
        
        arguments = {
            "prompt": final_prompt,
            "num_images": 1,
            "output_format": "png",
        }
        input_image_argument = settings.get("input_image_argument", "image_url")
        if settings.get("input_image_list"):
            arguments[input_image_argument] = image_urls
        else:
            arguments[input_image_argument] = image_urls[0]

        square_argument = settings.get("square_argument")
        if square_argument:
            arg_name, arg_value = square_argument
            arguments[arg_name] = arg_value

        arguments.update(settings.get("extra_arguments") or {})
        if active_thinking:
            arguments["thinking_level"] = active_thinking
        
        # Call Fal.ai
        result = fal_client.subscribe(model, arguments=arguments)
        
        if result and "images" in result and len(result["images"]) > 0:
            output_url = result["images"][0]["url"]
            print(f"Downloading Fal.ai output image from: {output_url}")
            img_res = requests.get(output_url, timeout=30)
            if img_res.status_code == 200:
                with open(output_path, "wb") as f:
                    f.write(img_res.content)
                print(f"Successfully saved Fal.ai image to {output_path}")
                return output_path
            else:
                print(f"Failed to download image from Fal.ai. Status: {img_res.status_code}")
        else:
            print("Fal.ai response contained no images.")
            
        return None
    except Exception as e:
        print(f"Error during Fal.ai generation: {e}")
        return None

def generate_image_with_imagen(prompt, output_path, client=None, model="imagen-4.0-generate-001", reference_image=None, fal_model_key=None, fal_thinking_level=None, reference_images=None):
    """Generate a single image using Fal.ai (if key present), Google Imagen, or free Pollinations fallback."""
    # 1. Check if Fal.ai API key is configured and we have a reference image
    fal_key = os.getenv("FAL_KEY")
    reference_paths = reference_images or ([reference_image] if reference_image else [])
    reference_paths = [path for path in reference_paths if path and os.path.exists(path)]
    if fal_key and reference_paths:
        local_path = generate_image_with_fal(
            prompt,
            reference_paths[0],
            output_path,
            model_key=fal_model_key,
            thinking_level=fal_thinking_level,
            input_image_paths=reference_paths,
        )
        if local_path:
            return local_path
            
    # 2. Check if user preferred free generation in .env
    use_free = os.getenv("USE_FREE_GENERATOR", "false").lower() == "true"
    
    if use_free:
        return generate_free_image(prompt, output_path)
        
    if not client:
        client = get_genai_client()
        
    print(f"Sending prompt to {model}: {prompt}")
    try:
        if "gemini" in model.lower():
            # Gemini Image models use generate_content and return image bytes in response parts
            response = client.models.generate_content(
                model=model,
                contents=prompt
            )
            if response.candidates and response.candidates[0].content.parts:
                for part in response.candidates[0].content.parts:
                    if hasattr(part, 'inline_data') and part.inline_data:
                        data = part.inline_data.data
                        image = Image.open(io.BytesIO(data))
                        image.save(output_path)
                        print(f"Successfully saved image: {output_path}")
                        return output_path
            print(f"No image data found in response from {model}.")
            if response.text:
                print(f"Response text: {response.text}")
        else:
            # Imagen models use generate_images
            result = client.models.generate_images(
                model=model,
                prompt=prompt,
                config=types.GenerateImagesConfig(
                    number_of_images=1,
                    output_mime_type="image/png",
                    aspect_ratio="1:1",
                    person_generation="ALLOW_ADULT"
                )
            )
            
            if result.generated_images:
                generated_image = result.generated_images[0]
                image_bytes = generated_image.image.image_bytes
                image = Image.open(io.BytesIO(image_bytes))
                image.save(output_path)
                print(f"Successfully saved image: {output_path}")
                return output_path
            else:
                print("No images were returned by the Imagen API.")
                
    except Exception as e:
        print(f"Error calling Google Image API: {e}")
        if "400" in str(e) or "429" in str(e) or "quota" in str(e).lower() or "billing" in str(e).lower():
            print("\n[NOTE] Google AI Studio requires billing for Imagen. Falling back to free generator (FLUX)...")
            return generate_free_image(prompt, output_path)
    return None

def generate_free_image(prompt, output_path, max_retries=3, initial_delay=5):
    """Generate a high-quality image for free using Pollinations.ai (FLUX model), with retries."""
    import urllib.parse
    import requests
    import time
    
    encoded_prompt = urllib.parse.quote(prompt)
    url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&nologo=true&private=true&model=flux"
    
    delay = initial_delay
    for attempt in range(max_retries):
        print(f"Generating free image via Pollinations.ai (FLUX model): {prompt[:60]}... (Attempt {attempt + 1}/{max_retries})")
        try:
            response = requests.get(url, timeout=45)
            if response.status_code == 200:
                image = Image.open(io.BytesIO(response.content))
                image.save(output_path)
                print(f"Successfully saved free image: {output_path}")
                # Add a brief rest after success to prevent hitting subsequent rate limits
                time.sleep(3)
                return output_path
            elif response.status_code == 429:
                print(f"Pollinations.ai rate limit hit (429). Retrying in {delay} seconds...")
                time.sleep(delay)
                delay += 5
            else:
                print(f"Free generation failed with status code {response.status_code}. Retrying in {delay} seconds...")
                time.sleep(delay)
                delay += 5
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            print(f"Network timeout or connection error: {e}. Retrying in {delay} seconds...")
            time.sleep(delay)
            delay += 5
        except Exception as e:
            print(f"Unexpected error in free image generation: {e}")
            break
            
    print(f"Failed to generate free image after {max_retries} attempts.")
    return None

def analyze_inspo_style(inspo_image_path, client=None):
    """Analyze an inspiration image to extract style, lighting, and background keywords."""
    if not client:
        client = get_genai_client()
        
    if not os.path.exists(inspo_image_path):
        raise FileNotFoundError(f"Inspiration image not found at: {inspo_image_path}")
        
    print(f"Analyzing inspiration image style: {inspo_image_path}")
    try:
        pil_image = Image.open(inspo_image_path)
        prompt = (
            "Analyze this reference photograph. Focus strictly on describing its setting, "
            "background, lighting style, color palette, props, textures, and camera angle/mood. "
            "Write a single, highly detailed paragraph (around 80 words) describing this environment "
            "in a way that can be used for text-to-image prompts. Do not mention any specific product "
            "currently in the image, only describe the backdrop and scene."
        )
        
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[prompt, pil_image]
        )
        style_description = response.text.strip()
        print(f"Extracted Inspo Style: {style_description}")
        return style_description
    except Exception as e:
        print(f"Error analyzing inspiration image: {e}")
        return "minimalist product studio showcase, clean soft lighting, solid neutral backdrop"

def generate_prompts_from_inspo(inspo_style, product_trigger="nanobananapro2"):
    """Generate a custom set of Showcase, Worn, and Detail prompts based on the inspo image analysis."""
    # Define standard templates using the analyzed style description
    return [
        {
            "name": "1_showcase",
            "prompt": f"{product_trigger} product, professional product photography, centered and showcasing the product, {inspo_style}, clean and sharp focus"
        },
        {
            "name": "2_worn_or_used",
            "prompt": f"{product_trigger} product, worn by a modern model, lifestyle setting, {inspo_style}, natural commercial depth of field"
        },
        {
            "name": "3_detail_close_up",
            "prompt": f"macro detailed close-up shot of {product_trigger} product, emphasizing textures and intricate craftsmanship, {inspo_style}, high contrast shadows"
        }
    ]
