from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.books.models import BookProject


class Command(BaseCommand):
    help = (
        "Assign owner for legacy BookProject rows where owner is NULL. "
        "Safe only for confirmed single-owner datasets."
    )

    def add_arguments(self, parser):
        parser.add_argument("--user-id", type=int, default=0, help="Target user id.")
        parser.add_argument("--username", type=str, default="", help="Target username.")
        parser.add_argument(
            "--confirm-single-owner",
            action="store_true",
            help="Required safety confirmation for blanket owner assignment.",
        )

    def handle(self, *args, **options):
        User = get_user_model()
        user_id = int(options.get("user_id", 0) or 0)
        username = str(options.get("username", "")).strip()
        confirm_single_owner = bool(options.get("confirm_single_owner"))

        target_user = None
        if user_id:
            target_user = User.objects.filter(id=user_id).first()
        elif username:
            target_user = User.objects.filter(username=username).first()
        else:
            target_user = User.objects.order_by("id").first()

        if target_user is None:
            raise CommandError("No target user found. Provide --user-id or --username.")

        qs = BookProject.objects.filter(owner__isnull=True)
        pending_count = qs.count()
        if pending_count == 0:
            self.stdout.write(self.style.SUCCESS("No legacy null-owner projects found."))
            return
        if not confirm_single_owner:
            raise CommandError(
                "Safety check: this command is intended for confirmed single-owner datasets. "
                "Re-run with --confirm-single-owner after validating ownership assumptions. "
                "For multi-user legacy data, use a mapping script instead of blanket assignment."
            )

        updated = qs.update(owner=target_user)
        self.stdout.write(
            self.style.SUCCESS(f"Assigned owner '{target_user.username}' to {updated} project(s).")
        )
