from django.views.generic.base import TemplateView


home = TemplateView.as_view(template_name="home.html")
course_detail = TemplateView.as_view(template_name="course.html")
apply = TemplateView.as_view(template_name="apply.html")
