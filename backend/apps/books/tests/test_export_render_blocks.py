from django.test import SimpleTestCase

from apps.books.services.pipeline import BookWorkflowService


class ExportRenderBlocksTests(SimpleTestCase):
    def setUp(self):
        self.service = BookWorkflowService.__new__(BookWorkflowService)  # bypass __init__

    def test_iter_render_blocks_parses_rich_content_blocks(self):
        content = """# Title

## Section

> [!TIP] Use short examples.

```python
print("hello")
```

| A | B |
| --- | --- |
| 1 | 2 |

[FIGURE: Agent loop]
[FLOWCHART: Decision path]
"""

        blocks = self.service._iter_render_blocks(content)  # noqa: SLF001
        types = [block.get("type") for block in blocks]

        self.assertIn("h1", types)
        self.assertIn("h2", types)
        self.assertIn("callout", types)
        self.assertIn("code", types)
        self.assertIn("table", types)
        self.assertEqual(types.count("visual_placeholder"), 2)

