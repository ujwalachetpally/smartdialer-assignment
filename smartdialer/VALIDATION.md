# Validation record

Executed locally on 30 October 2026 with bundled Python 3.12 and standard-library SQLite.

`python -m unittest discover -v`: 15 tests passed.

| Agents | Concurrent workers | Distinct allocations | Elapsed seconds | Allocations/second |
|---:|---:|---:|---:|---:|
| 100 | 8 | 100 | 0.2428 | 411.9 |
| 1,000 | 8 | 1,000 | 0.6793 | 1,472.1 |
| 10,000 | 8 | 10,000 | 3.0879 | 3,238.4 |

Each run asserted uniqueness of both allocated agents and borrowers. These are initial allocation measurements on this machine, not sustained telecom throughput or a production capacity claim.

The simulation results and sampled pacing decisions are in simulation_results.json. Dataset profiling results are in dataset_profile.json. See SOLUTION.md for limitations and interpretation.
