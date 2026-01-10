"""Minimal browse views."""

from django.core.paginator import Paginator
from django.db.models import Count
from django.shortcuts import get_object_or_404, render

from app.web.browser.models import Release, Rom, System, Title


def systems(request):
    systems = (
        System.objects.all()
        .annotate(title_count=Count("title"))
        .order_by("name")
    )
    return render(request, "browser/systems.html", {"systems": systems})


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
    releases = (
        Release.objects.filter(title=title)
        .annotate(rom_count=Count("rom"))
        .order_by("region", "release_year", "release_month", "serial")
    )
    total_roms = Rom.objects.filter(release__title=title).count()
    return render(
        request,
        "browser/title_detail.html",
        {"title": title, "releases": releases, "total_roms": total_roms},
    )
