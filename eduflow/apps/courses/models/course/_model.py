from django.core.validators import MinValueValidator
from django.db import models

from eduflow.apps.courses.models.course.mixins import CourseIntakeMixin


class Course(CourseIntakeMixin, models.Model):
    id = models.BigAutoField(
        "교육 ID", primary_key=True, help_text="교육을 고유하게 식별하는 번호입니다."
    )
    slug = models.SlugField(
        "교육 슬러그", max_length=120, unique=True,
        help_text="교육 소개와 신청 페이지의 URL에 사용하는 고유한 이름입니다.",
    )
    title = models.CharField(
        "교육명", max_length=160, help_text="교육 소개 페이지에 표시할 교육 이름입니다."
    )
    tagline = models.CharField(
        "한 줄 소개", max_length=240, help_text="교육의 주제와 목표를 한 문장으로 소개합니다."
    )
    curriculum = models.JSONField(
        "커리큘럼", default=list, help_text="교육에서 다루는 주제를 진행 순서대로 나열합니다."
    )
    course_image = models.URLField(
        "교육 이미지", max_length=500, blank=True,
        help_text="교육 소개 페이지에 표시할 대표 이미지의 URL입니다.",
    )
    course_image_alt = models.CharField(
        "이미지 대체 텍스트", max_length=200, blank=True,
        help_text="이미지를 볼 수 없는 경우에도 내용을 이해할 수 있도록 설명을 입력합니다.",
    )
    is_published = models.BooleanField(
        "공개 여부", default=False, help_text="교육 소개 페이지를 공개할지 결정합니다."
    )
    capacity = models.PositiveIntegerField(
        "교육 정원", validators=[MinValueValidator(1)],
        help_text="완료 상태의 신청 건수가 이 인원에 도달하면 신규 신청 접수를 마감합니다.",
    )
    application_deadline_at = models.DateTimeField(
        "접수 마감 시각", help_text="이 시각부터 교육의 신규 신청 접수를 종료합니다."
    )

    class Meta:
        verbose_name = "교육 과정"
        verbose_name_plural = "교육 과정"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(capacity__gte=1), name="course_capacity_positive"
            ),
        ]

    def __str__(self) -> str:
        return self.title
