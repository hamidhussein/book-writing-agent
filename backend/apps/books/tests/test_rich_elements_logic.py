from types import SimpleNamespace

from django.test import SimpleTestCase

from apps.books.services.llm import (
    _augment_chapter_payload_rich_elements,
    _detect_rich_elements_in_content,
    _extract_visual_placeholders,
    _normalize_chapter_plan_rich_elements,
    _requested_rich_elements_from_project,
)


def _project_with_rich_elements(values: list[str]) -> SimpleNamespace:
    return SimpleNamespace(
        metadata_json={
            "user_concept": {
                "profile": {
                    "richElements": values,
                }
            }
        }
    )


class RichElementsLogicTests(SimpleTestCase):
    def test_requested_rich_elements_are_canonicalized(self):
        project = _project_with_rich_elements(
            ["Tables", "Code Blocks", "Quotes", "Figures & Diagrams", "Flowcharts", "Callout Boxes"]
        )

        requested = _requested_rich_elements_from_project(project)  # noqa: SLF001

        self.assertEqual(
            requested,
            ["table", "code_block", "quote", "figure", "flowchart", "callout"],
        )

    def test_normalize_chapter_plan_rich_elements_canonicalizes_plan_entries(self):
        plan = {
            "chapter_number": 1,
            "rich_elements_plan": [
                {"type": "Code Blocks", "section": "Example", "purpose": "Show code", "required": True},
                {"type": "Tables", "section": "Comparison", "purpose": "Compare options", "required": False},
            ],
            "visual_specs": [
                {"type": "Figures & Diagrams", "placement_section": "Intro", "caption": "Agent loop", "prompt": "Agent loop diagram"},
                {"type": "Flowcharts", "placement_section": "Process", "caption": "Decision flow", "prompt": "Decision flowchart"},
            ],
        }

        normalized = _normalize_chapter_plan_rich_elements(plan)  # noqa: SLF001

        self.assertEqual(normalized["rich_elements_plan"][0]["type"], "code_block")
        self.assertEqual(normalized["rich_elements_plan"][1]["type"], "table")
        self.assertEqual(normalized["visual_specs"][0]["type"], "figure")
        self.assertEqual(normalized["visual_specs"][1]["type"], "flowchart")

    def test_detect_and_extract_rich_elements_from_content(self):
        content = """# Chapter 1

## Example
```python
print("hello")
```

> [!NOTE] Keep examples simple.

> This is a quoted reminder.

| Term | Meaning |
| --- | --- |
| Agent | A system |

[FIGURE: Agent loop overview]
[FLOWCHART: Prompt to action steps]
"""
        used = _detect_rich_elements_in_content(content)  # noqa: SLF001
        placeholders = _extract_visual_placeholders(content)  # noqa: SLF001

        self.assertIn("code_block", used)
        self.assertIn("callout", used)
        self.assertIn("quote", used)
        self.assertIn("table", used)
        self.assertIn("figure", used)
        self.assertIn("flowchart", used)
        self.assertEqual(len(placeholders), 2)
        self.assertEqual(placeholders[0]["type"], "figure")
        self.assertEqual(placeholders[1]["type"], "flowchart")

    def test_augment_chapter_payload_adds_rich_elements_metadata(self):
        project = _project_with_rich_elements(["Code Blocks", "Figures & Diagrams"])
        payload = {
            "chapter": {
                "number": 1,
                "title": "Basics",
                "content": "## Demo\n```python\nprint('x')\n```\n\n[FIGURE: Agent concept for beginners]",
                "summary": "Test",
            },
            "metadata": {},
        }
        chapter_plan = {
            "rich_elements_plan": [
                {"type": "Code Blocks", "section": "Demo", "purpose": "Show syntax", "required": True}
            ],
            "visual_specs": [
                {"type": "Figures & Diagrams", "placement_section": "Demo", "caption": "Agent concept", "prompt": "Simple agent concept visual"}
            ],
        }

        augmented = _augment_chapter_payload_rich_elements(payload, project, chapter_plan)  # noqa: SLF001
        rich_meta = augmented["metadata"]["rich_elements"]

        self.assertEqual(rich_meta["requested"], ["code_block", "figure"])
        self.assertIn("code_block", rich_meta["used"])
        self.assertIn("figure", rich_meta["used"])
        self.assertEqual(len(rich_meta["visual_placeholders"]), 1)
        self.assertEqual(rich_meta["render_status"], "placeholders_pending")

