import os
import io
import random
import yaml
from PIL import Image
from google import genai
from google.genai import types
from src.ai_helper import get_genai_client

def load_themes(config_path="themes.yaml"):
    """Load the YAML configuration file for themes."""
    if not os.path.exists(config_path):
        print(f"Warning: themes config not found at {config_path}. Using basic templates.")
        return {}
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def generate_image_with_fal(prompt, input_image_path, output_path):
    """Generate image-to-image using Fal.ai SDK with FLUX or SDXL."""
    try:
        import fal_client
        import requests
        
        api_key = os.getenv("FAL_KEY")
        if not api_key:
            print("Fal.ai API key (FAL_KEY) not found in environment.")
            return None
            
        os.environ["FAL_KEY"] = api_key
        
        # Default to FLUX Dev image-to-image
        model = os.getenv("FAL_MODEL", "fal-ai/flux/dev/image-to-image")
        strength = float(os.getenv("FAL_STRENGTH", "0.75"))
        
        print(f"Uploading reference image: {input_image_path} to Fal.ai...")
        image_url = fal_client.upload_file(input_image_path)
        
        print(f"Generating Fal.ai img2img ({model}) using reference URL: {image_url}...")
        
        # Prepare parameters
        arguments = {
            "prompt": prompt,
            "image_url": image_url,
            "strength": strength,
        }
        
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

def generate_image_with_imagen(prompt, output_path, client=None, model="imagen-4.0-generate-001", reference_image=None):
    """Generate a single image using Fal.ai (if key present), Google Imagen, or free Pollinations fallback."""
    # 1. Check if Fal.ai API key is configured and we have a reference image
    fal_key = os.getenv("FAL_KEY")
    if fal_key and reference_image and os.path.exists(reference_image):
        local_path = generate_image_with_fal(prompt, reference_image, output_path)
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

def roll_theme_prompts(theme_name, themes_config, product_trigger="nanobananapro2"):
    """Roll a prompt for each image section of the theme, inserting the product trigger."""
    theme = themes_config.get("themes", {}).get(theme_name)
    if not theme:
        raise ValueError(f"Theme '{theme_name}' was not found in themes configuration.")
        
    images_to_generate = []
    print(f"Rolling prompts for theme '{theme.get('name', theme_name)}'...")
    
    for image_sec in theme.get("images", []):
        section_name = image_sec.get("name")
        prompts_list = image_sec.get("prompts", [])
        
        if not prompts_list:
            continue
            
        # Randomly choose (roll) one of the variations
        selected_prompt = random.choice(prompts_list)
        
        # Replace the default placeholder with the user's custom product trigger/description
        if "nanobananapro2" in selected_prompt:
            selected_prompt = selected_prompt.replace("nanobananapro2", product_trigger)
            
        images_to_generate.append({
            "name": section_name,
            "prompt": selected_prompt
        })
        print(f"  - Rolled section '{section_name}': {selected_prompt[:60]}...")
        
    return images_to_generate

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
