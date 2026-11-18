# Module: dsl

## What exists

The expression DSL the no-code path, the futures run and live share (ADR-0096, ADR-0098). The
package is **syntax, types, identity, deterministic evaluation and compilation**: C4c adds the
cross-sectional rank, similarity and the incremental (live) evaluator.

- `grammar.py` — `GRAMMAR_VERSION = "2"`, `tokenize`, `parse`. Whitespace-insensitive recursive
  descent: `or` < `and` < `not` < comparison < `+ -` < `* /` < unary `-` < call/atom, every
  binary operator left-associative. Numbers are `\d+` / `\d+\.\d+` only (no `.5`, `5.`,
  exponents, `inf`, `nan`, underscores). Comparisons are `> >= < <=` only (`==`, `!=`, `=` outside
  a declaration and chained comparisons are refused as ambiguous). `if(c, a, b)` is the only
  conditional. Text is capped at 10 000 characters and 64 levels of nesting.
- `ast.py` — immutable slotted nodes (`Literal`, `Feature`, `Param`, `Unary`, `Binary`, `Call`)
  and `Expression(root, types, params, source_text)`. A node carries its 1-based column; it never
  mutates and holds no type of its own.
- `types.py` — `Dimension(price, volume, time)`, `ExprType(kind, dimension)` with `kind` in
  `{series, bool, literal}`, `typecheck(node) -> ExprType` and `type_map`. `price`/`volume` are
  exponents (`close` is price^1, `volume` volume^1, `close/close` price^0) and `time` marks a
  time-kind feature. Features: `open`, `high`, `low`, `close`, `volume`, `time_of_day`,
  `minutes_since_open`, `minutes_to_close` (the last three are `SESSION_FEATURES`).
- `operators.py` — the frozen `OPERATORS` table and `OPERATOR_TABLE_VERSION = "2"`: signatures,
  result-type rules, the minimum window each estimator needs (`min_window`) and a precise summary
  of the semantics.
- `params.py` — `FreeParam`, `free_parameters`, `optimizable_parameters`, `bind`.
- `canonical.py` — `canonicalize`, `canonical_text`, `canonical_form`.
- `identity.py` — `structure_id` (`DSX-`), `parameterization_id` (`DSP-`),
  `compiled_id_basis`/`compiled_id` (`DSC-`).
- `evaluate.py` — `evaluate` (the vectorized evaluator), `warmup_bars`, `check_availability`.
- `compile.py` — `compile_expression`, `CompiledSignal`, `COMPILER_VERSION = "1"`.
- `metrics.py` — `structural_metrics` -> `StructuralMetrics`.
- `errors.py` — `ExpressionError`, a `ConfigurationError` carrying the column, the token and a
  hint (`docs/CONVENTIONS.md` §9).

### The scale-invariance rule (ADR-0086)

A price *level* is not invariant under a ratio adjustment, so the type checker refuses comparing
one to a constant and refuses mixing dimensions:

- accepted: `volume > 1000`, `time_of_day >= 570`, `minutes_to_close >= 2`,
  `close/delay(close,1) > 1.01`, `ts_zscore(close, 20) > 1.5`,
  `delta(close,1) > ts_std(close,20)`, `if(close > ts_mean(close,20), 1, -1)`;
- refused: `close > 4500`, `close + 5`, `close > volume`, `ts_rank(close,10) > close`,
  `time_of_day + 1`, `ts_mean(time_of_day, 5)`, `time_of_day > minutes_since_open`,
  `cs_rank(close)`, `cs_rank(volume)`, `true + 1`, `ts_mean(5, 3)`, a float/0/2001 window, and a
  constant root (`1 + 2`).

A fixed literal and a free parameter are dimension-polymorphic only in volume and time, never in
price: `volume > 1000` and `time_of_day >= 570` typecheck, `close > 4500` does not. Unification is
required for `+ - min max`, comparisons and both branches of `if`; `*`/`/` add and subtract
exponents (`*`/`/` never carry time); comparisons yield `bool`; `and`/`or`/`not` need `bool`;
arithmetic on `bool` is refused. A time feature is only comparable to a literal or selected by
`if`; any arithmetic or rolling operator on it, and a comparison of two time features, is refused.
The root may be a condition (`bool`) or a score (`series`, or a `literal`-typed `if`), and
`ExprType.price_degree` is what compilation refuses on ratio-adjusted data.

### The operator table

| Operator | Signature | Min window | Semantics | Result type rule | Version |
|---|---|---|---|---|---|
| `delay` | `delay(x, n)` | 1 | `x` shifted `n` rows; null for the first `n` | preserves the dimension of x | 1.0.0 |
| `delta` | `delta(x, n)` | 1 | `x - delay(x, n)` | preserves the dimension of x | 1.0.0 |
| `ts_mean` | `ts_mean(x, n)` | 1 | mean of the last n bars, current included | preserves the dimension of x | 1.0.0 |
| `ts_std` | `ts_std(x, n)` | 2 | sample standard deviation (ddof=1) of the last n | preserves the dimension of x | 1.0.0 |
| `ts_min` | `ts_min(x, n)` | 1 | minimum of the last n bars, current included | preserves the dimension of x | 1.0.0 |
| `ts_max` | `ts_max(x, n)` | 1 | maximum of the last n bars, current included | preserves the dimension of x | 1.0.0 |
| `ts_rank` | `ts_rank(x, n)` | 2 | average-tie rank of the current value in the last n, `(rank-1)/(n-1)` in [0, 1] | dimensionless series in [0, 1] | 1.0.0 |
| `ts_zscore` | `ts_zscore(x, n)` | 2 | `(x - ts_mean(x, n)) / ts_std(x, n)`; null at zero spread | dimensionless series | 1.0.0 |
| `ema` | `ema(x, n)` | 1 | alpha = 2/(n+1), adjust=False, seeded at the first value, null until n values | preserves the dimension of x | 1.0.0 |
| `cs_rank` | `cs_rank(x)` | — | cross-sectional rank at the same bar (C4c) | dimensionless; x must be dimensionless | 1.0.0 |
| `abs` | `abs(x)` | — | absolute value | preserves the dimension of x | 1.0.0 |
| `sign` | `sign(x)` | — | -1.0, 0.0 or 1.0 by the sign | dimensionless | 1.0.0 |
| `min` | `min(a, b)` | — | element-wise minimum, null-propagating | the unified dimension of a and b | 1.0.0 |
| `max` | `max(a, b)` | — | element-wise maximum, null-propagating | the unified dimension of a and b | 1.0.0 |
| `if` | `if(c, a, b)` | — | `a` where c is true, `b` where false, null where c is null | the unified type of the branches | 1.0.0 |

`x` must be a series for the rolling operators (`ts_mean(5, 3)` is refused: a rolling operator
over a constant). A window `n` is an int literal or an int free parameter, `min_window <= n <=
2000`; a parameter in a window position needs a default, and bounds, inside that range. An
unbounded window parameter is allowed: it can be extracted and bound (`bind` re-validates the
window), but it is not optimizable. A float parameter is refused. `ts_std(x, 1)`,
`ts_zscore(x, 1)` and `ts_rank(x, 1)` are refused by both `parse` and `bind`, naming the operator.

### Evaluation semantics (`evaluate`, ADR-0098)

`evaluate(expr, frame, *, calendar=None, bar_seconds=60) -> pl.Series` returns one value per row,
in the frame's order: `Float64` for a numeric root (a score), `Boolean` for a bool root (a
condition). It evaluates the canonical form (the rewrite is exact, so a raw parsed tree is fine).
The same semantics apply to every operator:

- **Streams.** A `symbol` column makes each symbol its own stream (every rolling, shifting and
  recursive operator is computed per symbol); without it the whole frame is one stream. Rows must
  be sorted by `(symbol,) event_time`, strictly increasing within a stream; a duplicate or a
  backward step is refused (`DataQualityError`).
- **Windows** count rows (bars) of the stream and include the current row, so "over the last n
  bars" means the same thing for every operator (a breakout is written `close > delay(ts_max(close,
  n), 1)`, not `close > ts_max(close, n)`).
- **Nulls.** Null in gives null out. Every non-finite intermediate — `inf`, `NaN`, a division by
  zero, `0/0` — becomes null. A rolling window is null unless all `n` values are present (no
  skipping and no forward fill). Comparisons with null give null, `and`/`or`/`not` follow Kleene's
  three-valued logic, `if(null, a, b)` is null, and `min`/`max` propagate null (they are *not*
  `pl.min_horizontal`, which skips a null operand).
- **Operators.** `delay`/`delta` shift by rows; `ts_mean`/`ts_min`/`ts_max` are the last n bars;
  `ts_std` is the sample standard deviation (ddof=1); `ts_zscore` is null when the window's
  standard deviation is null or zero; `ts_rank` averages ties and is normalized to `[0, 1]`;
  `ema` uses alpha = 2/(n+1) and `adjust=False`, is seeded at the stream's first non-null value,
  gives null for a null input *without changing its state*, and is null until n non-null values
  have been seen (identical to `strategy_spec`'s `ema` on a gap-free series); `abs`, `sign`,
  `+ - * /` and unary `-` are pointwise and `Float64`.
- **`cs_rank` is refused** with "cs_rank is evaluated in C4c": a cross-section needs the whole bar.
- **Session features** come from the CME session calendar (ADR-0091/0092), never from a clock
  rule: `time_of_day` is exchange-local (`America/Chicago`) whole minutes since midnight at the
  bar's END; `minutes_since_open` is the whole minutes from the bar's END back to its trade date's
  scheduled session open; `minutes_to_close` is the whole minutes from the bar's END forward to
  that session's scheduled close. The last two are **null on an off-schedule bar** (the print after
  a close). An expression that reads one of the three is refused, naming the feature, unless a
  `SessionCalendar` is passed (`calendar_for(root)`): a generic frame has no exchange time zone.

### Warm-up (`warmup_bars`)

`warmup_bars(expr)` is the number of leading rows of a gap-free stream that are null **by
construction**: `delay`/`delta` add `n`, a rolling operator and `ema` add `n - 1`, composition adds
along a path, and a binary operator or `if` takes the largest of its arguments. It is static (it
reads the tree and the bound parameters, never data) and is recorded with a compiled signal, so a
caller knows how many bars a definition needs before its first value.

### Availability (`check_availability`, ADR-0098)

C2's row column `available_at` is the **only** availability source; the DSL builds no second one.
`evaluate` refuses a frame without `event_time` and `available_at` (`Int64` UTC ns) and one that
breaks the contract, naming the first offending row and its timestamp:

- `available_at < event_time` — the data claims to be known before the bar closed;
- `available_at` decreasing within a stream — a later bar known earlier than an earlier one;
- `available_at > event_time + bar_seconds` — the feed latency is longer than one bar, so a
  decision at this bar could not reach the next bar's open (not supported).

### The compiled signal (`CompiledSignal`, ADR-0098)

`compile_expression(text_or_expr, *, params=None, signal_input="ratio_adjusted")` parses (when it
gets text), binds the parameters (`bind`), canonicalizes, type-checks again and returns a frozen
`CompiledSignal`: `canonical_text`, `canonical_form`, `root_kind` (`condition` or `score`),
`features`, `uses_session_features`, `warmup_bars`, `params`, `signal_input`, the three ids,
`compiler_version` (`COMPILER_VERSION = "1"`) and `operator_versions`. It holds no evaluation
state, so live (C4c) reuses the same definition with its own per-stream state.

- `CompiledSignal.evaluate(frame, *, calendar=None, bar_seconds=60)` returns a frame with
  `event_time`, `decision_at` (= the bar's `available_at`), `value` (`Float64` or `Boolean`) and
  `symbol` when the frame has one. Timing: a value is decided at the bar's close and is knowable at
  `decision_at`, never before.
- `CompiledSignal.describe()` is the JSON-able document a manifest records.
- On `signal_input="ratio_adjusted"` a **score** must have price degree 0 (`delta(close, 1)`,
  `ts_mean(close, 20)` and `close` are refused with a hint; `sign(delta(close, 1))` and
  `delta(close,1)/delay(close,1)` are accepted). A **condition** is homogeneous by typing. Volume
  is not scaled by a ratio adjustment, so a volume degree is left alone.
- `compiled_id` hashes the parameterization id, the compiler version, the semantic versions of the
  operators used and the input **roles** (`signal_input` and the feature list) — not dataset
  hashes, which belong to the run id (ADR-0098 §6).

### Free parameters

Only `$`-marked values are free; an unmarked literal is fixed and never extracted. A parameter is
declared once (`$n:int[5,200]=20`, `$n=20`, `$n:float[0.1,3.0]=1.5`); its type is the declared one
or inferred from the default. Repeated references bind to that one declaration, and repeated
declarations must be identical (conflicts name both columns). `low`/`high` are both present or
both absent, `low <= default <= high`, and int parameters take int defaults and bounds.
`optimizable` means the declaration carries bounds: an unbounded parameter can be bound but not
swept. `bind(expr, {"n": 30})` returns a new immutable expression with the new default; unknown
names, a wrong type and an out-of-bounds value are refused, and a window is re-validated against
the operator's `min_window`.

### Canonicalization

`canonicalize` is deliberately conservative and never changes evaluation semantics; its result is
re-typechecked and must keep the same root type:

1. constant folding only when every operand is a fixed literal (never a `$parameter`) and only
   for `+ - * /`, unary `-`, `abs`, `sign`, `min`, `max`, with Python int/float64 arithmetic;
   `int` op `int` stays `int` for `+ - *`, `/` yields `float`; a constant division by zero and a
   non-finite result are refused. Canonical float text is `repr(float)`.
2. identities removed only where exact in IEEE-754: `x * 1`, `1 * x`, `x / 1`, `x - 0`.
   **`x + 0` is kept**: `-0.0 + 0.0` is `+0.0` while `-0.0` is not, so removing it would change an
   evaluation.
3. double negation: `-(-x) -> x`, `not (not b) -> b`.
4. the two direct operands of `+`, `*`, `min`, `max` are sorted; sums are never flattened or
   re-associated (`(a+b)+c` stays nested, floating-point addition is not associative). The sort
   key is the canonical text with each parameter rendered as an anonymous `$int`/`$float`.
5. distinct parameters are numbered `$0`, `$1`, ... by first occurrence in a pre-order traversal;
   repeated references share a number.

`canonical_text` is fully parenthesized where needed with one space around binary operators and
each parameter declaration at its first occurrence only; `canonical_form` is the JSON-able AST
(`{"op": ...}`, `{"lit": "20", "type": "int"}`, `{"feature": "close"}`,
`{"param": 0, "type": "int"}`). Both are idempotent, and a property test proves that evaluating an
expression and evaluating its canonical form is bitwise the same (nulls included).

### The three identities

- `structure_id` = `DSX-` + SHA-256 of grammar version, operator-table version and the canonical
  form. It covers topology, operators, features, fixed literals and parameter placeholders with
  their binding pattern and type, but **not** parameter names, defaults or ranges:
  `ts_mean(close, $n=20)` and `ts_mean(close, $m:int[5,50]=10)` share it, `$a + $a` differs from
  `$a + $b`.
- `parameterization_id` = `DSP-` + SHA-256 of the structure id and `[type, value, low, high]` per
  placeholder in order.
- `compiled_id` = `DSC-` + SHA-256 of `compiled_id_basis`: parameterization id, compiler version,
  the semantic version of every operator used and the input roles. `CompiledSignal` is its one
  caller.

### Structural metrics

`structural_metrics` runs on the canonical AST: `nodes`, `depth` (a leaf is 1), `operators`
(applications by name, `neg` for unary minus), `features` (sorted), `fixed_literals`,
`free_parameters` (distinct), `parameter_references`, `optimizable_parameters` and `result`. They
feed the degrees-of-freedom accounting of a candidate (C4b) and the report's description.

## Responsibility

One definition of what an expression *is*, what it *means*, and how a definition is evaluated
deterministically: the parse tree, its static type, its normal form, its identities, the
vectorized evaluation of every operator, the C2 availability check and the immutable compiled
definition. `strategy_spec`, `experiments` and `live` consume it; nothing here reads the clock or
a random generator.

## Interfaces

`parse(text) -> Expression`; `typecheck(node) -> ExprType`; `canonicalize(expr)`,
`canonical_text(expr)`, `canonical_form(expr)`; `free_parameters`, `optimizable_parameters`,
`bind`; `structure_id`, `parameterization_id`, `compiled_id_basis`, `compiled_id`;
`structural_metrics`; `evaluate(expr, frame, *, calendar, bar_seconds)`,
`warmup_bars(expr)`, `check_availability(frame, *, bar_seconds)`;
`compile_expression(text_or_expr, *, params, signal_input) -> CompiledSignal` and
`CompiledSignal.evaluate` / `.describe`. The operator table is `OPERATORS`; the grammar, table and
compiler versions are `GRAMMAR_VERSION`, `OPERATOR_TABLE_VERSION` and `COMPILER_VERSION`.

## Extension points

A new operator is a row in `crucible/dsl/operators.py` (with its `min_window` and a precise
summary) plus its result rule in `crucible/dsl/types.py` and its evaluation in
`crucible/dsl/evaluate.py`. A new feature is a row in `crucible/dsl/types.py: FEATURES`, a
documented dimension, and its evaluation (a session feature is added to `SESSION_FEATURES`). All
three bump `OPERATOR_TABLE_VERSION`/`GRAMMAR_VERSION`: the structure id hashes them.

## Timing semantics

A value is decided at the bar's close from the bars up to and including it: every operator shifts
backwards, looks back or recurses forwards, so `evaluate` on `frame[:t+1]` equals `evaluate` on the
whole frame at `t` (a property test). The output's `decision_at` is the bar's `available_at`, which
is what a scheduler may use to release the decision; `minutes_since_open`/`minutes_to_close` use
the session's *published* schedule, which is known in advance, so they add no look-ahead. A null
value means "no signal at this bar" and a caller treats it as flat, never as "hold".

## Known gaps

- `cs_rank` evaluation, cross-sectional similarity and the incremental (live) evaluator with its
  row-by-row parity tests are C4c; `cs_rank` is refused by `evaluate`.
- `strategy_spec` does not compile to the DSL yet; the two languages coexist.
