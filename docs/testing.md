---
title: Testing
description: How to run the django-contact-forms test suite and what each test file covers.
---

```bash
uv run pytest              # postgres via DATABASE_URL (default: postgres:postgres@localhost:5432/test)
```

| File | Scope |
|------|-------|
| `test_admin_api.py` | Auth (401/403/200), list, retrieve, search, pagination, notification config CRUD |
| `test_public_api.py` | Auth (401 no key / wrong key, 201 valid), submit, validation, multipart upload |
| `test_services.py` | contact_form_service CRUD, notification_service fallback chain |
| `test_service_booking.py` / `test_booking_time_window.py` / `test_fomo.py` | booking domain |
| `test_service_lead.py` / `test_service_conversions.py` | leads + conversion uploads |
| `test_form_types.py` / `test_multilang_booking.py` / `test_calendar_backends.py` | type catalog, i18n, backends |
