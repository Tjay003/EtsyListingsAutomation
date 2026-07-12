import os
import json
import tempfile
import unittest
import yaml
from unittest.mock import MagicMock
from fastapi.testclient import TestClient
from src.ai_helper import clean_tags, write_etsy_listing, extract_variation_specs
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
        mock_response_strategy.text = '{"primary_product_noun": "test product", "top_traits": ["woven yarn"], "buyer_intents": ["everyday use"], "audience": [], "primary_keywords": ["test product", "woven yarn product"], "long_tail_keywords": ["woven yarn test product"], "tag_keywords": ["test product", "woven yarn", "everyday use"], "google_keywords": ["test product"], "pinterest_keywords": ["woven yarn product"]}'
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
            presets={},
            image_facts=image_facts
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["title"], "Test Title")
        self.assertEqual(result["suggested_price"], "$15.99")
        self.assertEqual(len(result["tags"]), 13)
        self.assertIn("google_meta_title", result)
        self.assertIn("pinterest_description", result)
        self.assertIn("seo_quality_score", result)
        # Ensure client was called for SEO strategy, draft, and self-review critic
        self.assertEqual(mock_client.models.generate_content.call_count, 3)

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

if __name__ == "__main__":
    unittest.main()
