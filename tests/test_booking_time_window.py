# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""BookingTimeWindow model: clean(), __str__, CheckConstraint at DB level."""

from datetime import time

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from django_contact_forms.models import BookingTimeWindow
from tests.factories import BookingConfigFactory


@pytest.mark.django_db
def test_str_formats_as_hhmm_range():
    cfg = BookingConfigFactory(time_windows=[{"start_time": time(10, 0), "end_time": time(12, 30)}])
    window = cfg.time_windows.first()
    assert str(window) == "10:00-12:30"


@pytest.mark.django_db
def test_clean_rejects_end_equal_to_start():
    cfg = BookingConfigFactory(time_windows=[{"start_time": time(9, 0), "end_time": time(17, 0)}])
    bad = BookingTimeWindow(booking_config=cfg, order=1, start_time=time(10, 0), end_time=time(10, 0))
    with pytest.raises(ValidationError) as exc:
        bad.clean()
    assert "end_time" in exc.value.message_dict


@pytest.mark.django_db
def test_clean_rejects_end_before_start():
    cfg = BookingConfigFactory(time_windows=[{"start_time": time(9, 0), "end_time": time(17, 0)}])
    bad = BookingTimeWindow(booking_config=cfg, order=1, start_time=time(15, 0), end_time=time(10, 0))
    with pytest.raises(ValidationError):
        bad.clean()


@pytest.mark.django_db
def test_db_constraint_rejects_end_before_start():
    cfg = BookingConfigFactory(time_windows=[{"start_time": time(9, 0), "end_time": time(17, 0)}])
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            BookingTimeWindow.objects.create(booking_config=cfg, order=2, start_time=time(15, 0), end_time=time(10, 0))


@pytest.mark.django_db
def test_db_constraint_rejects_end_equal_to_start():
    cfg = BookingConfigFactory(time_windows=[{"start_time": time(9, 0), "end_time": time(17, 0)}])
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            BookingTimeWindow.objects.create(booking_config=cfg, order=3, start_time=time(12, 0), end_time=time(12, 0))


@pytest.mark.django_db
def test_ordering_by_order_then_start_time():
    cfg = BookingConfigFactory(
        time_windows=[
            {"order": 2, "start_time": time(8, 0), "end_time": time(9, 0)},
            {"order": 0, "start_time": time(16, 0), "end_time": time(17, 0)},
            {"order": 1, "start_time": time(10, 0), "end_time": time(12, 0)},
        ]
    )
    windows = list(cfg.time_windows.all())
    assert [w.order for w in windows] == [0, 1, 2]


@pytest.mark.django_db
def test_cascade_delete_on_booking_config():
    cfg = BookingConfigFactory(time_windows=[{"start_time": time(9, 0), "end_time": time(17, 0)}])
    window_pk = cfg.time_windows.first().pk
    cfg.delete()
    assert not BookingTimeWindow.objects.filter(pk=window_pk).exists()
