# Listing Production Studio Storage Plan

This project is evolving into a listing production studio, not a one-shot scraper. The storage design should preserve product source material for batch processing, future edits, and AI image regeneration while still keeping deployment simple.

## Current Local Behavior

- The Chrome extension scrapes product text, specs, and image URLs from AliExpress.
- The local FastAPI backend receives the payload through `/api/queue-product`.
- The backend downloads selected images into `OUTPUT_DIR`.
- If `OUTPUT_DIR` is not set, the backend defaults to `~/Downloads/AliExpressQueue`.
- The dashboard settings can change `OUTPUT_DIR`, which is why files may appear in `C:\Users\Tyrone James Bacolod\Downloads\AliExpressQueue` instead of the repo `outputs/` folder.

For local development, this is still useful. The local output folder acts as a source archive and makes debugging easy.

## Future Deployment Shape

The preferred production setup is:

```text
Chrome Extension
  -> Railway FastAPI backend
  -> Supabase Database
  -> Supabase Storage
```

Railway should run the API and background processing jobs. Supabase should become the durable product library.

- Railway backend: receives scrape jobs, downloads/normalizes assets, runs AI processing, uploads files, and writes database records.
- Supabase Database: stores product/job/listing records, AI output, status, prompts, settings, and references to stored files.
- Supabase Storage: stores source images, generated images, edited versions, and export files.

In this plan, "object storage" simply means cloud file storage for images, zips, and other assets. Supabase Storage is object storage.

## Why Not URL-Only

Saving only the AliExpress item URL is not reliable enough for this workflow.

- AliExpress pages load data dynamically.
- Description images may only be discoverable through network interception.
- Product URLs and CDN image URLs can change, expire, block server requests, or return different content later.
- Future AI edits need stable reference images.
- Batch workflows require products to remain available after the original scrape session.

The extension should capture a product snapshot. The backend should archive the important source assets so future processing and tweaking can reuse the same material.

## What To Save Permanently

Save these in the database:

- source product URL
- scraped title, price, specs, and description text
- source image records with type, order, original URL, storage path, and hash
- extracted visual facts
- variation-specific specs
- AI listing output: title, description, tags, category, suggested price
- generation prompts and model/settings used
- image version history
- job status and processing errors

Save these in Supabase Storage:

- main product images
- variation images
- important description images, especially size charts/spec diagrams/material labels
- generated listing images
- edited/regenerated image versions
- final export files, such as listing packages or zips

Do not intentionally save these unless needed:

- duplicated images
- tiny UI icons
- review/customer photos
- shipping/payment badges
- unrelated recommendation images

## Suggested Storage Buckets

Use private buckets first. Public URLs can be added later only for assets that must be shared externally.

```text
source-assets/
  products/{product_id}/main/
  products/{product_id}/variation/
  products/{product_id}/description/

generated-assets/
  products/{product_id}/versions/

exports/
  products/{product_id}/

temp-assets/
  jobs/{job_id}/
```

`temp-assets` is optional. Railway can also use local temp files during processing, then delete them after upload.

## Processing Modes

Support multiple storage modes over time:

```env
STORAGE_MODE=local
SAVE_SOURCE_ASSETS=true
SOURCE_ASSET_RETENTION_DAYS=0
MAX_SOURCE_ASSETS_PER_PRODUCT=40
```

Recommended meanings:

- `STORAGE_MODE=local`: current development behavior using `OUTPUT_DIR`.
- `STORAGE_MODE=supabase`: archive product source assets and final outputs in Supabase.
- `SAVE_SOURCE_ASSETS=true`: keep raw/reference assets for future edits.
- `SOURCE_ASSET_RETENTION_DAYS=0`: keep source assets indefinitely.
- `MAX_SOURCE_ASSETS_PER_PRODUCT=40`: prevent accidental runaway storage.

## AI Image Tweaking Workflow

Future UI should treat each generated image as a versioned creative artifact.

Each generated or edited image should keep:

- source image/reference image used
- prompt used
- negative prompt or restrictions, if supported
- model/provider used
- strength/settings
- parent image version
- creation timestamp
- user notes or edit instruction

This allows a workflow like:

```text
Open product
  -> choose source/reference/generated image
  -> request tweak or regeneration
  -> save new version
  -> compare versions
  -> export chosen images
```

## Railway Notes

Railway is best treated as the API/worker runtime. Its service filesystem can be used for temporary processing, but durable files should live in Supabase Storage unless a Railway volume is intentionally added.

Useful official docs:

- Railway service storage and ephemeral filesystem: https://docs.railway.com/services
- Railway volumes for persistent service storage: https://docs.railway.com/volumes

## Supabase Notes

Supabase can provide both the database and the asset storage layer. Storage uses buckets, which are like cloud folders with access rules.

Useful official docs:

- Supabase Storage overview: https://supabase.com/docs/guides/storage
- Supabase bucket fundamentals: https://supabase.com/docs/guides/storage/buckets/fundamentals
- Supabase Storage pricing: https://supabase.com/docs/guides/storage/pricing

## Practical Next Step

Keep building locally with the current `OUTPUT_DIR` flow. When adding new features, design metadata so it can later map cleanly into Supabase records and Supabase Storage paths.

The first production-ready storage feature should be an abstraction around asset saving:

```text
save_product_asset(product_id, asset_type, source_url_or_file)
  -> local path in local mode
  -> Supabase storage path in deployed mode
```

That lets the app keep working locally while preparing for Railway and Supabase deployment.
