"""Context processors for browser UI."""

from app.web.browser.models import System


def systems_nav(_request):
    systems = System.objects.all().order_by("name").values("id", "name")
    return {"nav_systems": list(systems)}
