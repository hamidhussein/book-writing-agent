from apps.books.models import BookProject
from apps.books.services.pipeline import BookWorkflowService


project = BookProject.objects.create(
    title="Test Book",
    genre="Non-fiction",
    target_audience="Builders",
    language="English",
    tone="Practical",
    target_word_count=5000,
)

service = BookWorkflowService()
print("toc", service.execute_mode(project, "toc", {})["status"])
print("refine", service.execute_mode(project, "refine_toc", {"feedback": "add concrete workflows"})["status"])
print("chapter", service.execute_mode(project, "chapter", {"chapter_number": 1})["status"])

export_output = service.execute_mode(project, "export", {"export_format": "both"})
print(
    "export",
    export_output["status"],
    bool(export_output.get("pdf_base64")),
    bool(export_output.get("docx_base64")),
)
