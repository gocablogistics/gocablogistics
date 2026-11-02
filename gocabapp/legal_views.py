"""Plain server-rendered pages with no auth/API involved — App Store Connect
(and Google Play Console) require a Privacy Policy URL and a Support URL
reachable in a plain browser, which an in-app-only React route can't satisfy
since there was no public website otherwise. Reuses api.gocablogistics.com,
already live/HTTPS, instead of standing up separate hosting under time
pressure for a same-day submission."""
from django.views.generic import TemplateView


class PrivacyPolicyView(TemplateView):
    template_name = "legal/privacy.html"


class TermsView(TemplateView):
    template_name = "legal/terms.html"


class SupportView(TemplateView):
    template_name = "legal/support.html"
