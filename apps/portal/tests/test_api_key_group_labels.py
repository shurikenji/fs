import unittest

from app.routers.api_keys import _build_group_display_names, _display_selected_groups


class KeyApiGroupLabelTests(unittest.TestCase):
    def test_selected_group_labels_use_available_group_display_names(self) -> None:
        raw_group = "\u4f18\u8d28banana"
        display_names = _build_group_display_names(
            [{"name": raw_group, "display_name": "Premium banana"}],
            [raw_group],
        )

        self.assertEqual(display_names[raw_group], "Premium banana")
        self.assertEqual(_display_selected_groups([raw_group], display_names), ["Premium banana"])

    def test_selected_group_labels_fall_back_to_sanitizer(self) -> None:
        raw_group = "\u9006\u5411"
        display_names = _build_group_display_names([], [raw_group])

        self.assertEqual(display_names[raw_group], "Reverse")
        self.assertEqual(_display_selected_groups([raw_group], display_names), ["Reverse"])
