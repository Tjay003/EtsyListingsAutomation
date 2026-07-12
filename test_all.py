import os
import unittest
import yaml
from unittest.mock import MagicMock
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

if __name__ == "__main__":
    unittest.main()
