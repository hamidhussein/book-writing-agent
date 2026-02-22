from __future__ import annotations

import logging
from typing import Any, Dict

from celery import shared_task
from django.utils import timezone

from .models import AgentRun, RunStatus
from .services.orchestration import AgentOrchestrator

logger = logging.getLogger(__name__)


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 2})
def execute_agent_run(self, run_id: str) -> Dict[str, Any]:
    run = AgentRun.objects.select_related("project").filter(id=run_id).first()
    if not run:
        return {"status": "error", "error": "run_not_found"}

    run.status = RunStatus.RUNNING
    run.started_at = timezone.now()
    run.error_message = ""
    run.save(update_fields=["status", "started_at", "error_message"])

    orchestrator = AgentOrchestrator()
    try:
        output = orchestrator.execute(run)
        run.output_payload = output or {}
        run.timings_json = output.get("timings_ms", {}) if isinstance(output, dict) else {}
        run.status = RunStatus.COMPLETED
        run.finished_at = timezone.now()
        run.save(update_fields=["output_payload", "timings_json", "status", "finished_at"])
        return {"status": "ok"}
    except Exception as exc:
        logger.error("Agent run failed", exc_info=True)
        run.status = RunStatus.FAILED
        run.error_message = str(exc)[:2000] or "Agent execution failed"
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "error_message", "finished_at"])
        return {"status": "error", "error": run.error_message}
