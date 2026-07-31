# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Tests for the FOMO synthetic busy slot generator.

Covers all three layers (time-decay, cluster generation, day blackout), plus the
critical guarantee that synthetic intervals never block a real booking — they
filter visibility only.
"""

from datetime import date, datetime, time, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from django_contact_forms.services.booking_service import get_available_slots
from django_contact_forms.services.calendar.backends.base import BackendBusyPeriod
from django_contact_forms.services.calendar.fomo import (
    _PEAK_HOUR_WEIGHTS,
    DAY_INTENSITY_CAP_PCT,
    generate_synthetic_busy_periods,
)
from tests.factories import BookingConfigFactory, enable_global_settings

TZ = ZoneInfo("Europe/Warsaw")


def _next_monday(today: date | None = None) -> date:
    """Return the nearest Monday on or after the given date.

    Anchors test windows to a known weekday so weekday/weekend logic is predictable
    regardless of when the suite runs.
    """
    today = today or date.today()
    return today + timedelta(days=(7 - today.weekday()) % 7 or 0)


def _make_config(**overrides):
    enable_global_settings(bookings=True)
    cfg = BookingConfigFactory(**overrides)
    return cfg


def _workday_total_minutes(cfg) -> int:
    """Sum of all configured time windows in minutes (replaces legacy `end_hour - start_hour` math)."""
    return sum(
        (w.end_time.hour * 60 + w.end_time.minute) - (w.start_time.hour * 60 + w.start_time.minute)
        for w in cfg.time_windows.all()
    )


def _earliest_window_start(cfg):
    """First window's start_time — proxy for legacy ``_earliest_window_start(cfg)``."""
    return cfg.time_windows.first().start_time


def _latest_window_end(cfg):
    """Last window's end_time — proxy for legacy ``_latest_window_end(cfg)``."""
    return cfg.time_windows.order_by("-end_time").first().end_time


# ---------------------------------------------------------------------------
# 1. Disabled / off
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestFomoDisabled:
    def test_fomo_disabled_returns_empty(self):
        cfg = _make_config(fomo_enabled=False, fomo_intensity=80)
        result = generate_synthetic_busy_periods(
            channel_idx=cfg.channel.idx, config=cfg, real_busy=[], start_day=_next_monday(), horizon_days=14
        )
        assert result == []

    def test_fomo_intensity_zero_returns_empty(self):
        cfg = _make_config(fomo_enabled=True, fomo_intensity=0)
        result = generate_synthetic_busy_periods(
            channel_idx=cfg.channel.idx, config=cfg, real_busy=[], start_day=_next_monday(), horizon_days=14
        )
        assert result == []

    def test_horizon_zero_returns_empty(self):
        cfg = _make_config(fomo_enabled=True, fomo_intensity=80)
        result = generate_synthetic_busy_periods(
            channel_idx=cfg.channel.idx, config=cfg, real_busy=[], start_day=_next_monday(), horizon_days=0
        )
        assert result == []


# ---------------------------------------------------------------------------
# 2. Determinism
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestFomoDeterminism:
    def test_same_inputs_same_output(self):
        cfg = _make_config(fomo_enabled=True, fomo_intensity=60)
        start = _next_monday()
        first = generate_synthetic_busy_periods(
            channel_idx=cfg.channel.idx, config=cfg, real_busy=[], start_day=start, horizon_days=14
        )
        second = generate_synthetic_busy_periods(
            channel_idx=cfg.channel.idx, config=cfg, real_busy=[], start_day=start, horizon_days=14
        )
        assert first == second

    def test_different_days_yield_different_layouts(self):
        """Different start_days must seed different RNG → different cluster layouts.

        Pin the start_day to a known Monday and sample 7 consecutive starts; with HMAC
        seeding, getting the same layout on multiple days requires SHA-256 collisions —
        so the unique-layout count is 7 in practice, never 1.
        """
        cfg = _make_config(fomo_enabled=True, fomo_intensity=60, fomo_blackout_full_days=0)
        anchor = date(2026, 1, 5)  # known Monday — independent of when suite runs
        layouts: set[tuple] = set()
        for offset in range(7):
            periods = generate_synthetic_busy_periods(
                channel_idx=cfg.channel.idx,
                config=cfg,
                real_busy=[],
                start_day=anchor + timedelta(days=offset),
                horizon_days=1,
            )
            layouts.add(tuple((p.start.isoformat(), p.end.isoformat()) for p in periods))
        # Tolerate up to one accidental coincidence; demand strict variety.
        assert len(layouts) >= 6, f"Expected 6-7 unique layouts across 7 days; got {len(layouts)}"


# ---------------------------------------------------------------------------
# 3. Day blackouts
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestFomoBlackouts:
    def test_today_and_tomorrow_never_blackout(self):
        cfg = _make_config(fomo_enabled=True, fomo_intensity=100, fomo_blackout_full_days=3)
        start = _next_monday()
        periods = generate_synthetic_busy_periods(
            channel_idx=cfg.channel.idx, config=cfg, real_busy=[], start_day=start, horizon_days=14
        )
        # A blackout period spans the full work day (start_hour..end_hour).
        full_day_durations = [p for p in periods if (p.end - p.start) == timedelta(minutes=_workday_total_minutes(cfg))]
        for p in full_day_durations:
            assert p.start.date() not in (start, start + timedelta(days=1)), (
                f"day {p.start.date()} is today/tomorrow but got a full-day blackout"
            )

    def test_blackout_count_capped_at_config(self):
        cfg = _make_config(fomo_enabled=True, fomo_intensity=100, fomo_blackout_full_days=2, weekdays_only=False)
        start = _next_monday()
        periods = generate_synthetic_busy_periods(
            channel_idx=cfg.channel.idx, config=cfg, real_busy=[], start_day=start, horizon_days=14
        )
        full_day_periods = [p for p in periods if (p.end - p.start) == timedelta(minutes=_workday_total_minutes(cfg))]
        assert len(full_day_periods) <= 2

    def test_zero_blackouts_means_no_full_day_periods(self):
        cfg = _make_config(fomo_enabled=True, fomo_intensity=100, fomo_blackout_full_days=0)
        start = _next_monday()
        periods = generate_synthetic_busy_periods(
            channel_idx=cfg.channel.idx, config=cfg, real_busy=[], start_day=start, horizon_days=14
        )
        for p in periods:
            assert (p.end - p.start) < timedelta(minutes=_workday_total_minutes(cfg))


# ---------------------------------------------------------------------------
# 4. Per-day intensity cap
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestFomoIntensityCap:
    def test_intensity_100_capped_at_day_cap(self):
        """Even with intensity=100 + 1.5x today multiplier, no day exceeds DAY_INTENSITY_CAP_PCT busy slots."""
        cfg = _make_config(fomo_enabled=True, fomo_intensity=100, fomo_blackout_full_days=0)
        start = _next_monday()
        periods = generate_synthetic_busy_periods(
            channel_idx=cfg.channel.idx, config=cfg, real_busy=[], start_day=start, horizon_days=14
        )
        slots_per_day = _workday_total_minutes(cfg) // cfg.slot_duration_minutes
        # Cap: ceil(slots × cap%), but never the whole day — at least one slot stays free.
        max_busy_slots = min((DAY_INTENSITY_CAP_PCT * slots_per_day + 99) // 100, slots_per_day - 1)

        # Group by day, count synthetic slots per day, assert ≤ cap.
        per_day: dict[date, int] = {}
        for p in periods:
            duration_min = int((p.end - p.start).total_seconds() // 60)
            count = duration_min // cfg.slot_duration_minutes
            per_day[p.start.date()] = per_day.get(p.start.date(), 0) + count
        for day, count in per_day.items():
            assert count <= max_busy_slots, f"day {day} has {count} busy slots, cap is {max_busy_slots}"


# ---------------------------------------------------------------------------
# 5. Real busy interaction
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestFomoRealBusyInteraction:
    def test_real_busy_subtracts_from_synthetic_target(self):
        """When real busy already exceeds target, no synthetic should be added."""
        cfg = _make_config(fomo_enabled=True, fomo_intensity=30, fomo_blackout_full_days=0)
        start = _next_monday()
        # Fill a full work day with real busy → 100% real-busy → target reached
        real_busy = [
            BackendBusyPeriod(
                start=datetime.combine(start, _earliest_window_start(cfg), tzinfo=TZ),
                end=datetime.combine(start, _latest_window_end(cfg), tzinfo=TZ),
            )
        ]
        periods = generate_synthetic_busy_periods(
            channel_idx=cfg.channel.idx, config=cfg, real_busy=real_busy, start_day=start, horizon_days=1
        )
        assert periods == []

    def test_synthetic_does_not_overlap_real_busy(self):
        cfg = _make_config(fomo_enabled=True, fomo_intensity=80, fomo_blackout_full_days=0)
        start = _next_monday()
        real_busy = [
            BackendBusyPeriod(
                start=datetime.combine(start, time(10, 0), tzinfo=TZ),
                end=datetime.combine(start, time(11, 0), tzinfo=TZ),
            )
        ]
        periods = generate_synthetic_busy_periods(
            channel_idx=cfg.channel.idx, config=cfg, real_busy=real_busy, start_day=start, horizon_days=1
        )
        for p in periods:
            assert not (p.start < real_busy[0].end and p.end > real_busy[0].start), (
                f"synthetic {p} overlaps real {real_busy[0]}"
            )


# ---------------------------------------------------------------------------
# 6. Weekday respect
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestFomoWeekdayRespect:
    def test_weekdays_only_skips_weekends(self):
        cfg = _make_config(fomo_enabled=True, fomo_intensity=100, weekdays_only=True, fomo_blackout_full_days=0)
        # Anchor to a Friday so the window crosses a weekend
        today = date.today()
        friday = today + timedelta(days=(4 - today.weekday()) % 7 or 7)
        periods = generate_synthetic_busy_periods(
            channel_idx=cfg.channel.idx, config=cfg, real_busy=[], start_day=friday, horizon_days=7
        )
        for p in periods:
            assert p.start.weekday() < 5, f"got synthetic on weekend day {p.start.date()}"

    def test_weekdays_only_false_includes_weekends(self):
        """Inverse of the above — when weekends are allowed, synthetic must reach them."""
        cfg = _make_config(fomo_enabled=True, fomo_intensity=80, weekdays_only=False, fomo_blackout_full_days=0)
        # Anchor to a Saturday so day 0 is the weekend itself.
        today = date.today()
        saturday = today + timedelta(days=(5 - today.weekday()) % 7 or 7)
        periods = generate_synthetic_busy_periods(
            channel_idx=cfg.channel.idx, config=cfg, real_busy=[], start_day=saturday, horizon_days=1
        )
        assert periods, "weekdays_only=False on a Saturday should still produce synthetic slots"
        assert all(p.start.date() == saturday for p in periods)


# ---------------------------------------------------------------------------
# 7. Public-API integration: synthetic appears as available=False, never as real-busy leak
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestFomoIntegration:
    @patch("django_contact_forms.services.booking_service.get_calendar_backend")
    def test_get_available_slots_includes_synthetic_busy(self, mock_factory):
        cfg = _make_config(fomo_enabled=True, fomo_intensity=80, fomo_blackout_full_days=0, weekdays_only=False)
        mock_backend = mock_factory.return_value
        mock_backend.get_busy_periods.return_value = []

        result = get_available_slots(channel=cfg.channel, days=7)
        # At intensity 80 across 7 days the vast majority of days must show synthetic load.
        days_with_busy = sum(1 for d in result if any(not s.available for s in d.slots))
        assert days_with_busy >= 5, f"FOMO at 80% over 7 days should mark ≥5 days as busy; got {days_with_busy}"

    @patch("django_contact_forms.services.booking_service.get_calendar_backend")
    def test_response_slot_shape_unchanged_by_fomo(self, mock_factory):
        cfg = _make_config(fomo_enabled=True, fomo_intensity=80)
        mock_factory.return_value.get_busy_periods.return_value = []

        result = get_available_slots(channel=cfg.channel, days=3)
        for day in result:
            for slot in day.slots:
                # No 'synthetic' attribute should leak — only the binary available flag.
                assert hasattr(slot, "available")
                assert not hasattr(slot, "synthetic")
                assert isinstance(slot.available, bool)


# ---------------------------------------------------------------------------
# 8. is_slot_free is unaffected — synthetic never blocks a real booking
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestFomoDoesNotBlockRealBooking:
    """Verify the architectural invariant: synthetic intervals are never consulted in the
    booking creation path. ``create_booking`` calls only ``backend.is_slot_free``; the FOMO
    module is reached only from ``get_available_slots``."""

    @patch("django_contact_forms.services.booking_service.generate_synthetic_busy_periods")
    @patch("django_contact_forms.services.booking_service.get_calendar_backend")
    def test_create_booking_does_not_invoke_fomo(self, mock_factory, mock_fomo):
        from django_contact_forms.services import booking_service

        cfg = _make_config(fomo_enabled=True, fomo_intensity=100)
        mock_backend = mock_factory.return_value
        mock_backend.is_slot_free.return_value = True
        mock_backend.create_event.return_value = type(
            "Evt", (), {"event_id": "ev-1", "meet_link": "https://m.test/x"}
        )()

        # Pick a future weekday slot that is in the business window.
        now = datetime.now(TZ)
        booking_dt = (now + timedelta(days=2)).replace(hour=10, minute=0, second=0, microsecond=0)
        while booking_dt.weekday() >= 5:
            booking_dt += timedelta(days=1)

        req = booking_service.BookingRequest(
            booking_date=booking_dt.date(), booking_time=time(10, 0), name="Test", email="test@example.com"
        )
        booking_service.create_booking(channel=cfg.channel, request=req)

        # The is_slot_free guard must run; the synthetic generator must NOT.
        mock_backend.is_slot_free.assert_called_once()
        mock_fomo.assert_not_called()


# ---------------------------------------------------------------------------
# 9. Peak-hour weighting (statistical assertion)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestFomoPeakHourWeighting:
    def test_peak_hours_get_more_synthetic_density(self):
        """Aggregate synthetic load across many days; peak hours should be more occupied
        than off-peak hours (statistical, not strict per-day)."""
        cfg = _make_config(fomo_enabled=True, fomo_intensity=50, fomo_blackout_full_days=0, weekdays_only=False)
        # Pin to a known Monday so the 30-day sample is identical regardless of suite run date.
        start = date(2026, 1, 5)
        all_periods = []
        for offset in range(30):
            day_periods = generate_synthetic_busy_periods(
                channel_idx=cfg.channel.idx,
                config=cfg,
                real_busy=[],
                start_day=start + timedelta(days=offset),
                horizon_days=1,
            )
            all_periods.extend(day_periods)

        # Count busy slot-minutes per starting hour
        hour_load: dict[int, int] = {}
        for p in all_periods:
            duration_min = int((p.end - p.start).total_seconds() // 60)
            hour_load[p.start.hour] = hour_load.get(p.start.hour, 0) + duration_min

        peak_hours = [h for h, w in _PEAK_HOUR_WEIGHTS.items() if w >= 1.0]
        off_peak_hours = [h for h, w in _PEAK_HOUR_WEIGHTS.items() if w < 0.5]

        peak_load = sum(hour_load.get(h, 0) for h in peak_hours)
        off_peak_load = sum(hour_load.get(h, 0) for h in off_peak_hours)

        # Peak load should clearly outweigh off-peak. With 0.4 vs 1.0 weights and ~3 peak
        # hours vs 2 off-peak, expect at least 2:1 ratio over the sample.
        assert peak_load > off_peak_load * 2, f"peak ({peak_load} min) should be >2x off-peak ({off_peak_load} min)"


# ---------------------------------------------------------------------------
# 10. Time-decay multipliers (today/tomorrow get more synthetic than far days)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestFomoTimeDecay:
    def test_today_busier_than_far_future(self):
        """Time-decay multiplier means day_offset=0 gets ~1.5x the intensity of days 7+.

        Day_offset is relative to start_day, so we run a single horizon-9 call and
        compare the offset-0 day's load with the offset-8 day's load. With intensity=40,
        effective today = ceil(16 * min(40 * 1.5, 80) / 100) = 10 slots; effective day-8
        = ceil(16 * 30 / 100) = 5 slots; so today should produce strictly more synthetic
        minutes than day 8.
        """
        cfg = _make_config(fomo_enabled=True, fomo_intensity=40, fomo_blackout_full_days=0, weekdays_only=False)
        anchor = date(2026, 1, 5)  # known Monday — independent of when suite runs

        periods = generate_synthetic_busy_periods(
            channel_idx=cfg.channel.idx, config=cfg, real_busy=[], start_day=anchor, horizon_days=9
        )
        per_day: dict[date, int] = {}
        for p in periods:
            duration_min = int((p.end - p.start).total_seconds() // 60)
            per_day[p.start.date()] = per_day.get(p.start.date(), 0) + duration_min

        today_minutes = per_day.get(anchor, 0)
        far_minutes = per_day.get(anchor + timedelta(days=8), 0)
        assert today_minutes > far_minutes, (
            f"day 0 should have more synthetic load than day 8: today={today_minutes} far={far_minutes}"
        )


# ---------------------------------------------------------------------------
# 11. Cluster size distribution (60% × 2-slot, 30% × 3-slot, 10% × 4-slot)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestFomoClusterSizeDistribution:
    def test_2_slot_clusters_outnumber_3_outnumber_4(self):
        """Verify 60/30/10 weights produce 2-slot > 3-slot > 4-slot in aggregate.

        Sample 30 days; count clusters by duration. With deterministic seeding the
        result is identical across runs; the bands are wide enough to tolerate the
        natural variance from peak-hour position weighting.
        """
        cfg = _make_config(fomo_enabled=True, fomo_intensity=60, fomo_blackout_full_days=0, weekdays_only=False)
        anchor = date(2026, 1, 5)
        size_counts = {2: 0, 3: 0, 4: 0}
        for offset in range(30):
            periods = generate_synthetic_busy_periods(
                channel_idx=cfg.channel.idx,
                config=cfg,
                real_busy=[],
                start_day=anchor + timedelta(days=offset),
                horizon_days=1,
            )
            for p in periods:
                slot_count = int((p.end - p.start).total_seconds() // 60) // cfg.slot_duration_minutes
                if slot_count in size_counts:
                    size_counts[slot_count] += 1
        assert size_counts[2] > size_counts[3], f"2-slot should outnumber 3-slot: {size_counts}"
        assert size_counts[3] > size_counts[4], f"3-slot should outnumber 4-slot: {size_counts}"


# ---------------------------------------------------------------------------
# 12. BookingConfig field validators (intensity ≤ 100, blackouts ≤ 3)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestBookingConfigFomoValidators:
    def test_intensity_above_100_raises_validation_error(self):
        from django.core.exceptions import ValidationError

        cfg = _make_config(fomo_intensity=101)
        with pytest.raises(ValidationError) as ctx:
            cfg.full_clean()
        assert "fomo_intensity" in ctx.value.message_dict

    def test_blackout_full_days_above_3_raises_validation_error(self):
        from django.core.exceptions import ValidationError

        cfg = _make_config(fomo_blackout_full_days=4)
        with pytest.raises(ValidationError) as ctx:
            cfg.full_clean()
        assert "fomo_blackout_full_days" in ctx.value.message_dict


# ---------------------------------------------------------------------------
# 13. Edge cases: short horizons + horizon=2 + blackout count cannot exceed eligibility
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestFomoHorizonEdges:
    def test_horizon_2_with_blackouts_still_no_blackout_periods(self):
        """horizon=2 means only days 0 and 1 in scope, both excluded from blackouts."""
        cfg = _make_config(fomo_enabled=True, fomo_intensity=100, fomo_blackout_full_days=3, weekdays_only=False)
        anchor = date(2026, 1, 5)
        periods = generate_synthetic_busy_periods(
            channel_idx=cfg.channel.idx, config=cfg, real_busy=[], start_day=anchor, horizon_days=2
        )
        # No full-day blackout periods (full_day_duration = end_hour - start_hour hours).
        full_day = timedelta(minutes=_workday_total_minutes(cfg))
        full_day_periods = [p for p in periods if (p.end - p.start) == full_day]
        assert full_day_periods == [], "horizon=2 leaves no eligible day for full-day blackout"

    def test_horizon_1_returns_synthetic_only_for_today(self):
        cfg = _make_config(fomo_enabled=True, fomo_intensity=80, fomo_blackout_full_days=2, weekdays_only=False)
        anchor = date(2026, 1, 5)
        periods = generate_synthetic_busy_periods(
            channel_idx=cfg.channel.idx, config=cfg, real_busy=[], start_day=anchor, horizon_days=1
        )
        for p in periods:
            assert p.start.date() == anchor, "horizon=1 must produce only day-0 periods"


# ---------------------------------------------------------------------------
# 14. Multi-window support — slots and clusters distributed across windows
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestFomoMultiWindow:
    def test_synthetic_distributed_across_two_windows(self):
        """With morning + afternoon windows, FOMO produces synthetic in both — not just one."""
        cfg = _make_config(
            fomo_enabled=True,
            fomo_intensity=80,
            fomo_blackout_full_days=0,
            weekdays_only=False,
            slot_duration_minutes=30,
            time_windows=[
                {"start_time": time(10, 0), "end_time": time(12, 0)},  # 4 slots
                {"start_time": time(15, 0), "end_time": time(17, 0)},  # 4 slots
            ],
        )
        anchor = date(2026, 1, 5)
        periods = generate_synthetic_busy_periods(
            channel_idx=cfg.channel.idx, config=cfg, real_busy=[], start_day=anchor, horizon_days=1
        )
        morning = [p for p in periods if p.start.hour < 12]
        afternoon = [p for p in periods if p.start.hour >= 12]
        # At intensity 80 across 8 slots → cap @ 6 busy slots → at least one in each window.
        assert morning, f"expected synthetic in morning window, got: {periods}"
        assert afternoon, f"expected synthetic in afternoon window, got: {periods}"

    def test_cluster_does_not_span_two_windows(self):
        """Clusters are constrained per-window — no synthetic period bridges a gap."""
        cfg = _make_config(
            fomo_enabled=True,
            fomo_intensity=100,
            fomo_blackout_full_days=0,
            weekdays_only=False,
            slot_duration_minutes=30,
            time_windows=[
                {"start_time": time(10, 0), "end_time": time(11, 30)},  # 3 slots — small window
                {"start_time": time(15, 0), "end_time": time(16, 30)},  # 3 slots
            ],
        )
        anchor = date(2026, 1, 5)
        periods = generate_synthetic_busy_periods(
            channel_idx=cfg.channel.idx, config=cfg, real_busy=[], start_day=anchor, horizon_days=1
        )
        # Every period must lie entirely within a single configured window.
        for p in periods:
            in_window = (p.start.time() >= time(10, 0) and p.end.time() <= time(11, 30)) or (
                p.start.time() >= time(15, 0) and p.end.time() <= time(16, 30)
            )
            assert in_window, f"period {p} bridges two windows"

    def test_blackout_emits_one_period_per_window(self):
        """Full-day blackout produces one BackendBusyPeriod per configured window (not one big span)."""
        cfg = _make_config(
            fomo_enabled=True,
            fomo_intensity=100,
            fomo_blackout_full_days=3,
            weekdays_only=False,
            time_windows=[
                {"start_time": time(10, 0), "end_time": time(12, 0)},
                {"start_time": time(15, 0), "end_time": time(17, 0)},
            ],
        )
        anchor = date(2026, 1, 5)
        periods = generate_synthetic_busy_periods(
            channel_idx=cfg.channel.idx, config=cfg, real_busy=[], start_day=anchor, horizon_days=14
        )
        # Find a blackout day: a day where total synthetic periods cover both windows entirely.
        morning_full = timedelta(hours=2)
        blackout_days = set()
        for p in periods:
            if p.start.time() == time(10, 0) and (p.end - p.start) == morning_full:
                blackout_days.add(p.start.date())
        # At least one blackout day exists per config (3 max, 12 eligible).
        assert blackout_days, "expected at least one blackout day with full morning window covered"

    def test_no_windows_returns_empty(self):
        """A config with no time_windows produces zero synthetic periods (defensive)."""
        cfg = _make_config(fomo_enabled=True, fomo_intensity=80)
        cfg.time_windows.all().delete()
        result = generate_synthetic_busy_periods(
            channel_idx=cfg.channel.idx, config=cfg, real_busy=[], start_day=_next_monday(), horizon_days=14
        )
        assert result == []


# ---------------------------------------------------------------------------
# 15. Service-layer integration: get_available_slots respects multi-window config
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSlotsForDayMultiWindow:
    @patch("django_contact_forms.services.booking_service.get_calendar_backend")
    def test_get_available_slots_emits_slots_from_both_windows(self, mock_factory):
        cfg = _make_config(
            slot_duration_minutes=45,
            weekdays_only=False,
            time_windows=[
                {"start_time": time(10, 0), "end_time": time(12, 30)},  # 3 × 45min slots
                {"start_time": time(16, 0), "end_time": time(17, 0)},  # 1 × 45min slot
            ],
        )
        mock_factory.return_value.get_busy_periods.return_value = []
        result = get_available_slots(channel=cfg.channel, days=1)

        day_slots = result[0].slots
        # 3 morning slots + 1 afternoon slot = 4 total.
        assert len(day_slots) == 4
        morning_starts = [s.start for s in day_slots if s.start < time(13, 0)]
        afternoon_starts = [s.start for s in day_slots if s.start >= time(13, 0)]
        assert morning_starts == [time(10, 0), time(10, 45), time(11, 30)]
        assert afternoon_starts == [time(16, 0)]

    @patch("django_contact_forms.services.booking_service.get_calendar_backend")
    def test_no_windows_returns_empty(self, mock_factory):
        cfg = _make_config()
        cfg.time_windows.all().delete()
        mock_factory.return_value.get_busy_periods.return_value = []
        result = get_available_slots(channel=cfg.channel, days=1)
        assert result == []


# ---------------------------------------------------------------------------
# Edge cases — slot index math + intensity input domain + inter-window busy
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSlotIdxToWindow:
    """``_slot_idx_to_window`` must raise ValueError for indices past the grid."""

    def test_raises_for_out_of_range_idx(self):
        from django_contact_forms.services.calendar.fomo import _slot_idx_to_window, _window_slot_ranges

        cfg = _make_config(
            slot_duration_minutes=30,
            time_windows=[
                {"order": 0, "start_time": time(10, 0), "end_time": time(11, 0)},  # 2 slots: 0-1
                {"order": 1, "start_time": time(14, 0), "end_time": time(15, 0)},  # 2 slots: 2-3
            ],
        )
        ranges = _window_slot_ranges(list(cfg.time_windows.all()), 30)
        with pytest.raises(ValueError, match="out of range"):
            _slot_idx_to_window(4, ranges)

    def test_resolves_secondary_window_offset(self):
        from django_contact_forms.services.calendar.fomo import _slot_idx_to_window, _window_slot_ranges

        cfg = _make_config(
            slot_duration_minutes=30,
            time_windows=[
                {"order": 0, "start_time": time(10, 0), "end_time": time(11, 0)},
                {"order": 1, "start_time": time(14, 0), "end_time": time(15, 0)},
            ],
        )
        ranges = _window_slot_ranges(list(cfg.time_windows.all()), 30)
        # idx=2 is first slot of second window
        window, offset = _slot_idx_to_window(2, ranges)
        assert window.start_time == time(14, 0)
        assert offset == 0
        # idx=3 is second slot of second window
        window, offset = _slot_idx_to_window(3, ranges)
        assert offset == 1


class TestFomoIntensityInputDomain:
    """``fomo_intensity`` is bounded by validators 0..100; the model raises
    on negative values via ``MinValueValidator``."""

    @pytest.mark.django_db
    def test_negative_intensity_raises_validation_error(self):
        from django.core.exceptions import ValidationError

        cfg = _make_config(fomo_enabled=True, fomo_intensity=50)
        cfg.fomo_intensity = -1
        with pytest.raises(ValidationError):
            cfg.full_clean()

    @pytest.mark.django_db
    def test_intensity_above_100_raises_validation_error(self):
        from django.core.exceptions import ValidationError

        cfg = _make_config(fomo_enabled=True, fomo_intensity=50)
        cfg.fomo_intensity = 101
        with pytest.raises(ValidationError):
            cfg.full_clean()


@pytest.mark.django_db
class TestFomoInterWindowBusy:
    """Real busy events that span the gap between two windows must not crash
    slot generation and must not produce synthetic that clobbers real events."""

    @patch("django_contact_forms.services.booking_service.get_calendar_backend")
    def test_busy_in_between_windows_does_not_create_synthetic_in_gap(self, mock_factory):
        cfg = _make_config(
            slot_duration_minutes=30,
            fomo_enabled=True,
            fomo_intensity=80,
            time_windows=[
                {"order": 0, "start_time": time(10, 0), "end_time": time(12, 0)},
                {"order": 1, "start_time": time(14, 0), "end_time": time(16, 0)},
            ],
        )
        # A real busy event entirely in the gap (12:00-14:00) — outside any window.
        # The FOMO logic must not bookkeep it as occupying a slot.
        anchor = _next_monday()
        gap_busy = [
            BackendBusyPeriod(
                start=datetime.combine(anchor, time(12, 30), tzinfo=TZ),
                end=datetime.combine(anchor, time(13, 30), tzinfo=TZ),
            )
        ]
        mock_factory.return_value.get_busy_periods.return_value = gap_busy

        # Should not raise — confirms slot index math handles inter-window busy gracefully.
        result = get_available_slots(channel=cfg.channel, date_from=anchor, days=1)
        assert len(result) == 1
        # All slots should be either fully free or fully busy — no slot starts
        # in the 12:00-14:00 gap because that range is not in any window.
        for s in result[0].slots:
            assert s.start < time(12, 0) or s.start >= time(14, 0)
