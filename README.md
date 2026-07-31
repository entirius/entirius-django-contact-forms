# Contact Forms

Forms Django module for Volkanos — channel-scoped contact form submissions with attachments,
per-type notification routing, booking calendar (optional Google Calendar backend), lead tracking
and Google Ads offline-conversion uploads.

## Install

```bash
uv pip install entirius-django-contact-forms
```

Optional extras:

```toml
"entirius-django-contact-forms[bookings,google-ads,email]>=3.0.0"
```

- `bookings` — Google Calendar backend for the booking endpoint.
- `google-ads` — click-conversion uploads for leads.
- `email` — branded notification e-mails via `entirius-django-email` (no-op fallback without it).

Add `django_contact_forms` to `INSTALLED_APPS` (requires `django_regional`); set `PRIVATE_DIR`.
Full settings reference and architecture: [AGENTS.md](AGENTS.md).

## Development and testing

```bash
make install   # uv sync, incl. extras
make check     # ruff lint + format-check
make test      # pytest (postgres via DATABASE_URL)
```
