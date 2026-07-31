# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from django.core.exceptions import ValidationError
from django.db import models

from django_contact_forms.models.base_model import BaseModel


class BookingTimeWindow(BaseModel):
    """A single working window within a BookingConfig (e.g., 10:00-12:30 or 16:00-17:00).

    A config can have any number of windows; slots are generated per window in
    ``order, start_time`` sequence. Cluster generation (FOMO) and slot validation
    treat windows as independent ranges — clusters never span two windows.
    """

    booking_config = models.ForeignKey("BookingConfig", on_delete=models.CASCADE, related_name="time_windows")
    order = models.PositiveSmallIntegerField(default=0, help_text="Sort order for admin display.")
    start_time = models.TimeField(help_text="Window start (inclusive), e.g., 10:00.")
    end_time = models.TimeField(help_text="Window end (exclusive), e.g., 12:30.")

    class Meta:
        ordering = ["booking_config", "order", "start_time"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(end_time__gt=models.F("start_time")), name="bookingtimewindow_end_after_start"
            )
        ]

    def __str__(self) -> str:
        return f"{self.start_time:%H:%M}-{self.end_time:%H:%M}"

    def clean(self) -> None:
        super().clean()
        if self.end_time <= self.start_time:
            raise ValidationError({"end_time": "end_time must be after start_time"})
