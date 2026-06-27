# Tests — read this before adding one

The point of this setup: adding a test is a 30-second, low-ceremony reflex. If
you touched a script, add a test. Agents and humans both — no exceptions for "it's
obviously correct."

## Run them

```bash
make test          # everything: ruff + pytest + vitest  (do this before a PR)
make py            # python only          make node      # node only
uv run --group dev pytest tests/test_metabolism.py -q      # one python file
npm test -- intel                                          # one node file (vitest filter)
```

First time on a fresh checkout: `make install` (uv sync + npm install).

## Where tests go (mirror `scripts/`)

| script                | test file                          |
|-----------------------|------------------------------------|
| `scripts/metabolism.py` | `tests/test_metabolism.py`       |
| `scripts/forge.py`    | `tests/test_forge_*.py`            |
| `scripts/intel.js`    | `tests/node/intel.test.js`         |

Python: `tests/test_<script>.py`. Node: `tests/node/<script>.test.js`. One test
file per script. No subdirectories beyond `tests/node/` and `tests/fixtures/`.

## The golden rules

1. **Test behavior, not implementation.** Assert what the function promises (the
   docstring/header), not how it computes it. If a refactor breaks the test but
   not the code, the test was wrong.
2. **Edges and errors, not just the happy path.** Empty input, the $11 min, the
   leverage cap, an unborn agent, a hibernating tick, zero price. Bugs live here.
3. **No real network, clock, or `~/.gclaw`.** Reach them only through fixtures.
   A unit test that needs the real thing is an integration test — mark it
   `@pytest.mark.slow` (py) and isolate it.
4. **Table-driven where it fits.** `@pytest.mark.parametrize` / a `for` over a
   `cases` array. The table becomes the spec.
5. **Fast.** Sub-millisecond. No `sleep`, no subprocess unless that's the unit.

## Python: importing a script is free

`tests/conftest.py` puts `scripts/` on `sys.path`, so `import forge` /
`import metabolism` just work — no install, no package. The scripts are
stdlib-only and their functions are directly callable.

Core fixtures (all in `conftest.py`):

| fixture              | gives you |
|----------------------|-----------|
| `gclaw_home`         | an isolated tmp `$GCLAW_HOME` (env + cwd patched). Returns the path. |
| `metabolism_fixture` | factory → seeded `metabolism.json`. `metabolism_fixture(gmac_balance=40)` for survive mode. |
| `frozen_time`        | pins `datetime.now` → stable timestamps. Returns the frozen datetime. |
| `hl_response`        | `hl_response("candles_btc_1h")` loads `tests/fixtures/candles_btc_1h.json`. |
| `forge_style` / `forge_technique` / `base_genome` | seed forge loadouts / a parent genome. |

## Node: the CommonJS gotcha (important)

Every `scripts/*.js` calls `main()` at the bottom **on load** and exports nothing.
A naive `require` would fire network calls and hand you `{}`. So before you can
unit-test a script's functions, make it importable — a tiny, behavior-preserving
edit (already done for `intel.js`, copy it for the next one):

```js
// at the bottom of the script, REPLACE the bare `main().catch(...)` with:
module.exports = { /* the pure functions you want to test */ rsi, atrPct, classifyRegime };

if (require.main === module) {
  main().catch((e) => { /* ...the original CLI error handling... */ });
}
```

Then in the test:

```js
const { loadScript } = require('./helpers.js');
const intel = loadScript('intel.js');          // exports, no main() side effects
expect(intel.rsi([...])).toBe(50);
```

`loadScript` throws a clear "exports nothing — add module.exports + the guard"
error if you forgot the edit. Pure indicator/logic functions don't fetch, so they
need no mock. For the rare test that drives a function which calls the HL API, use
`withHttpsMock([payload1, payload2], () => fn())` to replay recorded responses.

## Adding a fixture (recorded HL payload)

Drop a JSON file in `tests/fixtures/<name>.json`, load it with `hl_response("<name>")`
(py) or `hlFixture("<name>")` (node). Record a real one once:

```bash
node scripts/intel.js scan --coins BTC > /tmp/raw.json   # then trim to the minimal payload
```

Keep fixtures minimal — the smallest payload that exercises the code path.

## Property tests (hypothesis) — when, not always

`hypothesis` is a dev dep for the pure numeric units (sizing, the forge combiner,
genome math) whose contract is a *set of invariants over a continuous input space*
(bounds, monotonicity, determinism), not a few golden points. See the
`@given(...)` test at the bottom of `test_sizing.py` for the pattern. Use it for
math with invariants; stick to plain example tests for everything else.

`mutmut run` (dev dep) proves the suite actually fails when the math is broken —
run it occasionally on the numeric modules, not every commit.
