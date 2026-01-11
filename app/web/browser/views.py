"""Minimal browse views."""

from django.core.paginator import Paginator
from django.db.models import Count
from django.shortcuts import get_object_or_404, render

from app.web.browser.models import Attribute, Release, Rom, System, Title


def search(request):
    query = request.GET.get("q", "").strip()
    results = []
    if len(query) >= 2:
        results = (
            Title.objects.select_related("system")
            .filter(name__icontains=query)
            .order_by("name")[:100]
        )
    return render(
        request,
        "browser/search.html",
        {"query": query, "results": results},
    )


def titles(request, system_id: int):
    system = get_object_or_404(System, id=system_id)
    query = request.GET.get("q", "").strip()
    qs = Title.objects.filter(system=system).order_by("name")
    if query:
        qs = qs.filter(name__icontains=query)

    paginator = Paginator(qs, 100)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)
    return render(
        request,
        "browser/titles.html",
        {
            "system": system,
            "query": query,
            "page_obj": page_obj,
            "paginator": paginator,
        },
    )


def title_detail(request, title_id: int):
    title = get_object_or_404(Title, id=title_id)
    releases = list(
        Release.objects.filter(title=title)
        .order_by("region", "release_year", "release_month", "serial")
    )
    release_ids = [release.id for release in releases]
    roms = (
        Rom.objects.filter(release_id__in=release_ids)
        .order_by("rom_name")
        .values("release_id", "rom_name")
    )
    roms_by_release = {}
    for rom in roms:
        roms_by_release.setdefault(rom["release_id"], []).append(rom["rom_name"])
    for release in releases:
        release.rom_names = roms_by_release.get(release.id, [])
    attributes = (
        Attribute.objects.filter(entity_type="release", entity_id__in=release_ids)
        .order_by("key", "value")
        .values("key", "value")
    )
    grouped_attributes = {}
    for attr in attributes:
        grouped_attributes.setdefault(attr["key"], set()).add(attr["value"])
    return render(
        request,
        "browser/title_detail.html",
        {
            "title": title,
            "releases": releases,
            "attributes": {
                key: sorted(values) for key, values in grouped_attributes.items()
            },
        },
    )
