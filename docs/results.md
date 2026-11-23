# Ground-truth check

**4 of 4 recorded incidents passed.**

| Incident | Type | Start error | End error | Cause rank | Confidence | Checks | Result |
|---|---|---|---|---|---|---|---|
| bad_deploy | bad deploy | +1.0s | +0.1s | #1 | HIGH | 10/10 | PASS |
| failing_dependency | failing dependency | +1.0s | +0.5s | #1 | HIGH | 10/10 | PASS |
| no_clear_cause | no clear cause | +1.0s | -0.0s | none expected | LOW | 11/11 | PASS |
| resource_exhaustion | resource exhaustion | +0.5s | -0.1s | #1 | HIGH | 10/10 | PASS |

Start and end must be within the tolerance stored in each `ground_truth.json` (5 s for the demo incidents). The real cause must be in the top 3; the no-cause incident must give a LOW-confidence report that says so.
