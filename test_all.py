import os
import json
import tempfile
import unittest
import yaml
from unittest.mock import MagicMock
from fastapi.testclient import TestClient
from src.ai_helper import (
    clean_tags,
    extract_variation_specs,
    finalize_listing_seo,
    reset_copywriting_profile_override,
    score_listing_seo,
    set_copywriting_profile_override,
    tweak_etsy_listing,
    write_etsy_listing,
)
from src.copywriting_config import normalize_copywriting_profile
from src.image_gen import generate_prompts_from_inspo

class TestEtsyAutomationLogic(unittest.TestCase):

    @unittest.mock.patch("src.ai_helper.get_openai_client", return_value=None)
    def test_tag_cleaning_and_limit(self, mock_get_openai):
        """Test that tags are cleaned, limited to 13, and tags > 20 characters are condensed."""
        # Create a mock Gemini client
        mock_client = MagicMock()
        mock_response = MagicMock()
        
        # When called to condense "super long vintage aesthetic keyword phrase", mock returning a shorter one
        mock_response.text = "vintage aesthetic"
        mock_client.models.generate_content.return_value = mock_response

        raw_tags = [
            "short tag", 
            "another short tag",
            "super long vintage aesthetic keyword phrase",  # > 20 characters
            "clean simple",
            "handmade items",
            "tag 1", "tag 2", "tag 3", "tag 4", "tag 5",
            "tag 6", "tag 7", "tag 8", "tag 9", "tag 10"  # To test truncation to 13 tags
        ]

        cleaned = clean_tags(raw_tags, mock_client)

        # Check length validation
        self.assertLessEqual(len(cleaned), 13)
        for tag in cleaned:
            self.assertLessEqual(len(tag), 20)
            
        # Verify the mock client was called to condense the long tag
        mock_client.models.generate_content.assert_called_once()
        self.assertIn("vintage aesthetic", cleaned)


    def test_policy_footer_injection(self):
        """Test that cancellation and return policies are automatically appended."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        
        # Mock structured response
        mock_response.text = '{"title": "Test Title", "description": "Test description of product", "tags": ["tag1", "tag2"], "suggested_price": "$15.99"}'
        mock_client.models.generate_content.return_value = mock_response

        # Mock clean_tags to just return the tags
        mock_client.models.generate_content.return_value = mock_response
        
        result = write_etsy_listing("Test Title", "Test description", "$15.99", mock_client)
        
        self.assertIsNotNone(result)
        self.assertIn("Cancellation Policy: Cancellation is allowed within 5 hours", result["description"])
        self.assertIn("Returns & Refunds Policy: Returns and refunds are accepted", result["description"])

    def test_inspo_prompt_generation(self):
        """Test that style prompts are generated correctly based on inspo visual description."""
        inspo_style = "warm moody lighting with deep shadows, a rustic wooden table top, scattered oak leaves"
        prompts = generate_prompts_from_inspo(inspo_style, "banana_earrings")
        
        self.assertEqual(len(prompts), 3)
        self.assertEqual(prompts[0]["name"], "1_showcase")
        self.assertIn("banana_earrings", prompts[0]["prompt"])
        self.assertIn(inspo_style, prompts[0]["prompt"])

    @unittest.mock.patch("src.ai_helper.get_openai_client", return_value=None)
    def test_enriched_copywriting_and_self_review(self, mock_get_openai):
        """Test that write_etsy_listing properly formats prompts with image facts and reviews them."""
        mock_client = MagicMock()
        mock_response_strategy = MagicMock()
        mock_response_listing = MagicMock()
        mock_response_review = MagicMock()

        # Phase 1 mock SEO strategy
        mock_response_strategy.text = '{"primary_product_noun": "test product", "top_traits": ["woven yarn"], "buyer_intents": ["everyday use"], "audience": [], "primary_keywords": ["test product", "woven yarn product"], "long_tail_keywords": ["woven yarn test product"], "tag_keywords": ["test product", "woven yarn", "everyday use"]}'
        # Phase 2 mock draft listing
        mock_response_listing.text = '{"title": "Test Title", "description": "Test description of product", "tags": ["tag1", "tag2"], "suggested_price": "$15.99"}'
        # Phase 3 mock review verdict (approved)
        mock_response_review.text = '{"approved": true, "title_issues": "", "description_issues": "", "tag_issues": ""}'

        # Return sequence for SEO strategy, draft listing, and self-review critic
        mock_client.models.generate_content.side_effect = [mock_response_strategy, mock_response_listing, mock_response_review]

        image_facts = {
            "dimensions": "Height: 38cm, Width: 28cm",
            "materials": "100% Woven Yarn"
        }

        result = write_etsy_listing(
            title="Test Title",
            description="Scraped description",
            price="$15.99",
            client=mock_client,
            presets={"custom_prompt_rules": "Keep the tone warm but avoid unsupported concrete claims."},
            image_facts=image_facts
        )

        self.assertIsNotNone(result)
        self.assertIn("Test Product", result["title"])
        self.assertNotEqual(result["title"], "Test Title")
        self.assertEqual(result["suggested_price"], "$15.99")
        self.assertEqual(len(result["tags"]), 13)
        self.assertNotEqual(result["category"], "Not categorized")
        self.assertNotIn("google_meta_title", result)
        self.assertNotIn("google_meta_description", result)
        self.assertNotIn("pinterest_title", result)
        self.assertNotIn("pinterest_description", result)
        self.assertIn("seo_quality_score", result)
        # Ensure client was called for SEO strategy, draft, and self-review critic
        self.assertEqual(mock_client.models.generate_content.call_count, 3)
        listing_prompt = mock_client.models.generate_content.call_args_list[1].kwargs["contents"]
        self.assertIn("SHOP OWNER COPYWRITING RULES (high priority)", listing_prompt)
        self.assertIn("WORKSPACE MASTER RULES:", listing_prompt)
        self.assertIn("LISTING DRAFT INSTRUCTIONS:", listing_prompt)
        self.assertIn("ACTIVE EDITORIAL AND COMPATIBILITY POLICIES:", listing_prompt)
        self.assertIn("Strict Factual Accuracy [SAFE DEFAULT]", listing_prompt)

    def test_risk_overrides_preserve_long_titles_and_tags_with_compatibility_warnings(self):
        profile = normalize_copywriting_profile({
            "risk_controls": {
                "title_style": {"override_enabled": True},
                "etsy_title_limit": {"override_enabled": True, "value": 220},
                "etsy_tag_count": {"override_enabled": True, "value": 4},
                "etsy_tag_length": {"override_enabled": True, "value": 40},
            }
        })
        token = set_copywriting_profile_override(profile)
        try:
            listing = {
                "title": "Luxury Statement Product " * 8,
                "description": "A dramatic and highly promotional description.",
                "tags": ["very long discovery keyword", "second expressive keyword", "third keyword", "fourth keyword"],
                "suggested_price": "$80.00",
                "category": "Accessories",
            }
            result = finalize_listing_seo(
                listing,
                {"primary_product_noun": "statement product", "tag_keywords": listing["tags"]},
                MagicMock(),
            )
        finally:
            reset_copywriting_profile_override(token)

        self.assertGreater(len(result["title"]), 140)
        self.assertEqual(len(result["tags"]), 4)
        self.assertFalse(result["etsy_compatible"])
        self.assertTrue(any("Title is" in issue for issue in result["etsy_compatibility_issues"]))
        self.assertTrue(any("tag(s) exceed" in issue for issue in result["etsy_compatibility_issues"]))

    @unittest.mock.patch("src.ai_helper.get_openai_client", return_value=None)
    def test_keyword_stuffed_title_is_rebuilt_for_etsy_readability(self, mock_get_openai):
        """Test that a tag-list style title is converted into one readable Etsy title."""
        mock_client = MagicMock()
        mock_response_strategy = MagicMock()
        mock_response_listing = MagicMock()
        mock_response_review = MagicMock()

        mock_response_strategy.text = json.dumps({
            "primary_product_noun": "crochet tote bag",
            "top_traits": ["white openwork knit", "shoulder bag"],
            "buyer_intents": ["summer beach", "market bag"],
            "audience": ["women"],
            "primary_keywords": ["crochet tote bag", "white tote bag", "knit shoulder bag"],
            "long_tail_keywords": ["white crochet tote bag", "summer beach bag"],
            "tag_keywords": [
                "crochet tote", "white tote", "knit bag", "shoulder bag", "beach bag",
                "market bag", "summer tote", "openwork bag", "women bag", "boho tote",
                "casual bag", "travel tote", "gift for her"
            ]
        })
        mock_response_listing.text = json.dumps({
            "title": "Crochet Tote Bag White Bag Women Bag Summer Bag Beach Bag Market Bag Openwork Knit Shoulder Bag",
            "description": "A white openwork crochet tote bag for everyday summer styling.",
            "tags": [
                "crochet tote", "white tote", "knit bag", "shoulder bag", "beach bag",
                "market bag", "summer tote", "openwork bag", "women bag", "boho tote",
                "casual bag", "travel tote", "gift for her"
            ],
            "suggested_price": "$32.00",
            "category": "Bags & Purses"
        })
        mock_response_review.text = '{"approved": true, "title_issues": "", "description_issues": "", "tag_issues": ""}'
        mock_client.models.generate_content.side_effect = [mock_response_strategy, mock_response_listing, mock_response_review]

        result = write_etsy_listing(
            title="Crochet Tote Bag White Bag Women Bag Summer Bag Beach Bag Market Bag",
            description="A white openwork crochet tote bag for summer, beach, and market use.",
            price="$32.00",
            client=mock_client,
            presets={}
        )

        self.assertIsNotNone(result)
        self.assertLessEqual(len(result["title"].split()), 18)
        self.assertLessEqual(result["title"].count(",") + result["title"].count(":") + 1, 3)
        self.assertNotIn("google_meta_title", result)
        self.assertNotIn("pinterest_title", result)
        self.assertNotIn("White Bag Women Bag Summer Bag", result["title"])

    def test_final_listing_qa_prefers_clean_strategy_title_over_chopped_keyword_fragments(self):
        listing = {
            "title": "Ng Room Furniture Sofa Si Nordic Coffee, Nordic Coffee Tables Livi, De Table Acrylic Double-d",
            "description": "A clear acrylic side table with a double-deck storage shelf for living room or bedside use.",
            "tags": ["side table", "acrylic table", "accent table"],
            "suggested_price": "$89.99",
            "category": "Home & Living > Furniture",
        }
        strategy = {
            "title": "Modern Acrylic Side Table with Storage Shelf 16 Inch Cube Accent Table",
            "primary_product_noun": "nordic coffee",
            "top_traits": [
                "Nordic Coffee Tables Livi",
                "ng Room Furniture Sofa Si",
                "de Table Acrylic Double-d",
                "eck Storage Tea Tables Tr",
            ],
            "buyer_intents": ["living room furniture"],
            "primary_keywords": ["nordic coffee", "Nordic Coffee Tables Livi", "de Table Acrylic Double-d"],
            "long_tail_keywords": ["Modern Acrylic Side Table", "with Storage Shelf in Cle"],
            "tag_keywords": ["side table", "acrylic table", "accent table"],
        }

        result = finalize_listing_seo(listing, strategy, MagicMock())

        self.assertEqual(result["title"], "Modern Acrylic Side Table with Storage Shelf Cube Accent Table")
        for fragment in ["Ng Room", "Livi", "Double-d", "16 Inch"]:
            self.assertNotIn(fragment, result["title"])

    def test_final_listing_qa_removes_exact_measurements_from_titles(self):
        listing = {
            "title": "Modern Round Side Table with Terrazzo Base and Metal Top in Red or Black, 21 Inches High",
            "description": "A modern round side table with a terrazzo-style base and metal top.",
            "tags": ["round side table", "accent table", "metal table"],
            "suggested_price": "$74.99",
            "category": "Home & Living > Furniture",
        }
        strategy = {
            "title": listing["title"],
            "primary_product_noun": "side table",
            "top_traits": ["modern round", "terrazzo base", "metal top"],
            "buyer_intents": ["living room"],
            "primary_keywords": ["side table", "round side table"],
            "long_tail_keywords": ["modern round side table"],
            "tag_keywords": ["round side table", "accent table", "metal table"],
        }

        result = finalize_listing_seo(listing, strategy, MagicMock())

        self.assertEqual(result["title"], "Modern Round Side Table with Terrazzo Base and Metal Top in Red or Black")
        self.assertNotIn("21 Inches", result["title"])

    def test_final_listing_qa_cleans_variation_title_category_and_price(self):
        """Test deterministic final QA catches weak listing fields without another model call."""
        mock_client = MagicMock()
        listing = {
            "title": "Color: Army Green Knitted Handbag, Color: Brown, Color: Light Yellow",
            "description": "A soft knitted handbag for everyday carry.",
            "tags": [
                "knitted handbag", "cat purse", "wool bag", "soft tote", "daily carry",
                "cute handbag", "small purse", "portable tote", "woven bag", "casual purse",
                "gift bag", "colorful bag", "everyday tote"
            ],
            "suggested_price": "0",
            "category": "Handbags",
        }
        strategy = {
            "primary_product_noun": "knitted handbag",
            "top_traits": ["soft woven texture", "cat design"],
            "buyer_intents": ["everyday carry"],
            "primary_keywords": ["knitted handbag", "cat purse"],
            "long_tail_keywords": ["soft knitted handbag", "cute cat purse"],
            "tag_keywords": listing["tags"],
        }

        result = finalize_listing_seo(
            listing,
            strategy,
            mock_client,
            source_price="$12.00",
            source_context="knitted handbag cat design wool texture",
        )

        self.assertNotIn("Color:", result["title"])
        self.assertGreaterEqual(len(result["title"]), 50)
        self.assertEqual(result["category"], "Bags & Purses > Handbags")
        self.assertEqual(result["suggested_price"], "$21.60")
        self.assertNotIn("raw variation labels", " ".join(result["seo_qa_notes"]).lower())

    def test_final_listing_qa_does_not_leak_dict_traits_into_title(self):
        """Test AI dict-shaped strategy values are normalized before title composition."""
        mock_client = MagicMock()
        listing = {
            "title": "{'trait': 'color', 'value': 'red'} Handbag, {'trait': 'material', 'value': 'polyester'}",
            "description": "A compact luxury designer red knitted handbag perfect for daily carry without the bulk.",
            "tags": [
                "red handbag", "knitted bag", "daily carry", "polyester bag", "small handbag",
                "portable tote", "cute purse", "casual bag", "fashion purse", "commute bag",
                "red tote", "luxury bag", "everyday bag"
            ],
            "suggested_price": "$18.00",
            "category": "Handbags",
        }
        strategy = {
            "primary_product_noun": "handbag",
            "top_traits": [
                {"trait": "color", "value": "red"},
                {"trait": "material", "value": "polyester"},
                {"trait": "style", "value": "knitted"},
            ],
            "buyer_intents": ["daily carry"],
            "primary_keywords": ["red handbag", "knitted handbag"],
            "long_tail_keywords": ["compact red handbag"],
            "tag_keywords": listing["tags"],
        }

        result = finalize_listing_seo(listing, strategy, mock_client, source_price="$10.00")

        self.assertNotIn("{", result["title"])
        self.assertNotIn("trait", result["title"].lower())
        self.assertNotIn("value", result["title"].lower())
        self.assertNotIn("luxury", result["description"].lower())
        self.assertNotIn("designer", result["description"].lower())
        self.assertIn("suited for daily carry", result["description"].lower())
        self.assertNotIn("luxury bag", result["tags"])
        self.assertIn("Red", result["title"])
        self.assertEqual(result["category"], "Bags & Purses > Handbags")

    def test_final_listing_qa_returns_exact_repair_instructions(self):
        """Test deterministic QA gives actionable repair instructions, not only vague review notes."""
        mock_client = MagicMock()
        listing = {
            "title": "Brown Shoulder Bag",
            "description": "This brown shoulder bag is for everyday styling.",
            "tags": ["shoulder bag", "brown bag"],
            "suggested_price": "0",
            "category": "Bags & Purses > Wallets & Money Clips",
        }
        strategy = {
            "primary_product_noun": "shoulder bag",
            "top_traits": ["brown"],
            "buyer_intents": ["everyday styling"],
            "primary_keywords": ["brown shoulder bag"],
            "long_tail_keywords": ["brown shoulder bag for everyday styling"],
            "tag_keywords": ["shoulder bag", "brown bag", "everyday bag"],
        }

        result = finalize_listing_seo(
            listing,
            strategy,
            mock_client,
            source_price="$12.00",
            source_context="brown shoulder bag",
        )
        repairs = " ".join(result["repair_instructions"])

        self.assertEqual(result["category"], "Bags & Purses > Handbags")
        self.assertTrue(result["needs_review"])
        self.assertIn("Rewrite the title", repairs)
        self.assertIn("Product Details", repairs)
        self.assertIn("suited for everyday styling", result["description"].lower())

    def test_description_formatter_restores_line_breaks_and_removes_markdown(self):
        """Test final QA keeps Etsy descriptions scannable instead of one dense Markdown blob."""
        mock_client = MagicMock()
        listing = {
            "title": "Red Canvas Tote Bag with Adjustable Shoulder Strap for Everyday Carry",
            "description": (
                "Carry your essentials with this red canvas tote bag. **Product Details:** "
                "* **Materials:** Canvas * **Colors:** Red * **Features:** Adjustable shoulder strap "
                "*Please refer to the photos for exact color and proportions.*"
            ),
            "tags": [
                "canvas tote", "red tote bag", "shoulder bag", "daily carry", "casual tote",
                "canvas purse", "adjustable bag", "commute bag", "everyday tote", "red handbag",
                "fabric tote", "travel tote", "market bag"
            ],
            "suggested_price": "$24.00",
            "category": "Bags & Purses > Handbags",
        }
        strategy = {
            "primary_product_noun": "canvas tote bag",
            "top_traits": ["red", "canvas", "adjustable shoulder strap"],
            "buyer_intents": ["everyday carry"],
            "primary_keywords": ["red canvas tote bag"],
            "long_tail_keywords": ["red canvas tote bag with shoulder strap"],
            "tag_keywords": listing["tags"],
        }

        result = finalize_listing_seo(listing, strategy, mock_client, source_context="red canvas tote bag adjustable shoulder strap")
        description = result["description"]

        self.assertIn("\n\nPRODUCT DETAILS:\n", description)
        self.assertIn("\n- Materials: Canvas", description)
        self.assertIn("\n- Colors: Red", description)
        self.assertIn("\n\nNOTE:\nPlease refer to the photos", description)
        self.assertNotIn("**", description)
        self.assertNotIn("*", description)

    @unittest.mock.patch("src.ai_helper.get_openai_client", return_value=None)
    def test_tweak_listing_updates_selected_fields_only_and_formats_description(self, mock_get_openai):
        """Test lightweight copy tweaks preserve untouched fields and clean Etsy-safe formatting."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = json.dumps({
            "title": "AI Tried To Change This Title",
            "category": "AI Tried Category",
            "suggested_price": "$99.00",
            "tags": ["changed tag"],
            "description": (
                "Carry your essentials with this red canvas tote bag. **Product Details:** "
                "* Materials: Canvas * Colors: Red * Features: Adjustable strap"
            ),
            "seo_strategy": {
                "primary_product_noun": "tote bag",
                "top_traits": ["red", "canvas"],
                "buyer_intents": ["everyday carry"],
                "audience": [],
                "primary_keywords": ["red tote bag"],
                "long_tail_keywords": ["red canvas tote"],
                "tag_keywords": ["red tote", "canvas tote", "daily bag", "shoulder bag", "casual tote", "red bag", "fabric tote", "market tote", "travel tote", "simple tote", "commute bag", "gift bag", "carry bag"]
            }
        })
        mock_client.models.generate_content.return_value = mock_response
        existing = {
            "title": "Original Red Canvas Tote Bag",
            "category": "Bags & Purses > Handbags",
            "suggested_price": "$24.00",
            "tags": [
                "red tote", "canvas tote", "daily bag", "shoulder bag", "casual tote",
                "red bag", "fabric tote", "market tote", "travel tote", "simple tote",
                "commute bag", "gift bag", "carry bag"
            ],
            "description": "Original description.",
        }

        result = tweak_etsy_listing(
            existing,
            preset_key="safer_description",
            instruction="Make the description safer.",
            fields=["description"],
            source_context="red canvas tote bag with adjustable strap",
            image_facts={},
            variation_specs=[],
            price="$24.00",
            presets={"custom_prompt_rules": "Keep confirmed facts only."},
            client=mock_client,
        )

        self.assertEqual(result["title"], existing["title"])
        self.assertEqual(result["category"], existing["category"])
        self.assertEqual(result["suggested_price"], existing["suggested_price"])
        self.assertEqual(result["tags"], existing["tags"])
        self.assertIn("\n\nPRODUCT DETAILS:\n", result["description"])
        self.assertIn("\n- Materials: Canvas", result["description"])
        self.assertNotIn("**", result["description"])
        first_prompt = mock_client.models.generate_content.call_args_list[0].kwargs["contents"]
        self.assertIn("Selected Fields: description", first_prompt)
        self.assertIn("SHOP OWNER COPYWRITING RULES", first_prompt)
        self.assertIn("Do not scan or request images", first_prompt)

    def test_seo_score_does_not_flag_normal_bulk_wording_as_supplier_language(self):
        listing = {
            "title": "Canvas Tote Handbag with Zipper Closure for Daily Carry",
            "description": "A compact canvas handbag for daily carry without the bulk.",
            "tags": [
                "canvas tote", "zipper bag", "daily carry", "compact handbag", "purple bag",
                "floral purse", "casual bag", "commute purse", "canvas purse", "small tote",
                "everyday bag", "fabric handbag", "outing bag"
            ],
            "category": "Bags & Purses > Handbags",
            "suggested_price": "$24.99",
        }

        _, notes = score_listing_seo(listing)

        self.assertNotIn("Listing contains prohibited supplier/platform language.", notes)

    @unittest.mock.patch("src.ai_helper.get_openai_client", return_value=None)
    def test_variation_spec_extraction(self, mock_get_openai):
        """Test that extract_variation_specs constructs the prompt, handles images, and returns structured specs."""
        import json
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = json.dumps({
            "variations": [
                {
                    "name": "Red - S",
                    "size": "S",
                    "dimensions": "Height: 38cm, Width: 28cm",
                    "other_details": ""
                },
                {
                    "name": "Red - M",
                    "size": "M",
                    "dimensions": "Height: 40cm, Width: 30cm",
                    "other_details": ""
                }
            ]
        })
        mock_client.models.generate_content.return_value = mock_response

        variations_input = [
            {"local_path": "variation_images/var_1.jpg", "alt": "Red - S", "title": ""},
            {"local_path": "variation_images/var_2.jpg", "alt": "Red - M", "title": ""}
        ]

        result = extract_variation_specs(
            variations=variations_input,
            product_dir="dummy_dir",
            overall_specs={"dimensions": "S: 38x28cm, M: 40x30cm"},
            scraped_desc="Product description",
            client=mock_client
        )

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["size"], "S")
        self.assertEqual(result[1]["dimensions"], "Height: 40cm, Width: 30cm")
        mock_client.models.generate_content.assert_called_once()

class TestHostedWorkspaceIsolation(unittest.TestCase):

    def setUp(self):
        from src import server

        self.server = server
        self.temp_dir = tempfile.TemporaryDirectory()
        self.env_path = os.path.join(self.temp_dir.name, ".env")
        self.env_patch = unittest.mock.patch.object(server, "env_path", self.env_path)
        self.env_patch.start()

        self.old_output_dir = os.environ.get("OUTPUT_DIR")
        self.old_hosted_mode = os.environ.get("HOSTED_MODE")
        os.environ["OUTPUT_DIR"] = self.temp_dir.name
        os.environ.pop("HOSTED_MODE", None)

        self.client = TestClient(server.app)

    def tearDown(self):
        if self.old_output_dir is None:
            os.environ.pop("OUTPUT_DIR", None)
        else:
            os.environ["OUTPUT_DIR"] = self.old_output_dir

        if self.old_hosted_mode is None:
            os.environ.pop("HOSTED_MODE", None)
        else:
            os.environ["HOSTED_MODE"] = self.old_hosted_mode

        self.env_patch.stop()
        self.temp_dir.cleanup()

    def write_product(self, token, slug, title, status="queued", etsy_listing=None, generated_images=None):
        product_dir = os.path.join(self.server.get_output_dir(token), slug)
        image_dir = os.path.join(product_dir, "main_images")
        os.makedirs(image_dir, exist_ok=True)
        with open(os.path.join(image_dir, "main_1.jpg"), "wb") as f:
            f.write(b"fake image bytes")
        metadata = {
            "title": title,
            "price": "$10",
            "specs": {},
            "description_text": "",
            "main_images": ["main_images/main_1.jpg"],
            "variation_images": [],
            "description_images": [],
            "status": status,
        }
        if etsy_listing is not None:
            metadata["etsy_listing"] = etsy_listing
        if generated_images is not None:
            metadata["generated_images"] = generated_images
            for entry in generated_images:
                local_path = entry.get("local_path") if isinstance(entry, dict) else entry
                if not local_path:
                    continue
                generated_path = os.path.join(product_dir, local_path)
                os.makedirs(os.path.dirname(generated_path), exist_ok=True)
                with open(generated_path, "wb") as f:
                    f.write(b"fake generated image bytes")
        with open(os.path.join(product_dir, "metadata.json"), "w", encoding="utf-8") as f:
            json.dump(metadata, f)

    def sample_listing(self, title="Original Tote Bag"):
        return {
            "title": title,
            "category": "Bags & Purses > Handbags",
            "suggested_price": "$24.00",
            "description": "Original listing description.\n\nPRODUCT DETAILS:\n- Color: Red",
            "tags": [
                "red tote", "canvas tote", "daily bag", "shoulder bag", "casual tote",
                "red bag", "fabric tote", "market tote", "travel tote", "simple tote",
                "commute bag", "gift bag", "carry bag"
            ],
        }

    def test_missing_token_uses_default_workspace(self):
        self.write_product("default", "default-product", "Default Product")

        response = self.client.get("/api/queue")

        self.assertEqual(response.status_code, 200)
        queue = response.json()["queue"]
        self.assertEqual(len(queue), 1)
        self.assertEqual(queue[0]["slug"], "default-product")

    def test_user_token_is_sanitized_and_limited(self):
        token = self.server.sanitize_user_token("../tyrone abc123!!" + ("x" * 80))

        self.assertTrue(token.startswith("tyroneabc123"))
        self.assertLessEqual(len(token), 64)
        self.assertNotIn(".", token)
        self.assertNotIn("/", token)

    def test_workspace_queue_and_images_are_isolated(self):
        self.write_product("user-a", "bag-a", "Bag A")
        self.write_product("user-b", "bag-b", "Bag B")

        response_a = self.client.get("/api/queue", headers={"X-User-Token": "user-a"})
        response_b = self.client.get("/api/queue", headers={"X-User-Token": "user-b"})

        self.assertEqual([item["slug"] for item in response_a.json()["queue"]], ["bag-a"])
        self.assertEqual([item["slug"] for item in response_b.json()["queue"]], ["bag-b"])

        image_a = self.client.get("/api/product-image/bag-a/main_images/main_1.jpg?token=user-a")
        image_b = self.client.get("/api/product-image/bag-a/main_images/main_1.jpg?token=user-b")

        self.assertEqual(image_a.status_code, 200)
        self.assertEqual(image_b.status_code, 404)

    def test_queue_product_stores_clean_source_url(self):
        response = self.client.post(
            "/api/queue-product",
            headers={"X-User-Token": "source-user"},
            json={
                "title": "Source Bag",
                "price": "$12.00",
                "specs": {},
                "description_text": "",
                "source_url": "https://www.aliexpress.com/item/1234567890.html?spm=tracking&gatewayAdapt=abc#nav-review",
                "source_product_id": "",
                "source_domain": "www.aliexpress.com",
                "main_images": [],
                "variation_images": [],
                "description_images": [],
            },
        )

        self.assertEqual(response.status_code, 200)
        meta_path = os.path.join(
            self.server.get_output_dir("source-user"),
            self.server.sanitize_filename("Source Bag"),
            "metadata.json",
        )
        with open(meta_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)

        self.assertEqual(metadata["source_url"], "https://www.aliexpress.com/item/1234567890.html")
        self.assertEqual(metadata["source_product_id"], "1234567890")
        self.assertEqual(metadata["source_domain"], "www.aliexpress.com")

    def test_tweak_listing_missing_product_returns_404(self):
        response = self.client.post(
            "/api/tweak-listing",
            headers={"X-User-Token": "missing-user"},
            json={
                "output_dir_name": "missing-product",
                "preset_key": "fix_title",
                "fields": ["title"],
            },
        )

        self.assertEqual(response.status_code, 404)

    def test_tweak_listing_requires_existing_listing(self):
        self.write_product("tweak-user", "queued-product", "Queued Product")

        response = self.client.post(
            "/api/tweak-listing",
            headers={"X-User-Token": "tweak-user"},
            json={
                "output_dir_name": "queued-product",
                "preset_key": "fix_title",
                "fields": ["title"],
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("no generated Etsy listing", response.json()["detail"])

    def test_tweak_listing_returns_preview_without_saving_metadata(self):
        original_listing = self.sample_listing()
        tweaked_listing = {**original_listing, "title": "Improved Red Canvas Tote Bag"}
        self.write_product("tweak-user", "done-product", "Done Product", status="done", etsy_listing=original_listing)

        with unittest.mock.patch("src.server.tweak_etsy_listing", return_value=tweaked_listing) as mock_tweak:
            response = self.client.post(
                "/api/tweak-listing",
                headers={"X-User-Token": "tweak-user"},
                json={
                    "output_dir_name": "done-product",
                    "preset_key": "fix_title",
                    "fields": ["title"],
                    "context_mode": "existing_output",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["listing"]["title"], "Improved Red Canvas Tote Bag")
        self.assertEqual(mock_tweak.call_args.kwargs["fields"], ["title"])

        meta_path = os.path.join(self.server.get_output_dir("tweak-user"), "done-product", "metadata.json")
        with open(meta_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)
        self.assertEqual(metadata["etsy_listing"]["title"], original_listing["title"])

    def test_tweak_listing_does_not_scan_images_by_default_and_is_token_scoped(self):
        listing = self.sample_listing()
        self.write_product("user-a", "bag-a", "Bag A", status="done", etsy_listing=listing)

        with unittest.mock.patch("src.server.extract_visual_specs") as mock_scan, \
             unittest.mock.patch("src.server.tweak_etsy_listing", return_value={**listing, "category": "Bags & Purses > Totes"}):
            response_a = self.client.post(
                "/api/tweak-listing",
                headers={"X-User-Token": "user-a"},
                json={
                    "output_dir_name": "bag-a",
                    "preset_key": "fix_category",
                    "fields": ["category"],
                },
            )
            response_b = self.client.post(
                "/api/tweak-listing",
                headers={"X-User-Token": "user-b"},
                json={
                    "output_dir_name": "bag-a",
                    "preset_key": "fix_category",
                    "fields": ["category"],
                },
            )

        self.assertEqual(response_a.status_code, 200)
        self.assertEqual(response_b.status_code, 404)
        mock_scan.assert_not_called()

    def test_save_listing_persists_category(self):
        listing = self.sample_listing()
        self.write_product("save-user", "save-product", "Save Product", status="done", etsy_listing=listing)

        response = self.client.post(
            "/api/save-listing",
            headers={"X-User-Token": "save-user"},
            json={
                "output_dir_name": "save-product",
                "title": listing["title"],
                "category": "Bags & Purses > Totes",
                "suggested_price": listing["suggested_price"],
                "description": listing["description"],
                "tags": listing["tags"],
            },
        )

        self.assertEqual(response.status_code, 200)
        meta_path = os.path.join(self.server.get_output_dir("save-user"), "save-product", "metadata.json")
        with open(meta_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)
        self.assertEqual(metadata["etsy_listing"]["category"], "Bags & Purses > Totes")

    @unittest.mock.patch("src.server.generate_image_prompt_details", return_value="red woven bag variation")
    @unittest.mock.patch("src.server.generate_image_with_imagen")
    def test_batch_image_generation_processes_each_variation_source(self, mock_generate_image, mock_prompt_details):
        from src import server

        with tempfile.TemporaryDirectory() as product_dir:
            var_dir = os.path.join(product_dir, "variation_images")
            os.makedirs(var_dir, exist_ok=True)
            var_1 = os.path.join(var_dir, "var_1.jpg")
            var_2 = os.path.join(var_dir, "var_2.jpg")
            with open(var_1, "wb") as f:
                f.write(b"variation one")
            with open(var_2, "wb") as f:
                f.write(b"variation two")

            def fake_generate(*, output_path, **kwargs):
                with open(output_path, "wb") as f:
                    f.write(b"generated")
                return output_path

            mock_generate_image.side_effect = fake_generate
            metadata = {
                "title": "Red woven bag",
                "variation_images": [
                    {"local_path": "variation_images/var_1.jpg", "alt": "Red"},
                    {"local_path": "variation_images/var_2.jpg", "alt": "Blue"},
                ],
            }

            generated = server.run_image_generation_tasks(
                metadata=metadata,
                product_dir=product_dir,
                image_tasks=[
                    {
                        "task_type": "batch",
                        "target": "variation_images",
                        "prompt_mode": "preset",
                        "prompt_preset": "auto_product_staging",
                    }
                ],
                image_settings={"model_key": "flux-kontext-pro"},
                client=MagicMock(),
            )

            reference_paths = [
                os.path.relpath(call.kwargs["reference_image"], product_dir).replace("\\", "/")
                for call in mock_generate_image.call_args_list
            ]

            self.assertEqual(reference_paths, ["variation_images/var_1.jpg", "variation_images/var_2.jpg"])
            self.assertEqual([item["source_image"] for item in generated], ["variation_images/var_1.jpg", "variation_images/var_2.jpg"])
            self.assertEqual([item["local_path"] for item in generated], [item["local_path"] for item in metadata["generated_images"]])
            self.assertEqual(len({item["local_path"] for item in generated}), 2)

    def test_tweak_generated_image_missing_product_returns_404(self):
        response = self.client.post(
            "/api/tweak-generated-image",
            headers={"X-User-Token": "image-user"},
            json={
                "product_slug": "missing-product",
                "generated_image": "generated_1.png",
            },
        )

        self.assertEqual(response.status_code, 404)

    def test_tweak_generated_image_requires_metadata_entry_and_blocks_traversal(self):
        self.write_product(
            "image-user",
            "image-product",
            "Image Product",
            status="done",
            generated_images=[{"local_path": "generated_1.png"}],
        )

        missing_response = self.client.post(
            "/api/tweak-generated-image",
            headers={"X-User-Token": "image-user"},
            json={
                "product_slug": "image-product",
                "generated_image": "not-in-metadata.png",
            },
        )
        traversal_response = self.client.post(
            "/api/tweak-generated-image",
            headers={"X-User-Token": "image-user"},
            json={
                "product_slug": "image-product",
                "generated_image": "../metadata.json",
            },
        )

        self.assertEqual(missing_response.status_code, 404)
        self.assertIn(traversal_response.status_code, (400, 404))

    @unittest.mock.patch("src.server.get_genai_client", return_value=MagicMock())
    @unittest.mock.patch("src.server.generate_image_prompt_details", return_value="clean generated tote image")
    @unittest.mock.patch("src.server.generate_image_with_imagen")
    def test_tweak_generated_image_appends_new_entry_without_replacing(self, mock_generate_image, mock_prompt_details, mock_client):
        original_generated = [{
            "local_path": "generated_1.png",
            "source_label": "Variation Red",
            "model_key": "flux-kontext-pro",
        }]
        self.write_product(
            "image-user",
            "image-product",
            "Image Product",
            status="done",
            generated_images=original_generated,
        )

        def fake_generate(*, output_path, **kwargs):
            with open(output_path, "wb") as f:
                f.write(b"tweaked generated image bytes")
            return output_path

        mock_generate_image.side_effect = fake_generate

        response = self.client.post(
            "/api/tweak-generated-image",
            headers={"X-User-Token": "image-user"},
            json={
                "product_slug": "image-product",
                "generated_image": "generated_1.png",
                "prompt_mode": "preset",
                "prompt_preset": "clean_catalog",
                "model_key": "flux-kontext-pro",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["generated_images"]), 2)
        new_entry = payload["generated_image"]
        self.assertTrue(new_entry["is_tweak"])
        self.assertEqual(new_entry["parent_image"], "generated_1.png")
        self.assertEqual(new_entry["prompt_preset"], "clean_catalog")
        self.assertTrue(new_entry["local_path"].startswith("tweak_"))

        meta_path = os.path.join(self.server.get_output_dir("image-user"), "image-product", "metadata.json")
        with open(meta_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)
        self.assertEqual(metadata["generated_images"][0]["local_path"], "generated_1.png")
        self.assertEqual(len(metadata["generated_images"]), 2)

    @unittest.mock.patch("src.server.get_genai_client", return_value=MagicMock())
    @unittest.mock.patch("src.server.generate_image_prompt_details", return_value="clean generated tote image")
    @unittest.mock.patch("src.server.generate_image_with_imagen")
    def test_tweak_generated_image_uses_multi_reference_only_for_supported_model(self, mock_generate_image, mock_prompt_details, mock_client):
        self.write_product(
            "image-user",
            "image-product",
            "Image Product",
            status="done",
            generated_images=[{"local_path": "generated_1.png"}],
        )

        def fake_generate(*, output_path, **kwargs):
            with open(output_path, "wb") as f:
                f.write(b"tweaked generated image bytes")
            return output_path

        mock_generate_image.side_effect = fake_generate

        flux_response = self.client.post(
            "/api/tweak-generated-image",
            headers={"X-User-Token": "image-user"},
            json={
                "product_slug": "image-product",
                "generated_image": "generated_1.png",
                "reference_image": "main_images/main_1.jpg",
                "model_key": "flux-kontext-pro",
            },
        )
        nano_response = self.client.post(
            "/api/tweak-generated-image",
            headers={"X-User-Token": "image-user"},
            json={
                "product_slug": "image-product",
                "generated_image": "generated_1.png",
                "reference_image": "main_images/main_1.jpg",
                "model_key": "nano-banana-2-edit",
                "thinking_level": "minimal",
            },
        )

        self.assertEqual(flux_response.status_code, 200)
        self.assertTrue(flux_response.json()["reference_image_ignored"])
        self.assertEqual(len(mock_generate_image.call_args_list[0].kwargs["reference_images"]), 1)

        self.assertEqual(nano_response.status_code, 200)
        self.assertFalse(nano_response.json()["reference_image_ignored"])
        self.assertEqual(len(mock_generate_image.call_args_list[1].kwargs["reference_images"]), 2)
        self.assertEqual(mock_generate_image.call_args_list[1].kwargs["fal_model_key"], "nano-banana-2-edit")
        self.assertEqual(mock_generate_image.call_args_list[1].kwargs["fal_thinking_level"], "minimal")

    def test_tweak_generated_image_is_token_scoped_and_validates_optional_reference(self):
        self.write_product(
            "user-a",
            "image-product",
            "Image Product",
            status="done",
            generated_images=[{"local_path": "generated_1.png"}],
        )

        token_b_response = self.client.post(
            "/api/tweak-generated-image",
            headers={"X-User-Token": "user-b"},
            json={
                "product_slug": "image-product",
                "generated_image": "generated_1.png",
            },
        )
        invalid_reference_response = self.client.post(
            "/api/tweak-generated-image",
            headers={"X-User-Token": "user-a"},
            json={
                "product_slug": "image-product",
                "generated_image": "generated_1.png",
                "reference_image": "generated_1.png",
            },
        )

        self.assertEqual(token_b_response.status_code, 404)
        self.assertEqual(invalid_reference_response.status_code, 400)

    def test_product_image_path_traversal_is_blocked(self):
        self.write_product("user-a", "bag-a", "Bag A")

        with self.assertRaises(self.server.HTTPException):
            self.server.resolve_product_path("user-a", "bag-a", "..", "metadata.json")

        response = self.client.get("/api/product-image/bag-a/../metadata.json?token=user-a")

        self.assertIn(response.status_code, (400, 404))

    def test_hosted_mode_blocks_settings_update(self):
        os.environ["HOSTED_MODE"] = "true"

        response = self.client.post("/api/settings", json={"output_dir": "/tmp/elsewhere"})

        self.assertEqual(response.status_code, 403)

    def test_copywriting_model_options_include_default_and_luna(self):
        response = self.client.get("/api/copywriting-model-options")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["default_model_key"], "gpt-4.1-mini")
        model_keys = [model["key"] for model in payload["models"]]
        self.assertIn("gpt-4.1-mini", model_keys)
        self.assertIn("gpt-5.6-luna", model_keys)

    def test_copywriting_profiles_are_workspace_scoped(self):
        profile_response = self.client.get(
            "/api/copywriting-profile",
            headers={"X-User-Token": "profile-a"},
        )
        profile = profile_response.json()["profile"]
        profile["master_rules"] = "Workspace A writes energetic editorial copy."
        profile["risk_controls"]["promotional_language"]["override_enabled"] = True

        save_response = self.client.post(
            "/api/copywriting-profile",
            headers={"X-User-Token": "profile-a"},
            json={"profile": profile},
        )
        other_response = self.client.get(
            "/api/copywriting-profile",
            headers={"X-User-Token": "profile-b"},
        )

        self.assertEqual(save_response.status_code, 200)
        self.assertEqual(
            save_response.json()["profile"]["master_rules"],
            "Workspace A writes energetic editorial copy.",
        )
        self.assertTrue(
            save_response.json()["profile"]["risk_controls"]["promotional_language"]["override_enabled"]
        )
        self.assertNotEqual(
            other_response.json()["profile"]["master_rules"],
            "Workspace A writes energetic editorial copy.",
        )

    def test_copywriting_prompt_preview_shows_active_overrides_and_contract(self):
        profile = self.client.get(
            "/api/copywriting-profile",
            headers={"X-User-Token": "preview-user"},
        ).json()["profile"]
        profile["brand_voice"] = "Playful fashion editorial."
        profile["risk_controls"]["etsy_title_limit"].update({
            "override_enabled": True,
            "value": 220,
        })

        response = self.client.post(
            "/api/copywriting-prompt-preview",
            headers={"X-User-Token": "preview-user"},
            json={"stage_key": "listing_draft", "profile": profile},
        )

        self.assertEqual(response.status_code, 200)
        prompt = response.json()["prompt"]
        self.assertIn("Playful fashion editorial.", prompt)
        self.assertIn("Etsy Title Length [OVERRIDE ENABLED]", prompt)
        self.assertIn("Effective value: 220", prompt)
        self.assertIn("TECHNICAL OUTPUT CONTRACT", prompt)

    def test_copywriting_profile_reset_restores_defaults(self):
        profile = self.client.get(
            "/api/copywriting-profile",
            headers={"X-User-Token": "reset-profile"},
        ).json()["profile"]
        profile["master_rules"] = "Temporary custom rules."
        self.client.post(
            "/api/copywriting-profile",
            headers={"X-User-Token": "reset-profile"},
            json={"profile": profile},
        )

        response = self.client.post(
            "/api/copywriting-profile/reset",
            headers={"X-User-Token": "reset-profile"},
            json={"section": ""},
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(response.json()["profile"]["master_rules"], "Temporary custom rules.")

    def test_copywriting_depth_variation_scan_policy(self):
        from src import server

        variations = [
            {"local_path": "variation_images/var_1.jpg", "alt": "Red"},
            {"local_path": "variation_images/var_2.jpg", "alt": "Blue"},
            {"local_path": "variation_images/var_3.jpg", "alt": "Green"},
            {"local_path": "variation_images/var_4.jpg", "alt": "Yellow"},
            {"local_path": "variation_images/var_5.jpg", "alt": "Purple"},
            {"local_path": "variation_images/var_6.jpg", "alt": "Black"},
        ]

        self.assertFalse(server.should_scan_variation_specs("balanced", variations, "Color options only", "", {}))
        self.assertTrue(server.should_scan_variation_specs("balanced", variations, "Includes 30cm x 40cm size chart", "", {}))
        self.assertFalse(server.should_scan_variation_specs("quality", variations, "Color options only", "", {}))
        self.assertTrue(server.should_scan_variation_specs("quality", variations, "Includes 30cm x 40cm size chart", "", {}))
        self.assertTrue(server.should_scan_variation_specs("deep", variations, "Color options only", "", {}))
        self.assertEqual(len(server.cap_variation_items("balanced", variations)), 5)
        self.assertEqual(len(server.cap_variation_items("quality", variations)), 5)
        self.assertEqual(len(server.cap_variation_items("deep", variations)), 6)
        self.assertEqual(server.normalize_copywriting_depth({}), "quality")

    def test_quality_mode_refreshes_weaker_copywriting_cache(self):
        from src import server

        self.assertFalse(server.can_reuse_copywriting_cache("fast", "quality"))
        self.assertFalse(server.can_reuse_copywriting_cache("balanced", "quality"))
        self.assertTrue(server.can_reuse_copywriting_cache("quality", "balanced"))
        self.assertTrue(server.can_reuse_copywriting_cache("quality", "quality"))
        self.assertEqual(server.normalize_copywriting_model({"openai_model": "gpt-5.6-luna"}), "gpt-5.6-luna")
        self.assertEqual(server.normalize_copywriting_model({"openai_model": "unknown-model"}), "gpt-4.1-mini")

    def test_run_pipeline_accepts_copywriting_depth_option(self):
        self.write_product("depth-user", "depth-product", "Depth Product")

        with unittest.mock.patch("src.server.background_run_pipeline") as mock_background:
            response = self.client.post(
                "/api/run-pipeline",
                headers={"X-User-Token": "depth-user"},
                json={
                    "product_slug": "depth-product",
                    "mode": "listing_only",
                    "image_tasks": [],
                    "image_settings": {"model_key": "flux-kontext-pro"},
                    "copywriting_options": {"depth": "fast", "openai_model": "gpt-5.6-luna"}
                }
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(mock_background.call_args.args[4], {"depth": "fast", "openai_model": "gpt-5.6-luna"})

    def test_cancel_pipeline_marks_processing_item_cancelling(self):
        self.write_product("cancel-user", "cancel-product", "Cancel Product", status="processing")

        response = self.client.post(
            "/api/cancel-pipeline",
            headers={"X-User-Token": "cancel-user"},
            json={"product_slug": "cancel-product"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "success")
        meta_path = os.path.join(
            self.server.get_output_dir("cancel-user"),
            "cancel-product",
            "metadata.json",
        )
        with open(meta_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)
        self.assertEqual(metadata["status"], "cancelling")
        self.assertTrue(metadata["cancel_requested"])
        self.assertTrue(self.server.is_pipeline_cancel_requested("cancel-user", "cancel-product"))
        self.server.clear_pipeline_cancel("cancel-user", "cancel-product")

    def test_background_pipeline_honors_cancel_request(self):
        self.write_product("cancel-user", "cancel-background", "Cancel Background")
        self.server.request_pipeline_cancel("cancel-user", "cancel-background")

        with unittest.mock.patch("src.server.get_genai_client") as mock_client:
            self.server.background_run_pipeline(
                "cancel-background",
                "listing_only",
                image_tasks=[],
                image_settings={"model_key": "flux-kontext-pro"},
                copywriting_options={"depth": "fast"},
                user_token="cancel-user",
            )

        mock_client.assert_not_called()
        meta_path = os.path.join(
            self.server.get_output_dir("cancel-user"),
            "cancel-background",
            "metadata.json",
        )
        with open(meta_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)
        self.assertEqual(metadata["status"], "cancelled")
        self.assertEqual(metadata["error"], "Pipeline cancelled by user")
        self.assertFalse(self.server.is_pipeline_cancel_requested("cancel-user", "cancel-background"))

if __name__ == "__main__":
    unittest.main()
