from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.serializers import (
    CharField, ChoiceField, DateField, EmailField, IntegerField, ModelSerializer,
    Serializer, SerializerMethodField, SlugField, UUIDField, ValidationError,
)

from eduflow.apps.applications.choices import ApplicationStatus, ReminderStatus
from eduflow.apps.applications.models import Application, ApplicationReminder


class ApplicationSubmissionSerializer(Serializer):
    course_slug = SlugField(max_length=120)
    submission_id = UUIDField()
    name = CharField(max_length=100)
    email = EmailField(max_length=254)
    address = CharField(max_length=500)
    contact_date = DateField(input_formats=["%Y-%m-%d"])

    def save(self) -> tuple[Application, bool]:
        try:
            return Application.objects.submit(**self.validated_data)
        except DjangoValidationError as exc:
            raise ValidationError(exc.message_dict) from exc


class ApplicationListSerializer(ModelSerializer):
    course = SlugField(source="course.slug")

    class Meta:
        model = Application
        fields = ("id", "course", "status", "contact_date", "created_at")


class StaffApplicationListSerializer(ApplicationListSerializer):
    course_title = CharField(source="course.title")
    status_label = CharField(source="get_status_display")

    class Meta(ApplicationListSerializer.Meta):
        fields = (
            *ApplicationListSerializer.Meta.fields, "course_title", "status_label",
            "name", "email", "completed_at",
        )


class StaffApplicationDetailSerializer(StaffApplicationListSerializer):
    latest_mail_delivery = SerializerMethodField()

    class Meta(StaffApplicationListSerializer.Meta):
        fields = (*StaffApplicationListSerializer.Meta.fields, "address", "latest_mail_delivery")

    def get_latest_mail_delivery(self, application: Application) -> dict[str, str] | None:
        request = self.context.get("request")
        if request is None or not request.user.has_perm("applications.view_applicationreminder"):
            return None
        delivery = application.reminders.order_by("-created_at", "-pk").first()
        if delivery is None:
            return None
        return {
            "id": str(delivery.pk),
            "status": delivery.status,
            "status_label": delivery.get_status_display(),
        }


class ApplicationUpdateSerializer(ModelSerializer):
    class Meta:
        model = Application
        fields = ("name", "email", "address", "contact_date", "status")

    def update(self, instance: Application, validated_data: dict[str, Any]) -> Application:
        reminder_fields_changed = any(
            getattr(instance, field) != validated_data[field]
            for field in ("status", "contact_date", "email")
            if field in validated_data
        )
        status = validated_data.pop("status", None)
        if status is not None:
            instance.change_status(ApplicationStatus(status))
        application = super().update(instance, validated_data)
        if reminder_fields_changed:
            application.synchronize_contact_reminder()
        return application


class ApplicationFiltersSerializer(Serializer):
    course = SlugField(required=False)
    course_id = IntegerField(required=False, min_value=1)
    status = ChoiceField(choices=ApplicationStatus, required=False)
    contact_date = DateField(required=False)
    q = CharField(required=False, allow_blank=True, max_length=254)
    contact_date_from = DateField(required=False, input_formats=["%Y-%m-%d"])
    contact_date_to = DateField(required=False, input_formats=["%Y-%m-%d"])

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        start = attrs.get("contact_date_from")
        end = attrs.get("contact_date_to")
        if start and end and start > end:
            raise ValidationError({
                "contact_date_to": "종료일은 시작일과 같거나 이후여야 합니다."
            })
        return attrs


class StaffApplicationReminderSerializer(ModelSerializer):
    application_id = UUIDField(read_only=True)
    course_title = CharField(source="application.course.title", read_only=True)
    current_recipient_email = EmailField(source="application.email", read_only=True)
    kind_label = CharField(source="get_kind_display", read_only=True)
    status_label = CharField(source="get_status_display", read_only=True)

    class Meta:
        model = ApplicationReminder
        fields = (
            "id", "application_id", "course_title", "current_recipient_email",
            "kind", "kind_label", "status", "status_label", "scheduled_at", "sent_at",
            "next_attempt_at", "attempt_count", "last_error_code",
        )
        read_only_fields = fields


class ApplicationReminderFiltersSerializer(Serializer):
    status = ChoiceField(choices=ReminderStatus, required=False)
    q = CharField(required=False, allow_blank=True, max_length=254)
