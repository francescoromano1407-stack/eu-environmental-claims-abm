# Firm Own-Share Price Feedback Static Audit

- Audit time (UTC): `2026-07-16T21:44:06+00:00`
- Repository: `C:\Users\slend\Desktop\Financial-market-simulation\Economy_financial`
- Final classification: `direct_price_feedback_detected`

## Central answer

Yes. At least one firm decision method directly reads an own-share market variable.

## Decision-category dependency table

| Category | Classification | Decision methods | Direct evidence | Indirect evidence |
|---|---|---:|---:|---:|
| greenwashing_disclosure | no_price_feedback_detected | 6 | 0 | 0 |
| compliance | inconclusive_static_analysis | 0 | 0 | 0 |
| investment | no_price_feedback_detected | 2 | 0 | 0 |
| financing | direct_price_feedback_detected | 1 | 3 | 0 |
| production_or_strategy | no_price_feedback_detected | 1 | 0 | 0 |
| reputation_management | inconclusive_static_analysis | 0 | 0 | 0 |

## Evidence locations

- `C:\Users\slend\Desktop\Financial-market-simulation\Economy_financial\market_sim\corporates.py:516` — `CorporatePolicy.sell_treasury` reads/calls `venue.order_book` (direct_own_share_read).

```python
515:             return 0.0
516:         book = venue.order_book
517:         mid = book.get_midpoint(self.asset.get_last_price())
```

- `C:\Users\slend\Desktop\Financial-market-simulation\Economy_financial\market_sim\corporates.py:517` — `CorporatePolicy.sell_treasury` reads/calls `book.get_midpoint` (direct_own_share_read).

```python
516:         book = venue.order_book
517:         mid = book.get_midpoint(self.asset.get_last_price())
518:         v_fair_true = v_fund * (1.0 + GREENIUM_GAMMA
```

- `C:\Users\slend\Desktop\Financial-market-simulation\Economy_financial\market_sim\corporates.py:517` — `CorporatePolicy.sell_treasury` reads/calls `self.asset.get_last_price` (direct_own_share_read).

```python
516:         book = venue.order_book
517:         mid = book.get_midpoint(self.asset.get_last_price())
518:         v_fair_true = v_fund * (1.0 + GREENIUM_GAMMA
```


## Detected firm classes

ConsumerFirmFlow, CorporateCommunicationsPolicy, CorporatePolicy, FirmProfile

## Limitations

- This is static analysis of Python source. It does not execute the model or prove runtime causality.
- A variable used by traders, regulators, investors, or an order book is not treated as firm feedback unless it reaches an identified firm decision method.
- Potential dynamic dispatch, external configuration, or dependencies outside the parsed source may require a separate runtime trace audit.
- Generic prices, including the green-capital price, are not treated as own-share price feedback without explicit own-listing evidence.

## Audited source files

- `audit_firm_price_feedback.py` — `d229f2f9963c44bd287fde4504a561d94b4b635ed3122ee92fbe646c5724393e`
- `market_sim\__init__.py` — `747656addaab86b29c801c7ef4e1f8886d7b14e917a50ca1182d2b80b149b7c2`
- `market_sim\campaign_reporting.py` — `02cafa38db82b18303bd6abab5691bfb33dce39207b71b6643fdd497dafc211e`
- `market_sim\constants.py` — `e75d862df62005da3532de215b66322c26496217c80bbddcda1f5e642032e905`
- `market_sim\consumer_market.py` — `3db8729f4cd2e69d6be406e201ce41c2b6d348820084b8cafe4cc35487855d82`
- `market_sim\corporate_communications.py` — `f930dbc5abac84686120b42cf2a27302de33af1d21710f1cc8b0cece96161507`
- `market_sim\corporates.py` — `c8184342d6060e855cdb89c44fbd9d4e57a7d091010ea2afefed30356ca28dfa`
- `market_sim\credit_market.py` — `c3b346b3bc0def0655f8b8f4575db4c5a714feb7bb692ce58215fac00e123eae`
- `market_sim\environmental_claims.py` — `a760af1a430f0ce5ad65f529121bd2d6a594bdfb9cb2e3352215f0bfe7959ea7`
- `market_sim\financial_validation.py` — `48f5e712e0313ee6c0158cbb914e1635ecaaff8305ebbae3a0c2fef4ec4a13a5`
- `market_sim\financial_validation_campaign.py` — `03114ca5060ab377e4c6ffd8af79a8861c82e2244581556c91ffbe1d61990f2d`
- `market_sim\greenwashing_supervision.py` — `2b155666e7d1f570b6015092cb044566a3e4d40b38ad19777e4fedef908b8758`
- `market_sim\main.py` — `9249e06831b15c294054f2e1df4bb836ef4a5039cb05a4eca7c3ca50eeeb9ad6`
- `market_sim\models.py` — `ca6c55bd0d4c786bd5878eabceed2553e0a9996ef281027333fb9356e84e3809`
- `market_sim\order_book.py` — `50aade8679eb55b781db5ce42b96edbcbcf39666910e6004a9011c9e7877cc7d`
- `market_sim\parameter_registry.py` — `25f03233fe77de329535a7f0bc0c60bb25050a985fd671419779ff6ba3c3dce7`
- `market_sim\policy_comparison.py` — `3d734fb82b5283a654c04ce3d1439d26167c3acd8883d07f5a326a7dc42d95d2`
- `market_sim\policy_regimes.py` — `e6d5795ef44a6cb27d5a68bf4dc9ba1bea4e38db933ea42e8b6812e31e186803`
- `market_sim\regulation.py` — `2b516d28665f96e0a8da513d1e2e1df2c50d0808b61d59274335064401686820`
- `market_sim\sensitivity_campaign.py` — `1adc8ba415925cde464733e8379b105db52593aac35cfc6a75cd44f4e88216f5`
- `market_sim\simulation.py` — `96c03162bec023ca38183d3ad8ed7cf39f647b072fd9e073ed006a5f5972f76c`
- `market_sim\state_intervention.py` — `fb824f002ae5ef93e275bc2ad9dfac45fd88f2ff71cbff9dbffdbbc097fe3aa4`
- `market_sim\traders.py` — `72401d5b24525ebca58f3ddc5294fe6dd5daf3adfdac65358d92679e3342e60e`
- `market_sim\workforce.py` — `b96e1a2d73f6110376e399d4a736238e3cee782cb32af8878097a34647c15503`
- `run_financial_validation_campaign.py` — `282669229b627571f32c902e14a18e9cce773b2c73890c8a21da5723f992a426`
- `run_global_lhs_campaign.py` — `03453b95eeafb7f250b0193a519554009ff5c29095be3efcd6b427ebfa9a916d`
- `run_replication_robustness.py` — `0de3c01405d22f49e336a23381b4f3ad7bc08a75b3877ad0d48f2023959e6978`
- `tools\revise_manuscript.py` — `790fe8b052dc1b32567f4b900b6d4f0bd2359963ff8624f42e833a1c58bb82c7`
