# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""FOMO synthetic busy slot generator.

Adds *fake* busy periods to the calendar to make a young or low-traffic booking
calendar look more occupied — to combat empty-calendar deterrence (visitors
abandon when "nobody else is using this"). Three layers:

1. Time-decay multiplier — today ×1.5, tomorrow ×1.3, 2-6 days ×1.0, 7+ ×0.75.
   Caps at 80% blocked per day to avoid full-occupancy deterrence (always ≥1 free).
2. Slot-cluster generation — 2-4 consecutive slots per cluster, weighted toward
   business peak hours (10-12, 13-16). Mirrors how real bookings cluster.
3. Day-level blackout — 0-3 full-day blocks within the visible window. Never
   today/tomorrow (those need "fresh availability" urgency).

A booking config can have multiple :class:`BookingTimeWindow` rows; cluster
generation is constrained per-window (clusters never span two windows). Slot
indices are global (numbered 0..N-1 across all windows in `order, start_time`
sequence) but the helpers map back to the originating window when constructing
busy periods.

Per-day seed = ``HMAC-SHA256(SECRET_KEY, "fomo|{channel_idx}|{day}")`` so the
layout is stable for refreshing visitors within a calendar day and rotates
naturally at midnight.

Synthetic periods are returned as ``BackendBusyPeriod`` (same dataclass as real
backends emit) so they merge transparently in ``booking_service.get_available_slots``.
The backend's ``is_slot_free`` does NOT consult this module — synthetic busy
filters visibility, never blocks an actual booking.
"""

import hashlib
import hmac
import math
import random
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings

from django_contact_forms.models import BookingConfig, BookingTimeWindow
from django_contact_forms.services.calendar.backends.base import BackendBusyPeriod

_WEEKEND_WEEKDAYS = (5, 6)


def is_weekend(d: date) -> bool:
    return d.weekday() in _WEEKEND_WEEKDAYS


# Cluster size distribution — most real-world meetings are 1h (= 2 × 30-min slots).
CLUSTER_SIZE_WEIGHTS: list[tuple[int, float]] = [(2, 0.6), (3, 0.3), (4, 0.1)]

# Per-day intensity ceiling. Above this threshold the calendar reads as
# "fully booked" and visitors give up; we always leave breathing room.
DAY_INTENSITY_CAP_PCT = 80

# Time-decay multipliers per day offset from today.
_DECAY_TODAY = 1.5
_DECAY_TOMORROW = 1.3
_DECAY_WEEK = 1.0
_DECAY_BEYOND = 0.75
_DECAY_WEEK_THRESHOLD_DAYS = 6

# Today (offset 0) and tomorrow (offset 1) are excluded from full-day blackouts
# so "fresh availability" urgency works (a fully blocked today/tomorrow kills conversion).
_BLACKOUT_MIN_OFFSET = 2

# Bound the cluster-placement retry loop. One attempt per possible cluster start
# position with slack for size resampling.
_CLUSTER_ATTEMPT_MULTIPLIER = 3

# Per-hour weights for cluster start placement.
_PEAK_HOUR_WEIGHTS: dict[int, float] = {9: 0.4, 10: 1.0, 11: 1.0, 12: 0.6, 13: 1.0, 14: 1.0, 15: 1.0, 16: 0.4}

# Type alias: (slot_idx_start_inclusive, slot_idx_end_exclusive, window).
# Built once per request; lets us look up which BookingTimeWindow owns a given
# slot index in O(W) where W = number of windows (typically 1-3).
_SlotRange = tuple[int, int, BookingTimeWindow]


def generate_synthetic_busy_periods(
    *,
    channel_idx: str,
    config: BookingConfig,
    real_busy: list[BackendBusyPeriod],
    start_day: date,
    horizon_days: int,
    windows: list[BookingTimeWindow] | None = None,
) -> list[BackendBusyPeriod]:
    """Return synthetic busy intervals for the visible booking window.

    ``windows`` is optional — when omitted the function falls back to
    ``config.time_windows.all()``. Callers in the request hot path should pass
    a pre-fetched list to avoid an extra DB query.
    """
    if not config.fomo_enabled or config.fomo_intensity <= 0 or horizon_days <= 0:
        return []

    if windows is None:
        windows = list(config.time_windows.all())

    tz = ZoneInfo(config.timezone)
    secret_bytes = settings.SECRET_KEY.encode()
    slot_ranges = _window_slot_ranges(windows, config.slot_duration_minutes)
    if not slot_ranges:
        return []

    blackout_days = _select_blackout_days(channel_idx, config, start_day, horizon_days, secret_bytes)

    out: list[BackendBusyPeriod] = []
    for day_offset in range(horizon_days):
        day = start_day + timedelta(days=day_offset)
        if config.weekdays_only and is_weekend(day):
            continue

        # Layer 3: full-day blackout — replaces slot-cluster generation for this day.
        if day in blackout_days:
            out.extend(_full_day_periods(day, windows, tz))
            continue

        # Layers 1 + 2: per-day deterministic RNG → weighted slot clusters.
        rng = random.Random(_seed_for_day(secret_bytes, channel_idx, day))  # noqa: S311  # cosmetic randomness, not security
        day_real_busy = [p for p in real_busy if p.start.date() <= day <= p.end.date()]
        real_busy_idx = _real_busy_slot_indices(day, day_real_busy, slot_ranges, config.slot_duration_minutes, tz)
        out.extend(_synthetic_clusters_for_day(rng, day, day_offset, real_busy_idx, slot_ranges, config, tz))

    return out


# ---------------------------------------------------------------------------
# Window indexing helpers
# ---------------------------------------------------------------------------


def _window_minute_count(window: BookingTimeWindow) -> int:
    """Length of one window in minutes."""
    return (window.end_time.hour * 60 + window.end_time.minute) - (
        window.start_time.hour * 60 + window.start_time.minute
    )


def _window_slot_count(window: BookingTimeWindow, slot_duration_minutes: int) -> int:
    """Number of full slots that fit inside one window."""
    return _window_minute_count(window) // slot_duration_minutes


def _window_slot_ranges(windows: list[BookingTimeWindow], slot_duration_minutes: int) -> list[_SlotRange]:
    """Return ``(start_idx, end_idx_exclusive, window)`` per BookingTimeWindow.

    Slot indices are cumulative across windows in the iteration order of the
    passed-in list. Windows that produce zero slots (too short for the configured
    slot_duration) are excluded.
    """
    cumulative = 0
    ranges: list[_SlotRange] = []
    for window in windows:
        win_slots = _window_slot_count(window, slot_duration_minutes)
        if win_slots <= 0:
            continue
        ranges.append((cumulative, cumulative + win_slots, window))
        cumulative += win_slots
    return ranges


def _slot_idx_to_window(idx: int, slot_ranges: list[_SlotRange]) -> tuple[BookingTimeWindow, int]:
    """Map global ``idx`` onto its owning ``(window, offset_within_window)``."""
    for start, end_exclusive, window in slot_ranges:
        if start <= idx < end_exclusive:
            return window, idx - start
    raise ValueError(f"slot_idx {idx} out of range for ranges {slot_ranges}")


# ---------------------------------------------------------------------------
# Layer 1: time-decay multiplier
# ---------------------------------------------------------------------------


def _multiplier_for_offset(day_offset: int) -> float:
    """Per-day intensity multiplier (urgency for near days, slack for far ones)."""
    if day_offset == 0:
        return _DECAY_TODAY
    if day_offset == 1:
        return _DECAY_TOMORROW
    if day_offset <= _DECAY_WEEK_THRESHOLD_DAYS:
        return _DECAY_WEEK
    return _DECAY_BEYOND


# ---------------------------------------------------------------------------
# Layer 2: slot-cluster generation
# ---------------------------------------------------------------------------


def _compute_target_synthetic_count(
    real_busy_idx: set[int], day_offset: int, slots_per_day: int, config: BookingConfig
) -> int:
    """How many additional synthetic slots this day needs.

    Always leaves at least one slot free per day — even at intensity 100 with the
    today multiplier, ceil(N × 80%) on small N can lock all slots and look like a
    closed business. The ``slots_per_day - 1`` clamp guarantees one bookable slot.
    """
    multiplier = _multiplier_for_offset(day_offset)
    effective_intensity = min(int(round(config.fomo_intensity * multiplier)), DAY_INTENSITY_CAP_PCT)
    target_busy = math.ceil(slots_per_day * effective_intensity / 100)
    target_busy = min(target_busy, slots_per_day - 1)  # ≥1 free always
    return max(0, target_busy - len(real_busy_idx))


def _synthetic_clusters_for_day(
    rng: random.Random,
    day: date,
    day_offset: int,
    real_busy_idx: set[int],
    slot_ranges: list[_SlotRange],
    config: BookingConfig,
    tz: ZoneInfo,
) -> list[BackendBusyPeriod]:
    """Generate clusters for one day (Layer 2 + Layer 1 cap applied)."""
    slots_per_day = sum(end - start for start, end, _ in slot_ranges)
    if slots_per_day <= 0:
        return []
    synthetic_target = _compute_target_synthetic_count(real_busy_idx, day_offset, slots_per_day, config)
    if synthetic_target <= 0:
        return []
    placements = _place_clusters(rng, real_busy_idx, synthetic_target, slot_ranges, slots_per_day, config)
    return [_build_period(day, pos, size, slot_ranges, config.slot_duration_minutes, tz) for pos, size in placements]


def _place_clusters(
    rng: random.Random,
    real_busy_idx: set[int],
    synthetic_target: int,
    slot_ranges: list[_SlotRange],
    slots_per_day: int,
    config: BookingConfig,
) -> list[tuple[int, int]]:
    """Pick (start_idx, size) tuples until quota is filled or attempts exhausted."""
    duration = config.slot_duration_minutes
    taken: set[int] = set(real_busy_idx)
    placements: list[tuple[int, int]] = []
    max_attempts = slots_per_day * _CLUSTER_ATTEMPT_MULTIPLIER

    for _ in range(max_attempts):
        synthetic_so_far = len(taken) - len(real_busy_idx)
        if synthetic_so_far >= synthetic_target:
            break
        placement = _place_one_cluster(rng, taken, synthetic_target - synthetic_so_far, slot_ranges, duration)
        if placement is None:
            continue
        pos, size = placement
        for k in range(size):
            taken.add(pos + k)
        placements.append(placement)

    return placements


def _place_one_cluster(
    rng: random.Random, taken: set[int], remaining_quota: int, slot_ranges: list[_SlotRange], slot_duration_minutes: int
) -> tuple[int, int] | None:
    """Pick a (start_idx, size) tuple for a new cluster; ``None`` if no room."""
    size = _select_cluster_size(rng)
    free_starts = _free_cluster_starts(taken, size, slot_ranges)
    if not free_starts:
        return None
    pos = _select_cluster_position(rng, free_starts, slot_ranges, slot_duration_minutes)
    actual_size = min(size, remaining_quota)
    return pos, actual_size


def _select_cluster_size(rng: random.Random) -> int:
    """Pick a cluster size weighted by ``CLUSTER_SIZE_WEIGHTS`` (60/30/10 for 2/3/4)."""
    sizes, weights = zip(*CLUSTER_SIZE_WEIGHTS, strict=True)
    return rng.choices(sizes, weights=weights, k=1)[0]


def _free_cluster_starts(taken: set[int], size: int, slot_ranges: list[_SlotRange]) -> list[int]:
    """Slot indices where ``size`` consecutive free slots fit inside a single window.

    By only enumerating starts within window boundaries, clusters can never
    straddle two windows.
    """
    result: list[int] = []
    for start, end_exclusive, _window in slot_ranges:
        for i in range(start, end_exclusive - size + 1):
            if all((i + k) not in taken for k in range(size)):
                result.append(i)
    return result


def _select_cluster_position(
    rng: random.Random, free_starts: list[int], slot_ranges: list[_SlotRange], slot_duration_minutes: int
) -> int:
    """Pick a cluster start position weighted by peak hours; fall back to uniform."""
    weights = [_peak_weight_for_slot(idx, slot_ranges, slot_duration_minutes) for idx in free_starts]
    if sum(weights) == 0:
        return rng.choice(free_starts)
    return rng.choices(free_starts, weights=weights, k=1)[0]


def _peak_weight_for_slot(slot_idx: int, slot_ranges: list[_SlotRange], slot_duration_minutes: int) -> float:
    """Peak-hour weight for placing a cluster starting at ``slot_idx``."""
    window, offset = _slot_idx_to_window(slot_idx, slot_ranges)
    minute_in_day = window.start_time.hour * 60 + window.start_time.minute + offset * slot_duration_minutes
    hour = minute_in_day // 60
    return _PEAK_HOUR_WEIGHTS.get(hour, 0.0)


# ---------------------------------------------------------------------------
# Layer 3: full-day blackout
# ---------------------------------------------------------------------------


def _select_blackout_days(
    channel_idx: str, config: BookingConfig, start_day: date, horizon_days: int, secret_bytes: bytes
) -> set[date]:
    """Pick which days (if any) get a full-day blackout. Today/tomorrow always excluded."""
    if config.fomo_blackout_full_days <= 0:
        return set()

    eligible: list[date] = []
    for offset in range(horizon_days):
        if offset < _BLACKOUT_MIN_OFFSET:
            continue
        candidate = start_day + timedelta(days=offset)
        if config.weekdays_only and is_weekend(candidate):
            continue
        eligible.append(candidate)

    if not eligible:
        return set()

    n_blackouts = min(config.fomo_blackout_full_days, len(eligible))
    rng_window = random.Random(_window_seed(secret_bytes, channel_idx, start_day, horizon_days))  # noqa: S311  # cosmetic randomness, not security
    return set(rng_window.sample(eligible, n_blackouts))


def _full_day_periods(day: date, windows: list[BookingTimeWindow], tz: ZoneInfo) -> list[BackendBusyPeriod]:
    """One ``BackendBusyPeriod`` per configured time window — covers the full work day."""
    return [
        BackendBusyPeriod(
            start=datetime.combine(day, w.start_time, tzinfo=tz), end=datetime.combine(day, w.end_time, tzinfo=tz)
        )
        for w in windows
    ]


# ---------------------------------------------------------------------------
# Helpers — seeding and period construction
# ---------------------------------------------------------------------------


def _seed_for_day(secret_bytes: bytes, channel_idx: str, day: date) -> bytes:
    """Per-day HMAC seed: stable within calendar day, rotates at midnight."""
    payload = f"fomo|{channel_idx}|{day.isoformat()}".encode()
    return hmac.new(secret_bytes, payload, hashlib.sha256).digest()


def _window_seed(secret_bytes: bytes, channel_idx: str, start_day: date, horizon_days: int) -> bytes:
    """Window-level HMAC seed for blackout day selection — stable across the visible window."""
    payload = f"fomo-blackout|{channel_idx}|{start_day.isoformat()}|{horizon_days}".encode()
    return hmac.new(secret_bytes, payload, hashlib.sha256).digest()


def _real_busy_slot_indices(
    day: date,
    day_real_busy: list[BackendBusyPeriod],
    slot_ranges: list[_SlotRange],
    slot_duration_minutes: int,
    tz: ZoneInfo,
) -> set[int]:
    """Index set of slots on ``day`` (across all windows) that overlap any real busy period."""
    busy: set[int] = set()
    for start_idx, _end_idx, window in slot_ranges:
        win_anchor = datetime.combine(day, window.start_time, tzinfo=tz)
        win_slots = _window_slot_count(window, slot_duration_minutes)
        for offset in range(win_slots):
            slot_start = win_anchor + timedelta(minutes=offset * slot_duration_minutes)
            slot_end = slot_start + timedelta(minutes=slot_duration_minutes)
            if _slot_overlaps_any(slot_start, slot_end, day_real_busy):
                busy.add(start_idx + offset)
    return busy


def _slot_overlaps_any(slot_start: datetime, slot_end: datetime, periods: list[BackendBusyPeriod]) -> bool:
    """True if [slot_start, slot_end) intersects any period in the list."""
    return any(p.start < slot_end and p.end > slot_start for p in periods)


def _build_period(
    day: date,
    slot_start_idx: int,
    slot_count: int,
    slot_ranges: list[_SlotRange],
    slot_duration_minutes: int,
    tz: ZoneInfo,
) -> BackendBusyPeriod:
    """Construct a ``BackendBusyPeriod`` of ``slot_count`` slots starting at ``slot_start_idx``.

    ``_free_cluster_starts`` guarantees the cluster fits in a single window, so
    the start window is sufficient to anchor the period.
    """
    window, offset = _slot_idx_to_window(slot_start_idx, slot_ranges)
    win_anchor = datetime.combine(day, window.start_time, tzinfo=tz)
    start_dt = win_anchor + timedelta(minutes=offset * slot_duration_minutes)
    end_dt = start_dt + timedelta(minutes=slot_count * slot_duration_minutes)
    return BackendBusyPeriod(start=start_dt, end=end_dt)
