"""EU legal calendar plus the retained legacy Part-G policy object.

``LegalRegime`` is the calendar-aware source used by the opt-in prevention
system.  It keeps UCPD consumer law, Directive (EU) 2024/825, CSRD reporting,
financial-market communications and CSDDD due diligence on distinct tracks.
It applies the amended CSRD scope through explicit turnover *and* employee
thresholds.

``ESGRegulation`` remains for compatibility with the original model's green
capital, green-bond and reserve experiments.  Its audit lottery and 3% proxy
penalty are legacy mechanics only and are bypassed when
``enable_greenwashing_supervision`` is active.  The new supervisor provides
limited assurance to every mandatory report and never uses the CSDDD 3%
ceiling for an ordinary greenwashing claim.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_DOWN, Decimal
from typing import Optional

from market_sim.environmental_claims import FirmProfile, RuleAuthority

from market_sim.constants import (
    CREDIT_CENT_DEC,
    GREEN_BOND_OMEGA,
    GREEN_RISK_WEIGHT_DISCOUNT,
    INSTITUTIONS_USE_CREDIBILITY,
    OMEGA_MIN,
    REG_AUDIT_PROBABILITY,
    REG_DETECT_MIDPOINT,
    REG_DETECT_STEEPNESS,
    REG_ENFORCEMENT_START_DAY,
    REG_GREEN_BONDS_ALLOWED,
    REG_MANDATORY_SIZE_THRESHOLD,
    REG_OMISSION_RATE_DEFAULT,
    REG_PENALTY_RATE_DEC,
    REG_REPORTING_PERIOD_DAYS,
    REG_TRANSITION_PLANS_MANDATORY,
    REG_TURNOVER_BALANCE_MULTIPLE_DEC,
    REG_WEDGE_TOLERANCE,
    RESERVE_BASE_RATIO,
)

_ZERO = Decimal("0")


@dataclass(frozen=True)
class LegalRegime:
    """Calendar and scope rules for the opt-in EU supervision model.

    Dates are application dates in the model, not claims that every Member
    State will implement procedures identically.  ``csrd_new_scope_date`` is
    therefore injectable for national-transposition scenarios.
    """

    simulation_start_date: date = date(2026, 1, 1)
    empowering_consumers_application_date: date = date(2026, 9, 27)
    csrd_new_scope_date: date = date(2027, 3, 19)
    csddd_application_date: date = date(2029, 7, 26)
    green_claims_preverification_enabled: bool = False
    csrd_turnover_threshold: float = 450_000_000.0
    csrd_employee_threshold: float = 1000.0

    def date_for_day(self, day: int) -> date:
        """Map simulation day 1 to ``simulation_start_date``."""
        return self.simulation_start_date + timedelta(days=max(0, day - 1))

    def ucpd_active(self, on_date: date) -> bool:
        # The base UCPD is part of the background law throughout the model.
        return True

    def empowering_consumers_active(self, on_date: date) -> bool:
        return on_date >= self.empowering_consumers_application_date

    def csrd_active(self, on_date: date) -> bool:
        return on_date >= self.csrd_new_scope_date

    def csddd_active(self, on_date: date) -> bool:
        return on_date >= self.csddd_application_date

    def green_claims_preverification_active(self, on_date: date) -> bool:
        return bool(self.green_claims_preverification_enabled)

    def csrd_in_scope(self, profile: FirmProfile, on_date: date,
                      average_employees: Optional[float] = None,
                      group_scope: bool = False) -> bool:
        """Strict conjunction required by the model's post-Omnibus scope.

        The annual historical workforce average can be supplied by the
        workforce ledger.  A one-day headcount reduction therefore cannot
        instantaneously remove the reporting obligation.
        """
        if group_scope:
            turnover = profile.group_annual_net_turnover
            employees = profile.group_average_employees
            if turnover is None or employees is None:
                return False
        else:
            turnover = profile.annual_net_turnover
            employees = profile.average_employees if average_employees is None \
                else float(average_employees)
        return (self.csrd_active(on_date)
                and turnover > self.csrd_turnover_threshold
                and employees > self.csrd_employee_threshold)

    def active_authorities(self, on_date: date) -> tuple[RuleAuthority, ...]:
        authorities = [RuleAuthority.UCPD_BASE,
                       RuleAuthority.MARKET_DISCLOSURE]
        if self.empowering_consumers_active(on_date):
            authorities.append(RuleAuthority.EMPOWERING_CONSUMERS_2024_825)
        if self.csrd_active(on_date):
            authorities.append(RuleAuthority.CSRD)
        if self.csddd_active(on_date):
            authorities.append(RuleAuthority.CSDDD)
        if self.green_claims_preverification_active(on_date):
            authorities.append(RuleAuthority.GREEN_CLAIMS_COUNTERFACTUAL)
        return tuple(authorities)


class ESGRegulation:
    """
    Stylized Directive (EU) 2026/470 policy object.

    All attributes are plain instance fields initialized from the
    `constants` canon, so an experiment can construct one instance,
    override a field (e.g. `audit_probability = 1.0` for a
    full-assurance counterfactual) and inject it into the Simulation --
    no other module needs to change.
    """

    __slots__ = (
        "mandatory_size_threshold", "audit_probability",
        "detect_steepness", "detect_midpoint", "wedge_tolerance",
        "omission_rate_default", "penalty_rate_dec",
        "turnover_balance_multiple_dec", "transition_plans_mandatory",
        "enforcement_start_day", "green_bonds_allowed",
        "reporting_period_days", "reserve_base_ratio",
        "green_risk_weight_discount", "omega_min", "green_bond_omega",
        "institutions_use_credibility",
        # Audit trail / conservation counters.
        "audits_performed", "scandals_detected",
        "total_penalties_dec", "scandal_log",
    )

    def __init__(self):
        # WP1.1 -- size-scoped mandatory disclosure (Art. 2(4)).
        self.mandatory_size_threshold = REG_MANDATORY_SIZE_THRESHOLD
        # WP1.3 -- limited assurance only (Art. 1(3), recital 5).
        self.audit_probability = REG_AUDIT_PROBABILITY
        self.detect_steepness = REG_DETECT_STEEPNESS
        self.detect_midpoint = REG_DETECT_MIDPOINT
        self.wedge_tolerance = REG_WEDGE_TOLERANCE
        # WP1.4 -- omission exemptions (Art. 2(4)(b)(iii)).
        self.omission_rate_default = REG_OMISSION_RATE_DEFAULT
        # WP1.5 -- penalty regime (Art. 4(19) / CSDDD Art. 27(4)).
        self.penalty_rate_dec = REG_PENALTY_RATE_DEC
        self.turnover_balance_multiple_dec = REG_TURNOVER_BALANCE_MULTIPLE_DEC
        # WP1.6 -- no mandatory transition plans (recital 47).
        self.transition_plans_mandatory = REG_TRANSITION_PLANS_MANDATORY
        # WP1.7 -- application timing (Art. 3, Art. 5).
        self.enforcement_start_day = REG_ENFORCEMENT_START_DAY
        # WP6 gate -- green-bond framework left in force by the Omnibus.
        self.green_bonds_allowed = REG_GREEN_BONDS_ALLOWED
        self.reporting_period_days = REG_REPORTING_PERIOD_DAYS
        # WP7 -- green supporting factor parameters.
        self.reserve_base_ratio = RESERVE_BASE_RATIO
        self.green_risk_weight_discount = GREEN_RISK_WEIGHT_DISCOUNT
        self.omega_min = OMEGA_MIN
        self.green_bond_omega = GREEN_BOND_OMEGA
        # WP3 -- institutional reliance toggle.
        self.institutions_use_credibility = INSTITUTIONS_USE_CREDIBILITY

        self.audits_performed = 0
        self.scandals_detected = 0
        self.total_penalties_dec = _ZERO
        self.scandal_log: list[tuple] = []   # (day, symbol, wedge, penalty)

    # -- WP1.7: enforcement phase-in ---------------------------------------- #
    def enforcement_active(self, day: int) -> bool:
        """Pre-enforcement days run with audits/penalties inactive and
        disclosure voluntary for everyone (Art. 3 / Art. 5 phase-in)."""
        return day >= self.enforcement_start_day

    # -- WP1.1: disclosure scope ---------------------------------------------#
    def is_mandatory_discloser(self, firm_size: float, day: int) -> bool:
        """Above the net-turnover/headcount threshold analog -> mandatory
        reporting; below -> VSME-style voluntary regime (Art. 29ca)."""
        if not self.enforcement_active(day):
            return False
        return firm_size >= self.mandatory_size_threshold

    # -- WP1.3: limited-assurance audit ---------------------------------------#
    def detection_probability(self, wedge: float) -> float:
        """
        Probability that a limited-assurance audit detects a misreporting
        wedge (disclosed - true - lawful omissions). Logistic in the gap:

            p(w) = 1 / (1 + exp(-steepness * (w - midpoint)))   for w > tol
            p(w) = 0                                            otherwise

        Monotone non-decreasing in `wedge` by construction (unit-tested).
        The tolerance floor reflects measurement noise: sub-tolerance gaps
        are indistinguishable from estimation error under limited depth.
        """
        if wedge <= self.wedge_tolerance:
            return 0.0
        return 1.0 / (1.0 + math.exp(
            -self.detect_steepness * (wedge - self.detect_midpoint)))

    def run_audit(self, wedge: float, day: int) -> bool:
        """
        One reporting-period audit lottery for a mandatory discloser:
        the firm is audited with `audit_probability`; a triggered audit
        detects the wedge with `detection_probability(wedge)`. Voluntary
        reporters are never audited (the caller must not invoke this for
        them). Consumes 0 RNG draws when enforcement is inactive.
        """
        if not self.enforcement_active(day):
            return False
        self.audits_performed += 1
        if random.random() >= self.audit_probability:
            return False
        return random.random() < self.detection_probability(wedge)

    # -- WP1.5: penalty regime -------------------------------------------------#
    def penalty_for(self, balance: float) -> Decimal:
        """
        Sanction on detection, capped at 3% of turnover (Art. 4(19)).
        Turnover is proxied as `turnover_balance_multiple * balance`
        (STYLIZATION -- see constants.py). Cent-quantized Decimal.
        """
        turnover_dec = (Decimal(repr(round(balance, 2)))
                        * self.turnover_balance_multiple_dec)
        return (self.penalty_rate_dec * turnover_dec).quantize(
            CREDIT_CENT_DEC, rounding=ROUND_DOWN)

    def record_scandal(self, day: int, symbol: str, wedge: float,
                       penalty_dec: Decimal) -> None:
        """Books a detected scandal into the audit trail."""
        self.scandals_detected += 1
        self.total_penalties_dec += penalty_dec
        self.scandal_log.append((day, symbol, wedge, float(penalty_dec)))

    # -- WP7: green supporting factor ------------------------------------------#
    def risk_weight(self, disclosed_green_score: float) -> float:
        """
        Reserve risk weight of an exposure backed by an asset with the
        given DISCLOSED green score (WP3 institutional reliance):

            omega = max(OMEGA_MIN, 1 - discount * disclosed_score)

        Strictly positive and monotone non-increasing in the score.
        """
        omega = 1.0 - self.green_risk_weight_discount * disclosed_green_score
        if omega < self.omega_min:
            return self.omega_min
        return omega
