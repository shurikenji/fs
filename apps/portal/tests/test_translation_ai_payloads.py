import unittest

from app.translation_ai_payloads import (
    normalize_ai_group_response,
    normalize_ai_text_response,
    parse_ai_json,
)


class TranslationAiPayloadsTests(unittest.TestCase):
    def test_parse_ai_json_accepts_fenced_json(self) -> None:
        payload = parse_ai_json('```json\n{"items":[{"original_text":"a","text_en":"b"}]}\n```')
        self.assertEqual(payload["items"][0]["text_en"], "b")

    def test_parse_ai_json_extracts_embedded_object(self) -> None:
        payload = parse_ai_json('noise before {"items":[{"original_name":"g1","name_en":"Group 1"}]} noise after')
        self.assertEqual(payload["items"][0]["name_en"], "Group 1")

    def test_normalize_ai_group_response_supports_items_and_mapping(self) -> None:
        self.assertEqual(
            normalize_ai_group_response(
                {"items": [{"original_name": "g1", "name_en": "Group 1", "desc_en": "Desc", "category": "General"}]}
            ),
            {"g1": {"name_en": "Group 1", "desc_en": "Desc", "category": "General"}},
        )
        self.assertEqual(
            normalize_ai_group_response(
                {"g2": {"name_en": "Group 2", "desc_en": "", "category": ""}}
            ),
            {"g2": {"name_en": "Group 2", "desc_en": "", "category": "Other"}},
        )

    def test_normalize_ai_text_response_sanitizes_and_supports_mapping(self) -> None:
        self.assertEqual(
            normalize_ai_text_response(
                {"items": [{"original_text": "中文", "text_en": "Concise English"}]}
            ),
            {"中文": "Concise English"},
        )
        self.assertEqual(
            normalize_ai_text_response(
                {"中文": {"text_en": "Still 中文"}}
            ),
            {"中文": "Still"},
        )
