# Simulation results

50 agents, 900 virtual seconds, seed 42. Utilization is connected time divided by staffed time.

| Provider | Scenario | Mode | Utilization | Initiated | Connected | Reduced ticks |
|---|---|---|---:|---:|---:|---:|
| A | A | progressive | 95.3% | 2134 | 395 | 0 |
| A | A | predictive | 95.3% | 2134 | 395 | 329 |
| A | B | progressive | 97.7% | 1034 | 500 | 0 |
| A | B | predictive | 97.7% | 1034 | 500 | 126 |
| A | C | progressive | 99.2% | 367 | 250 | 0 |
| A | C | predictive | 99.2% | 367 | 250 | 35 |
| A | D | progressive | 95.6% | 1963 | 400 | 0 |
| A | D | predictive | 95.6% | 1963 | 400 | 249 |
| B | A | progressive | 71.8% | 1577 | 287 | 39 |
| B | A | predictive | 71.0% | 1561 | 284 | 404 |
| B | B | progressive | 81.9% | 976 | 433 | 39 |
| B | B | predictive | 80.1% | 951 | 420 | 118 |
| B | C | progressive | 92.9% | 421 | 250 | 0 |
| B | C | predictive | 91.1% | 421 | 250 | 24 |
| B | D | progressive | 75.9% | 1292 | 325 | 39 |
| B | D | predictive | 73.3% | 1271 | 315 | 129 |

Predictive proposals are capped at one reserved agent per admitted call. Equal or lower utilization is expected with this strict cap. These are simulated results, not live dialing performance.

Provider B adds setup latency, failures, duplicate/late events, and an outage. Detailed estimates, requests, and approvals are in simulation_results.json. See SOLUTION.md for scenario definitions and model assumptions.