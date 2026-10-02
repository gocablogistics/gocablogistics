dev:
	DJANGO_SETTINGS_MODULE=Gocabservices.settings.development daphne -b 127.0.0.1 -p 8000 Gocabservices.asgi:application