from django.templatetags.static import static
from django.utils.timezone import localdate
from rest_framework.serializers import ModelSerializer, SerializerMethodField

from eduflow.apps.courses.covers import sample_course_cover_alt
from eduflow.apps.courses.models import Course


class CourseListSerializer(ModelSerializer):
    image = SerializerMethodField()

    class Meta:
        model = Course
        fields = ("slug", "title", "tagline", "image")

    def get_image(self, course: Course) -> dict[str, str] | None:
        url, alt = course.course_image, course.course_image_alt
        if not url:
            alt = sample_course_cover_alt(course.slug)
            if not alt:
                return None
            url = static(f"courses/{course.slug}.webp")
        request = self.context.get("request")
        return {"url": request.build_absolute_uri(url) if request else url, "alt": alt}


class CourseDetailSerializer(CourseListSerializer):
    intake = SerializerMethodField()
    contact_date_min = SerializerMethodField()

    class Meta(CourseListSerializer.Meta):
        fields = (
            *CourseListSerializer.Meta.fields, "curriculum", "capacity",
            "application_deadline_at", "intake", "contact_date_min",
        )

    def get_intake(self, course: Course) -> dict[str, str]:
        status = course.intake_status()
        return {"code": status.value, "label": status.label}

    def get_contact_date_min(self, course: Course) -> str:
        return localdate().isoformat()


class StaffCourseChoiceSerializer(ModelSerializer):
    class Meta:
        model = Course
        fields = ("slug", "title", "is_published")
