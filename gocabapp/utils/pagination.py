"""Shared paginator helpers for HTMX-style JSON partials."""

from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.http import HttpRequest, JsonResponse
from django.template.loader import render_to_string


def paginate_request_page(
    request: HttpRequest, queryset, per_page: int, page_param: str = "page"
):
    """Return the current page for GET `page` (defaults to 1)."""
    paginator = Paginator(queryset, per_page)
    raw_page = request.GET.get(page_param, 1)
    try:
        return paginator.page(raw_page)
    except PageNotAnInteger:
        return paginator.page(1)
    except EmptyPage:
        return paginator.page(paginator.num_pages)


def json_partial_html(
    request: HttpRequest, template_name: str, context: dict
) -> JsonResponse:
    """Render a template fragment and return `{'html': ...}` for JsonResponse APIs."""
    context = {**context, "request": request}
    html = render_to_string(template_name, context)
    return JsonResponse({"html": html})
