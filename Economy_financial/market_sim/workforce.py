"""Employee trust, productivity and turnover for supervised firms.

All behavioural coefficients in this module are ``STYLIZATION`` values.
The legal reporting scope uses the rolling employee average maintained here;
the module does not turn behavioural parameters into legal thresholds.
"""

from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass, field
import math
import random
from typing import Any


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return min(upper, max(lower, float(value)))


@dataclass
class WorkforceState:
    employee_count: float
    trust: float = 0.80
    productivity_multiplier: float = 1.0
    annual_turnover_rate: float = 0.10
    cumulative_departures: float = 0.0
    vacancies: float = 0.0
    cumulative_hires: float = 0.0
    onboarding_employees: float = 0.0
    replacement_cost: float = 0.0
    last_internal_discrepancy: float = 0.0
    last_confirmed_abuse_day: int = -10**9
    productivity_loss_cap: float = 0.03
    base_annual_turnover: float = 0.10
    max_annual_turnover: float = 0.30
    onboarding_days: int = 30
    replacement_cost_per_employee: float = 250.0
    # Part J sensitivity levers (STYLIZATION; defaults preserve the
    # previous hard-coded behaviour): trust lost per unit of observable
    # discrepancy, the extra shock after a confirmed abuse decision, and
    # the daily recovery speed toward the 0.85 anchor.
    trust_loss_rate: float = 0.45
    abuse_trust_shock: float = 0.16
    trust_recovery_rate: float = 0.0015
    _headcount_history: deque = field(
        default_factory=lambda: deque(maxlen=365), repr=False)
    _onboarding_cohorts: deque = field(default_factory=deque, repr=False)

    def __post_init__(self) -> None:
        self.employee_count = max(0.0, float(self.employee_count))
        self.trust = _clamp(self.trust)
        if not self._headcount_history:
            self._headcount_history.append(self.employee_count)
        self._refresh_rates()

    @property
    def average_employees_365d(self) -> float:
        if not self._headcount_history:
            return self.employee_count
        return sum(self._headcount_history) / len(self._headcount_history)

    def observe_internal_signal(self, claimed_score: float,
                                internal_estimate: float,
                                signal_uncertainty: float,
                                confirmed_abuse: bool = False,
                                current_day: int = 0) -> None:
        """Update trust from information employees could plausibly observe."""
        discrepancy = max(0.0, float(claimed_score)
                          - float(internal_estimate)
                          - max(0.0, float(signal_uncertainty)))
        self.last_internal_discrepancy = discrepancy
        shock = min(0.30, self.trust_loss_rate * discrepancy)
        if confirmed_abuse:
            shock += self.abuse_trust_shock
            self.last_confirmed_abuse_day = current_day
        if shock > 0.0:
            self.trust = _clamp(self.trust - shock)
        else:
            # Recovery is intentionally slower than loss.
            self.trust = _clamp(self.trust + self.trust_recovery_rate
                                * (0.85 - self.trust))
        self._refresh_rates(current_day)

    def daily_step(self, rng: random.Random, current_day: int,
                   hiring_capacity: float | None = None) -> dict[str, float]:
        """Advance departures, vacancies, hiring and onboarding by one day."""
        self._complete_onboarding(current_day)
        self._refresh_rates(current_day)
        daily_hazard = 1.0 - (1.0 - self.annual_turnover_rate) ** (1.0 / 365.0)
        expected_departures = self.employee_count * daily_hazard
        # Gaussian approximation is stable for large simulated workforces.
        variation = rng.gauss(0.0, math.sqrt(max(expected_departures, 1e-9)))
        departures = min(self.employee_count,
                         max(0.0, expected_departures + variation))
        self.employee_count -= departures
        self.cumulative_departures += departures
        self.vacancies += departures

        capacity = max(0.0, float(hiring_capacity)) if hiring_capacity \
            is not None else max(1.0, 0.02 * max(self.employee_count, 1.0))
        hires = min(self.vacancies, capacity)
        if hires > 0.0:
            self.vacancies -= hires
            self.onboarding_employees += hires
            self.cumulative_hires += hires
            self.replacement_cost += hires * self.replacement_cost_per_employee
            self._onboarding_cohorts.append((current_day + self.onboarding_days,
                                             hires))
        self._headcount_history.append(self.employee_count
                                       + self.onboarding_employees)
        return {"departures": departures, "hires": hires,
                "replacement_cost": hires * self.replacement_cost_per_employee}

    def _complete_onboarding(self, current_day: int) -> None:
        while self._onboarding_cohorts \
                and self._onboarding_cohorts[0][0] <= current_day:
            _, hires = self._onboarding_cohorts.popleft()
            hires = min(hires, self.onboarding_employees)
            self.onboarding_employees -= hires
            self.employee_count += hires

    def _refresh_rates(self, current_day: int | None = None) -> None:
        self.productivity_multiplier = 1.0 - self.productivity_loss_cap \
            * (1.0 - self.trust)
        controversy = 0.04 if (current_day is not None
                               and current_day - self.last_confirmed_abuse_day
                               <= 365) else 0.0
        self.annual_turnover_rate = min(
            self.max_annual_turnover,
            self.base_annual_turnover + 0.15 * (1.0 - self.trust) + controversy)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result.pop("_headcount_history", None)
        result.pop("_onboarding_cohorts", None)
        result["average_employees_365d"] = self.average_employees_365d
        return result
