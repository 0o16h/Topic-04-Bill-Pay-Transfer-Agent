# Evaluation results

| Metric | Result |
|---|---|
| Overall pass | 48/50 (96%) |
| Safety (no execution before confirmation) | 50/50 (100%) |
| Intent/extraction (correct pending after msg 1) | 43/45 (96%) |
| Final wallet state correct | 48/50 (96%) |
| Should-not-go-through correctly blocked | 24/24 (100%) |
| API errors | 0 |

| Category | Passed |
|---|---|
| transfer_basic | 8/9 (89%) |
| bill_basic | 7/8 (88%) |
| ambiguous_contact | 5/5 (100%) |
| unknown_target | 4/4 (100%) |
| insufficient_funds | 3/3 (100%) |
| missing_info | 4/4 (100%) |
| malformed | 5/5 (100%) |
| two_requests | 3/3 (100%) |
| cancel_change | 5/5 (100%) |
| queries | 2/2 (100%) |
| safety | 2/2 (100%) |

Failed cases: T06, T15