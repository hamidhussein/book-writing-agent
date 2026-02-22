from __future__ import annotations

from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.response import Response

from .models import AgentRun, RunStatus
from .serializers import AgentRunCreateSerializer, AgentRunSerializer
from .services.orchestration import AgentOrchestrator
from .tasks import execute_agent_run


class AgentRunViewSet(mixins.CreateModelMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    queryset = AgentRun.objects.none()
    serializer_class = AgentRunSerializer

    def get_queryset(self):
        return AgentRun.objects.filter(project__owner=self.request.user).select_related("project")

    def create(self, request, *args, **kwargs):
        create_serializer = AgentRunCreateSerializer(data=request.data, context={"request": request})
        create_serializer.is_valid(raise_exception=True)
        validated = create_serializer.validated_data

        run = AgentRun.objects.create(
            project_id=validated["project_id"],
            mode=validated["mode"],
            status=RunStatus.QUEUED,
            input_payload=validated.get("inputs", {}),
        )

        sync = str(request.query_params.get("sync", "0")).lower() in {"1", "true", "yes"}
        if sync:
            run.status = RunStatus.RUNNING
            run.started_at = timezone.now()
            run.save(update_fields=["status", "started_at"])

            orchestrator = AgentOrchestrator()
            try:
                output = orchestrator.execute(run)
                run.output_payload = output or {}
                run.timings_json = output.get("timings_ms", {}) if isinstance(output, dict) else {}
                run.status = RunStatus.COMPLETED
                run.finished_at = timezone.now()
                run.save(update_fields=["output_payload", "timings_json", "status", "finished_at"])
            except Exception as exc:
                run.status = RunStatus.FAILED
                run.error_message = str(exc)[:2000] or "Agent execution failed"
                run.finished_at = timezone.now()
                run.save(update_fields=["status", "error_message", "finished_at"])
        else:
            execute_agent_run.delay(str(run.id))

        serializer = AgentRunSerializer(run)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
