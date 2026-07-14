import os
import json
import tempfile
import unittest
import yaml
from unittest.mock import MagicMock
from fastapi.testclient import TestClient
from src.ai_helper import clean_tags, write_etsy_listing, extract_variation_specs, finalize_listing_seo, score_listing_seo
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
        self.assertLess(
            listing_prompt.index("SHOP OWNER COPYWRITING RULES (high priority)"),
            listing_prompt.index("Guidelines:"),
        )
        self.assertIn("safe lifestyle/story opening", listing_prompt)
        self.assertIn("Product Details:", listing_prompt)
        self.assertIn("List only confirmed facts", listing_prompt)

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

    def write_product(self, token, slug, title):
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
            "status": "queued",
        }
        with open(os.path.join(product_dir, "metadata.json"), "w", encoding="utf-8") as f:
            json.dump(metadata, f)

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
                    "copywriting_options": {"depth": "fast"}
                }
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(mock_background.call_args.args[4], {"depth": "fast"})

if __name__ == "__main__":
    unittest.main()
