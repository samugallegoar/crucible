# Module: dsl

## What exists

The expression DSL the no-code path and C4b's evaluator will share (ADR-0096). This package is
**syntax, types and identity only**: no expression is evaluated on data here (that is C4b), and
there is no cross-sectional similarity yet (C4c).

- `grammar.py` — `GRAMMAR_VERSION = "1"`, `tokenize`, `parse`. Whitespace-insensitive recursive
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
  exponents (`close` is price^1, `volume` volume^1, `close/close` price^0) and `time` marks
  `time_of_day`-derived values. Features: `open`, `high`, `low`, `close`, `volume`, `time_of_day`
  (exchange-time minutes since midnight at bar end).
- `operators.py` — the frozen `OPERATORS` table and `OPERATOR_TABLE_VERSION = "1"`: signatures
  and result-type rules only, C4b implements evaluation.
- `params.py` — `FreeParam`, `free_parameters`, `optimizable_parameters`, `bind`.
- `canonical.py` — `canonicalize`, `canonical_text`, `canonical_form`.
- `identity.py` — `structure_id` (`DSX-`), `parameterization_id` (`DSP-`),
  `compiled_id_basis`/`compiled_id` (`DSC-`).
- `metrics.py` — `structural_metrics` -> `StructuralMetrics`.
- `errors.py` — `ExpressionError`, a `ConfigurationError` carrying the column, the token and a
  hint (`docs/CONVENTIONS.md` §9).

### The scale-invariance rule (ADR-0086)

A price *level* is not invariant under a ratio adjustment, so the type checker refuses comparing
one to a constant and refuses mixing dimensions:

- accepted: `volume > 1000`, `time_of_day >= 570`,
  `close/delay(close,1) > 1.01`, `ts_zscore(close, 20) > 1.5`,
  `delta(close,1) > ts_std(close,20)`, `if(close > ts_mean(close,20), 1, -1)`;
- refused: `close > 4500`, `close + 5`, `close > volume`, `ts_rank(close,10) > close`,
  `time_of_day + 1`, `ts_mean(time_of_day, 5)`, `cs_rank(close)`, `cs_rank(volume)`,
  `true + 1`, `ts_mean(5, 3)`, a float/0/2001 window, and a constant root (`1 + 2`).

A fixed literal and a free parameter are dimension-polymorphic only in volume and time, never in
price: `volume > 1000` and `time_of_day >= 570` typecheck, `close > 4500` does not. Unification is
required for `+ - min max`, comparisons and both branches of `if`; `*`/`/` add and subtract
exponents (`*`/`/` never carry time); comparisons yield `bool`; `and`/`or`/`not` need `bool`;
arithmetic on `bool` is refused. `time_of_day` is only comparable to a literal or selected by
`if`; any arithmetic or rolling operator on it is refused. The root may be a condition (`bool`)
or a score (`series`), and `ExprType.price_degree` lets C4b refuse a non-zero-degree score on
ratio-adjusted data.

### The operator table (signatures only; C4b implements)

| Operator | Signature | Result type rule | Version |
|---|---|---|---|
| `delay` | `delay(x, n)` | preserves the dimension of x | 1.0.0 |
| `delta` | `delta(x, n)` | preserves the dimension of x (`x - delay(x, n)`) | 1.0.0 |
| `ts_mean` | `ts_mean(x, n)` | preserves the dimension of x | 1.0.0 |
| `ts_std` | `ts_std(x, n)` | preserves the dimension of x | 1.0.0 |
| `ts_min` | `ts_min(x, n)` | preserves the dimension of x | 1.0.0 |
| `ts_max` | `ts_max(x, n)` | preserves the dimension of x | 1.0.0 |
| `ts_rank` | `ts_rank(x, n)` | dimensionless series in `[0, 1]` | 1.0.0 |
| `ts_zscore` | `ts_zscore(x, n)` | dimensionless series | 1.0.0 |
| `ema` | `ema(x, n)` | preserves the dimension of x | 1.0.0 |
| `cs_rank` | `cs_rank(x)` | dimensionless; x must be dimensionless (price/volume degree 0, not time) | 1.0.0 |
| `abs` | `abs(x)` | preserves the dimension of x | 1.0.0 |
| `sign` | `sign(x)` | dimensionless | 1.0.0 |
| `min` | `min(a, b)` | the unified dimension of a and b | 1.0.0 |
| `max` | `max(a, b)` | the unified dimension of a and b | 1.0.0 |
| `if` | `if(c, a, b)` | the unified type of the two branches | 1.0.0 |

`x` must be a series for the rolling operators (`ts_mean(5, 3)` is refused: a rolling operator
over a constant). A window `n` is an int literal or an int free parameter, `1 <= n <= 2000`; a
parameter in a window position needs a default inside that range, and its bounds, when declared,
must lie inside it too. An unbounded window parameter is allowed: it can be extracted and bound
(`bind` re-validates the window), but it is not optimizable. A float parameter is refused.

### Free parameters

Only `$`-marked values are free; an unmarked literal is fixed and never extracted. A parameter is
declared once (`$n:int[5,200]=20`, `$n=20`, `$n:float[0.1,3.0]=1.5`); its type is the declared one
or inferred from the default. Repeated references bind to that one declaration, and repeated
declarations must be identical (conflicts name both columns). `low`/`high` are both present or
both absent, `low <= default <= high`, and int parameters take int defaults and bounds.
`optimizable` means the declaration carries bounds: an unbounded parameter can be bound but not
swept. `bind(expr, {"n": 30})` returns a new immutable expression with the new default; unknown
names, a wrong type and an out-of-bounds value are refused.

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
`{"param": 0, "type": "int"}`). Both are idempotent.

### The three identities

- `structure_id` = `DSX-` + SHA-256 of grammar version, operator-table version and the canonical
  form. It covers topology, operators, features, fixed literals and parameter placeholders with
  their binding pattern and type, but **not** parameter names, defaults or ranges:
  `ts_mean(close, $n=20)` and `ts_mean(close, $m:int[5,50]=10)` share it, `$a + $a` differs from
  `$a + $b`.
- `parameterization_id` = `DSP-` + SHA-256 of the structure id and `[type, value, low, high]` per
  placeholder in order.
- `compiled_id_basis` returns the canonical dict C4b hashes into `DSC-`: parameterization id,
  compiler version, the semantic version of every operator used and the input dataset
  roles/hashes. `compiled_id` implements the hash; nothing calls it yet.

### Structural metrics

`structural_metrics` runs on the canonical AST: `nodes`, `depth` (a leaf is 1), `operators`
(applications by name, `neg` for unary minus), `features` (sorted), `fixed_literals`,
`free_parameters` (distinct), `parameter_references`, `optimizable_parameters` and `result`. They
feed the degrees-of-freedom accounting of a candidate (C4b) and the report's description.

## Responsibility

One definition of what an expression *is* and what it *means structurally*: the parse tree, its
static type, its normal form and its identities. Evaluation (C4b) consumes this package; nothing
here reads data, the clock or a registry outside `crucible.core.*`.

## Interfaces

`parse(text) -> Expression`; `typecheck(node) -> ExprType`; `canonicalize(expr)`,
`canonical_text(expr)`, `canonical_form(expr)`; `free_parameters`, `optimizable_parameters`,
`bind`; `structure_id`, `parameterization_id`, `compiled_id_basis`, `compiled_id`;
`structural_metrics`. The operator table is `OPERATORS`; the grammar and table versions are
`GRAMMAR_VERSION` and `OPERATOR_TABLE_VERSION`.

## Extension points

A new operator is a row in `crucible/dsl/operators.py` plus its result rule in
`crucible/dsl/types.py` (and, in C4b, its evaluation). A new feature is a row in
`crucible/dsl/types.py: FEATURES` and a documented dimension. Both bump
`OPERATOR_TABLE_VERSION`/`GRAMMAR_VERSION`: the structure id hashes them.

## Timing semantics

None: the DSL never reads data or time. `time_of_day` is defined as exchange-time minutes since
midnight at the bar's end, so C4b can evaluate it from a bar whose `available_at` is the bar end.

## Known gaps

- No evaluation on data yet: C4b implements the operator table, `time_of_day` and the session
  features.
- `cs_rank` evaluation and cross-sectional similarity are C4c.
- Only `time_of_day` exists as a time-like feature; session/seasonality features are C4b.
- `strategy_spec` does not compile to the DSL yet.
