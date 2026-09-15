from piem.version import get_version_info
from django.conf import settings
from django.templatetags.static import static

def version_context(request):
    public_url = settings.PUBLIC_SITE_URL
    version = get_version_info()
    match = request.resolver_match
    public_page = bool(match and match.url_name in {"home", "courses", "showcase"})
    insights = None
    if settings.SPEED_INSIGHTS_ENABLED and not settings.DEBUG and public_page and settings.SPEED_INSIGHTS_SAMPLE_RATE > 0:
        insights = {
            "scriptSrc": settings.SPEED_INSIGHTS_SCRIPT_URL,
            "sampleRate": settings.SPEED_INSIGHTS_SAMPLE_RATE,
            "route": request.path,
        }
    return {
        "version_info": version,
        "PIEM_VERSION": version["version"],
        "PIEM_RELEASE_NAME": version["release_name"],
        "PIEM_OG_IMAGE": f"{public_url}{static('core/og.png')}" if public_url else "",
        "PIEM_SPEED_INSIGHTS": insights,
        "PIEM_ROBOTS": "index,follow" if public_page else "noindex,nofollow",
    }
