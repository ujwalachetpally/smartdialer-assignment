# SmartDialer assignment solution

Python 3.10+; standard library only. No installation, network access, credentials, or actual phone calls required.

## Run

Extract this folder, open a terminal in it, then run:

```console
python -m unittest discover -v
python simulate.py
python load_test.py
python profile_dataset.py "path/to/collections_30k_dataset (1).zip"
```

Windows users can use `py -3` instead of `python`. The scripts use temporary SQLite databases and remove them after execution. If a managed environment restricts the default temp directory, set TEMP and TMP to a writable scratch directory first.

Read SOLUTION.md for design reasoning, state diagrams, failure walkthroughs, scaling, and the final answer. Generated results are included as JSON. `simulation_results.json` includes a pacing explanation every 60 simulated seconds. `load_results.json` measures reservation throughput, not telecom throughput.

## Source map

- `dialer.py`: transactional store, progressive and predictive engines, safety controller, durable outbox worker, reconciliation, two mock providers.
- `test_dialer.py`: correctness and concurrency tests.
- `simulate.py`: deterministic-seed simulation of all four scenarios against both providers and both pacing modes.
- `load_test.py`: 8 concurrent workers, 100 / 1,000 / 10,000 agent allocation runs.
- `profile_dataset.py`: profiles every CSV in the supplied archive without extracting or printing personal records.

## Minimal use

```python
from dialer import Store, SafetyController, Progressive, MockProvider, Worker
s = Store('dialer.db')
s.seed(agents=50, borrowers=30000)
p = MockProvider('provider.db')
worker = Worker(s, {'A': p})
requested = Progressive().propose(available=50)
ids = SafetyController(s).admit('campaign-1:tick-1', requested, provider='A')
worker.dispatch()
for call in ids:
    for event_id, state in p.events(call, answered=True):
        worker.event('A', event_id, call, state)
worker.wrap_up()
```

Reuse the same job identifier only when retrying the same scheduling operation. A new scheduling tick needs a new identifier. The prototype models one campaign and one shared agent pool. Borrowers are synthetic priority-ordered IDs; dataset records are profiled separately rather than silently treated as eligible contacts.

## What is deliberately bounded

This is a functional progressive prototype with an experimental predictive proposal engine and mandatory conservative safety cap. It does not claim predictive overbooking gains. It models an atomic local bridge; no real bridge, inbound webhook server, UI, calendar/contact policy engine, or multi-host database is included. See the design note before extending it.
