# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from django.db import models


class BaseModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now=True)

    # Powyższe kolumny dodadzą się na początku tabeli w DB
    # Aby sobie to zmienić należy po utworzeniu migracji edytować ją i
    # przenieść tworzenie tych kolumn na koniec. (estetyka)

    class Meta:
        abstract = True
