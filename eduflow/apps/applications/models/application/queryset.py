from datetime import date
from typing import TYPE_CHECKING
from uuid import UUID

from django.db.models import Q, QuerySet

if TYPE_CHECKING:
    from eduflow.apps.applications.models.application._model import Application


class ApplicationQuerySet(QuerySet):
    def search(
        self,
        *,
        q: str = "",
        contact_date_from: date | None = None,
        contact_date_to: date | None = None,
    ) -> QuerySet["Application"]:
        queryset = self
        if q:
            try:
                receipt = Q(pk=UUID(q))
            except ValueError:
                receipt = Q(pk__icontains=q)
            queryset = queryset.filter(receipt | Q(name__icontains=q) | Q(email__icontains=q))
        if contact_date_from is not None:
            queryset = queryset.filter(contact_date__gte=contact_date_from)
        if contact_date_to is not None:
            queryset = queryset.filter(contact_date__lte=contact_date_to)
        return queryset
