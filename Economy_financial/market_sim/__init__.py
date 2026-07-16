"""
market_sim -- Agent-based financial market simulation with a P2P LOB engine.

Modular package refactor of `market_simulation_opus.py`. The domain
specification (Parts A-D below) is preserved verbatim across the modules;
this docstring is the package-level architectural map.

Package layout
--------------
  constants.py   Microstructural constants: friction floors, solvency
                 floors, LOB decay hazard bounds, evolutionary epoch
                 config, Part G regulatory/greenwashing parameters.
  regulation.py  Calendar-aware LegalRegime plus the retained legacy
                 ESGRegulation policy experiment.
  environmental_claims.py  Typed facts, claims, evidence, assessments and
                 information-safe public/investor signals.
  greenwashing_supervision.py  Assurance, consumer/reporting/market rule
                 tracks, finite-capacity cases, remedies and sanctions.
  consumer_market.py  Heterogeneous consumer beliefs, logit demand and the
                 external real-economy ledger.
  workforce.py   Employee trust, bounded productivity and turnover.
  models.py      Data primitives: LimitOrder / MarketOrder (__slots__),
                 Asset (log-space OU fundamental; true vs disclosed
                 green score split, Part G), GreenBond (__slots__, WP6),
                 IncrementalEMA (O(1)).
  order_book.py  OrderBook: bisect-sorted price-time priority arrays,
                 O(1) best-level pops, lazy tombstone compaction, exact
                 double-entry escrow settlement under dynamic friction.
  corporates.py  CorporatePolicy (honest / greenwasher / adaptive) and
                 the NPV-driven continuous transition machinery plus the
                 GreenCapitalPrice OU (Part G, WP2 + WP5).
  traders.py     Behavioral agents: Trader (noise / fundamentalist /
                 chartist; WP4 strategy mixtures, WP3 credibility
                 beliefs), MarketMaker (tanh skew, asymmetric spreads),
                 Manipulator / GreenManipulator (spoofing FSMs).
  credit_market.py  Part E credit layer + WP7 green-weighted reserves.
  state_intervention.py  State fiscal agent + WP6 sovereign green bonds.
  simulation.py  Simulation orchestrator + CSV export pipeline.
  main.py        Entry point (`python -m market_sim.main`).

Dependency graph (acyclic, verified at runtime; regulation sits beside
constants at the bottom, corporates between models and simulation):

    constants   regulation
        ^        ^
        |        |
      models  <--+------  order_book
        ^   ^               ^ (TYPE_CHECKING only)
        |   |               |
        | corporates        |
        |   ^               |
     traders|  <------------+   (TYPE_CHECKING only)
        ^   |
        |   |
      simulation  <-  main

Domain specification (systemic refactor, Parts A-D)
---------------------------------------------------
PART A -- Herd control: smoothed evolutionary strategy mechanism
  1. The independent 10%-probability strategy switch is replaced by a
     Discrete Choice / Logit model. Each strategy carries an exponentially
     smoothed "attractiveness" score (memory factor STRATEGY_MEMORY) built
     from its realised epoch return; migration targets are sampled from a
     softmax over these scores with intensity-of-choice INTENSITY_OF_CHOICE.
  2. Inertia: only a random SWITCH_CONSIDERATION_RATE fraction of traders
     even re-evaluate their strategy at a review, and the smoothed
     attractiveness prevents reactions to single-epoch noise.
  3. Hard cap: at most MAX_SWITCH_FRACTION (5%) of the evolutionary
     population may actually change strategy per epoch, eliminating the
     synchronised order-cancellation shocks that previously caused
     macro-scale liquidity voids and cascades.

PART B -- Dynamic information flow and elastic valuation corridors
  1. The corporate fundamental (the balance sheet backing the intrinsic
     value) is a mean-reverting Ornstein-Uhlenbeck process in log space
     around a slowly drifting anchor (GBM-like drift), updated every trading
     day. Information arrives organically instead of as rare uniform jumps.
  2. Fundamentalists use no hard 0.95/1.05 trigger walls. The mispricing is
     mapped through a Gaussian error function into a smooth trade
     probability whose width scales with current realised volatility:
     small mispricings are traded rarely and gently, large ones with rising
     conviction, and the corridor breathes with the volatility regime.
  3. The initial corporate balance is seeded from the TRUE total float
     (including the Market Maker and Manipulator inventories), so the
     simulation does not start structurally overvalued.

PART C -- Adaptive Market Maker microstructure
  1. Asymmetric, volatility-scaled spreads: the half-spread widens with
     realised relative volatility, and the side that would worsen the MM's
     inventory position widens further while the unwinding side tightens.
  2. The inventory skew is passed through tanh (smooth for small
     imbalances, saturating defensively near capacity) instead of a linear
     multiplier that over-reacted to minor deviations.
  3. The MM never abruptly drains the book: quoted sizes scale down
     smoothly near capacity instead of quotes disappearing, and after any
     mass cancellation (evolutionary review) `provide_structural_depth`
     posts temporary backstop layers wherever near-mid depth is thin.

PART D -- Fluid friction and probabilistic LOB decay
  1. Commission and Tobin tax are dynamic: they scale down toward floor
     rates during low-volume regimes (measured as short-run volume vs a
     long-run EMA baseline) so friction can no longer freeze the market.
     Escrow accounting stays exact: every resting order stores the
     commission rate at which its cash was escrowed and is settled or
     refunded at exactly that rate.
  2. The rigid ORDER_TTL_DAYS cutoff is replaced by a probabilistic
     age-increasing evaporation hazard: stale resting orders dissolve
     smoothly instead of building week-long artificial walls that all
     expire at once.

PART G -- Legacy ESG experiments and opt-in EU greenwashing supervision
----------------------------------------------------------------------
The ESG layer is reoriented around greenwashing as the central research
object. The current prevention layer is gated behind
``Simulation(enable_greenwashing_supervision=True)`` and is inert otherwise.
It combines the base UCPD, Directive (EU) 2024/825, amended CSRD rules,
separate financial-market communication rules and CSDDD due diligence; no
single directive is treated as a complete greenwashing code.  The historical
WP1-WP7 mechanics below remain available as legacy policy experiments.

  WP1  Regulatory layer (`regulation.py`): stylized Directive (EU)
       2026/470. Size-scoped mandatory disclosure (Art. 2(4); balance
       proxy for the turnover/headcount threshold), the disclosed-vs-true
       green-score wedge, limited-assurance probabilistic audits with
       logistic detection power (Art. 1(3), recital 5), lawful omission
       exemptions damping downward revisions (Art. 2(4)(b)(iii)),
       penalties capped at 3% of a turnover proxy routed corporate
       balance -> State treasury (Art. 4(19)), no mandatory transition
       plans with a pre-Omnibus counterfactual toggle (recital 47), and
       a pre-enforcement phase-in window (Art. 3 / Art. 5). Every
       stylization is tagged with a STYLIZATION comment stating what the
       directive actually says and what was simplified.
  WP2  Greenwashing corporates (`corporates.py`): one CorporatePolicy
       per listing in {honest, greenwasher, adaptive}. Cheap-talk
       disclosure at a PR cost orders of magnitude below real CAPEX,
       regulatory arbitrage around the size threshold, a one-period
       expected-profit argmax over inflation (all terms from live state),
       five harvesting channels measured where the euros flow (treasury
       greenium sales, subsidy wedge gains, sovereign-fund pressure,
       reserve-relief funding advantage, bond-funded spillover), and
       scandal dynamics feeding trader beliefs and the GreenManipulator
       sentiment (complementary predators: one manipulates the signal,
       the other the book).
  WP3  Greenwashing-aware traders: per-asset credibility beliefs kappa
       with slow trust drift, sharp scandal collapse and mild sector
       spillover; fundamentalists price the greenium on the credibility-
       discounted disclosed score with a sophisticated wedge-suspicion
       haircut; noise traders use a diluted kappa; chartists stay price-
       only (asymmetry documented in the handler); institutions (State
       fund, bank) rely on the raw disclosure unless the
       INSTITUTIONS_USE_CREDIBILITY counterfactual is toggled.
  WP4  Strategy mixtures: each trader carries a weight vector on the
       (noise, fundamentalist, chartist) simplex; per decision the
       handler is sampled from the weights (single RNG stream; sampling
       chosen over blending because heterogeneous order intents cannot
       be averaged without breaking order-sizing/escrow semantics).
       Evolution moves weights a bounded step toward the logit target
       vertex under an L1 mass budget (MAX_SWITCH_FRACTION * 2 per
       epoch); Dirichlet initialization via random.gammavariate with an
       exact-vertex regression option.
  WP5  NPV-driven continuous, reversible transition: the stepped
       heuristic is DELETED; dg/dt = responsiveness * marginal NPV with
       a log-OU price of green capital, convex marginal costs, live
       subsidy/greenium/funding/bond sensitivities (derived term-by-term
       in the corporates.py docstring), maintenance drag, negative-NPV
       backsliding (sunk costs stay sunk), and cent-quantized CAPEX
       through the OU-synced balance setter.
  WP6  Sovereign green bonds (`state_intervention.py`): regulation-gated
       primary issuance at par to the bank and cash-rich traders, coupon
       = policy rate - greenium, earmarked use-of-proceeds sub-ledger
       (asserted identity: issued == earmarked + spent-green), coupon /
       redemption servicing next to accrue_interest, sovereign-stress
       roll instead of default (documented simplification).
  WP7  Green-weighted reserves (`credit_market.py`): RR = base ratio *
       sum(exposure * omega), omega = 1 - discount * DISCLOSED score
       (floored at OMEGA_MIN); lending capacity = capital - RR;
       deliberate model risk -- scandals snap omega back to the true
       score, RR jumps, and reserve_shortfall events are logged.

Part G conservation identities (asserted in the end-of-run audit):
  - penalties:   sum(sanctions) leaves corporate balances and equals the
                 State's penalty_inflow_dec exactly (transfer, not sink);
  - green bonds: bonds_issued == green_proceeds + green_proceeds_spent
                 (earmarked euros fund only subsidies / fund purchases);
  - treasury sales: buyer cash -> corporate wallet -> balance sheet,
                 accumulated in total_treasury_sweeps;
  - reserves:    RR is bookkeeping on bank capital, never a cash flow.

Retained legacy guarantees (all still active):
  - Dynamic shares-outstanding fundamental (no hard-coded float).
  - Persistent order book (no daily wipe); cancellation is the only
    removal path and always refunds escrow.
  - Solvency-constrained dividends (corporate balance floor, no printing).
  - Strategy switches recorded via `strategy_history`; canonical trader_id
    immutable; open orders cancelled on switch.
  - MM and Manipulators are full macro participants (dividends, interest).
  - O(1) incremental EMAs; bisect-maintained sorted books with lazy
    tombstone cancellation and periodic compaction.
  - Manipulator (spoofer / momentum-igniter) finite-state machine.
  - Cash/share conservation, exact escrow telescoping, Decimal canon for
    monetary constants, acyclic import graph, seed-42 bit-for-bit
    reproducibility with all new features disabled.

Author: Antigravity (refactored)
Date: July 2026
"""

from __future__ import annotations

from market_sim.corporates import (
    CorporatePolicy,
    GreenCapitalPrice,
)
from market_sim.credit_market import (
    CentralBank,
    CommercialBank,
    CreditLine,
    CreditMarket,
)
from market_sim.consumer_market import (
    ConsumerMarket,
    ConsumerMarketLedger,
    ConsumerSegment,
)
from market_sim.environmental_claims import (
    AssessmentOutcome,
    ClaimAssessment,
    EnvironmentalClaim,
    EnvironmentalFactVector,
    EvidenceRecord,
    FirmProfile,
    InvestorEnvironmentalContext,
)
from market_sim.greenwashing_supervision import (
    GreenwashingSupervisor,
    RegulatoryCase,
    SupervisionParameters,
)
from market_sim.models import (
    Asset,
    AssetPosition,
    GreenBond,
    IncrementalEMA,
    LimitOrder,
    MarketOrder,
)
from market_sim.order_book import OrderBook
from market_sim.policy_comparison import (
    HorizonGridResult,
    PolicyComparisonReport,
    PolicyOutcomeEvaluator,
    PolicyScoreWeights,
    SensitivityResult,
    run_greenwashing_policy_comparison,
    run_horizon_grid,
    run_sensitivity_analysis,
)
from market_sim.policy_regimes import (
    CertifiedGreenDataConnector,
    ConnectorAuthorizationState,
    ConnectorParameters,
    DataSourceKind,
    GreenwashingPolicyRegime,
    PrescreeningParameters,
    PrescreeningParticipationMode,
    ReconciliationClass,
    SMEPrescreeningHub,
    export_connector_ledgers,
    export_prescreening_ledger,
)
from market_sim.regulation import ESGRegulation, LegalRegime
from market_sim.simulation import (
    MarketVenue,
    Simulation,
    export_claim_audit_log,
    export_correction_events,
    export_regulatory_cases,
    export_simulation_metrics,
)
from market_sim.state_intervention import State
from market_sim.traders import (
    GreenManipulator,
    Manipulator,
    MarketMaker,
    Trader,
)
from market_sim.workforce import WorkforceState

__all__ = [
    "Asset",
    "AssetPosition",
    "CentralBank",
    "CommercialBank",
    "ConsumerMarket",
    "ConsumerMarketLedger",
    "ConsumerSegment",
    "CorporatePolicy",
    "CreditLine",
    "CreditMarket",
    "ESGRegulation",
    "LegalRegime",
    "EnvironmentalClaim",
    "EnvironmentalFactVector",
    "EvidenceRecord",
    "ClaimAssessment",
    "AssessmentOutcome",
    "FirmProfile",
    "InvestorEnvironmentalContext",
    "GreenwashingSupervisor",
    "RegulatoryCase",
    "SupervisionParameters",
    "GreenBond",
    "GreenCapitalPrice",
    "GreenManipulator",
    "IncrementalEMA",
    "LimitOrder",
    "Manipulator",
    "MarketMaker",
    "MarketOrder",
    "MarketVenue",
    "OrderBook",
    "Simulation",
    "State",
    "Trader",
    "WorkforceState",
    # Part H: three-regime State-intervention comparison.
    "CertifiedGreenDataConnector",
    "ConnectorAuthorizationState",
    "ConnectorParameters",
    "DataSourceKind",
    "GreenwashingPolicyRegime",
    "PolicyComparisonReport",
    "PolicyOutcomeEvaluator",
    "PolicyScoreWeights",
    "PrescreeningParameters",
    "PrescreeningParticipationMode",
    "ReconciliationClass",
    "SMEPrescreeningHub",
    "run_greenwashing_policy_comparison",
    "run_horizon_grid",
    "run_sensitivity_analysis",
    "HorizonGridResult",
    "SensitivityResult",
    "export_connector_ledgers",
    "export_prescreening_ledger",
    "export_claim_audit_log",
    "export_correction_events",
    "export_regulatory_cases",
    "export_simulation_metrics",
]

__version__ = "3.0.0"
