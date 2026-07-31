# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from datetime import datetime
from hashlib import sha256
from typing import TYPE_CHECKING

from django.db import models
from django.utils.crypto import get_random_string

from django_contact_forms.models.base_model import BaseModel

if TYPE_CHECKING:
    from django_contact_forms.models.channel import Channel


class APIKey(BaseModel):
    class Scope(models.TextChoices):
        CONTACT_FORM = "contact_form", "Contact form"
        BOOKING = "booking", "Booking"

    channel: "Channel" = models.ForeignKey("Channel", null=True, on_delete=models.CASCADE)
    key = models.CharField(max_length=128, editable=False)
    scope = models.CharField(
        max_length=16,
        choices=Scope.choices,
        default=Scope.CONTACT_FORM,
        help_text="What endpoints this key may call. Existing keys default to 'contact_form'.",
    )
    objects = models.Manager()

    def generate_key(self):
        seed = "".join([get_random_string(length=16), str(datetime.now()), get_random_string(length=16)])
        key = sha256(seed.encode("utf-8")).hexdigest()
        return key

    def save(self, *args, **kwargs) -> None:
        if self.key is None or self.key == "":
            self.key = self.generate_key()

        return super().save(*args, **kwargs)
