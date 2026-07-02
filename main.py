import os
import sys
import json
import argparse
from src.scraper import scrape_aliexpress, sanitize_filename, parse_aliexpress_html
from src.ai_helper import (
    get_genai_client,
    generate_description_from_images,
    write_etsy_listing,
    generate_image_prompt_details
)
from src.image_gen import (
    load_themes,
    roll_theme_prompts,
    analyze_inspo_style,
    generate_prompts_from_inspo,
    generate_image_with_imagen
)

def parse_arguments():
    parser = argparse.ArgumentParser(description="Ultimate Etsy Listing Automation Script")
    
    # Inputs
    parser.add_argument("--url", type=str, help="AliExpress product URL to scrape")
    parser.add_argument("--html-file", type=str, help="Path to a local saved AliExpress HTML file")
    parser.add_argument("--text-fallback", type=str, help="Raw text description or path to a text file for description")
    
    # Style & Prompts
    parser.add_argument("--theme", type=str, default="bauhaus_beige", 
                        help="Theme key from themes.yaml (e.g. bauhaus_beige, cottagecore_rustic, cyberpunk_neon)")
    parser.add_argument("--inspo-image", type=str, help="Path to a local inspiration image to mimic style")
    parser.add_argument("--product-trigger", type=str, default="nanobananapro2 product",
                        help="Specific keyword/phrase to represent your product in the image prompts (e.g. 'nanobananapro banana earrings')")
    
    # Outputs
    parser.add_argument("--output-dir", type=str, default="outputs", help="Base directory for listing exports")
    parser.add_argument("--headed", action="store_true", help="Run Playwright in headed mode to manually solve captchas")
    parser.add_argument("--model", type=str, default="imagen-4.0-generate-001", 
                        help="Image generation model to use (e.g. imagen-4.0-generate-001, gemini-3.1-flash-image)")
    
    return parser.parse_args()

def main():
    args = parse_arguments()
    client = get_genai_client()
    
    title = ""
    price = ""
    description = ""
    image_paths = []
    
    # --- PHASE 1: DATA EXTRACTION ---
    if args.html_file:
        print(f"\n=== Phase 1: Parsing Local HTML File ===")
        scraped = parse_aliexpress_html(args.html_file)
        title = scraped.get("title", "")
        price = scraped.get("price", "")
        description = scraped.get("description_text", "")
        image_paths = scraped.get("image_paths", [])
        
        # Multimodal fallback if text description is missing or tiny
        if not description or len(description.strip()) < 50:
            if image_paths:
                description = generate_description_from_images(image_paths, client)
            else:
                print("Warning: No description or product images found to analyze.")
                description = "Generic product details (no description extracted)."
    elif args.url:
        print(f"\n=== Phase 1: Scraping AliExpress ===")
        scraped = scrape_aliexpress(args.url, headless=not args.headed)
        title = scraped.get("title", "")
        price = scraped.get("price", "")
        description = scraped.get("description_text", "")
        image_paths = scraped.get("image_paths", [])
        
        # Multimodal fallback if text description is missing or tiny
        if not description or len(description.strip()) < 50:
            if image_paths:
                description = generate_description_from_images(image_paths, client)
            else:
                print("Warning: No description or product images found to analyze.")
                description = "Generic product details (no description extracted)."
    elif args.text_fallback:
        print(f"\n=== Phase 1: Loading Text Input ===")
        if os.path.exists(args.text_fallback):
            with open(args.text_fallback, "r", encoding="utf-8") as f:
                description = f.read()
            title = os.path.basename(args.text_fallback).split(".")[0]
        else:
            description = args.text_fallback
            title = "Manual Product Listing"
    else:
        print("ERROR: You must provide either an AliExpress --url, --html-file path, or --text-fallback description.")
        sys.exit(1)
        
    print(f"Product Title: {title}")
    print(f"Product Description length: {len(description)} characters")
    
    # --- PHASE 2: AI COPYWRITING & GUARDRAILS ---
    print(f"\n=== Phase 2: Copywriting and Etsy Validation ===")
    etsy_listing = write_etsy_listing(title, description, price, client)
    
    if not etsy_listing:
        print("ERROR: Failed to generate Etsy listing content via Gemini.")
        sys.exit(1)
        
    print("\nGenerated Etsy Details:")
    print(f"Title: {etsy_listing['title']}")
    print(f"Price: {etsy_listing['suggested_price']}")
    print(f"Tags ({len(etsy_listing['tags'])}): {', '.join(etsy_listing['tags'])}")
    
    # --- PHASE 3: IMAGE GENERATION ---
    print(f"\n=== Phase 3: Rolling Theme & Generating Images ===")
    
    # Distill the parsed description into a brief visual physical description
    visual_details = generate_image_prompt_details(description, client)
    if visual_details:
        combined_trigger = f"{args.product_trigger}, {visual_details}"
    else:
        combined_trigger = args.product_trigger
    
    # Create the output folder for this listing
    product_slug = sanitize_filename(etsy_listing['title'] or "etsy_listing")
    product_output_dir = os.path.join(args.output_dir, product_slug)
    os.makedirs(product_output_dir, exist_ok=True)
    
    prompts_to_run = []
    
    if args.inspo_image:
        # User supplied an inspiration image - extract style and build prompts dynamically
        try:
            inspo_style = analyze_inspo_style(args.inspo_image, client)
            prompts_to_run = generate_prompts_from_inspo(inspo_style, combined_trigger)
        except Exception as e:
            print(f"Failed to use inspiration image: {e}. Falling back to default theme.")
            args.inspo_image = None # Reset to trigger normal themes loader
            
    if not args.inspo_image:
        # Standard configuration-based prompt rolling
        themes_config = load_themes("themes.yaml")
        if not themes_config:
            print("ERROR: themes.yaml not found or empty.")
            sys.exit(1)
        try:
            prompts_to_run = roll_theme_prompts(args.theme, themes_config, combined_trigger)
        except ValueError as e:
            print(f"ERROR: {e}")
            sys.exit(1)
            
    # Generate the images using Google Imagen 3
    generated_image_paths = []
    for image_item in prompts_to_run:
        img_name = image_item["name"]
        prompt = image_item["prompt"]
        
        output_image_name = f"{img_name}.png"
        output_image_path = os.path.join(product_output_dir, output_image_name)
        
        print(f"\nGenerating: {output_image_name}")
        local_path = generate_image_with_imagen(prompt, output_image_path, client, model=args.model)
        if local_path:
            generated_image_paths.append(local_path)
            
    # --- PHASE 4: LOCAL EXPORT ---
    print(f"\n=== Phase 4: Exporting Listing Data ===")
    
    # Save the listing text details as metadata.json
    metadata_path = os.path.join(product_output_dir, "metadata.json")
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(etsy_listing, f, indent=4, ensure_ascii=False)
        
    print(f"\n[SUCCESS] Listing automation complete!")
    print(f"Listing Output Directory: {os.path.abspath(product_output_dir)}")
    print(f"Created metadata: {os.path.basename(metadata_path)}")
    print(f"Created images:")
    for path in generated_image_paths:
        print(f"  - {os.path.basename(path)}")

if __name__ == "__main__":
    main()
