# ADR-0096: The DSL core: typed causal expressions, bounded canonicalization, three identities

- **Status**: accepted
- **Date**: 2026-11-17

## Context

Fathom (PRD §13, milestone C4) needs a formal expression language for signals. It must provide:
- types;
- causal operators only;
- free parameters that can be extracted;
- a canonical form and its hash;
- structural metrics;
- deterministic compilation, reused unchanged by live.

`strategy_spec` is the product's no-code path. Each of its conditions compares two operands, with
no arithmetic and no rolling operators, and it is kept as it is.

The owner approved C4 as three stages, each with its own ADR and PR:
- C4a: the core (this ADR);
- C4b: the operators and compilation;
- C4c: cross-sectional rank, similarity and live parity.

The owner's requirements for C4a are:
- canonicalization stays conservative and never changes evaluation semantics;
- only `$`-marked parameters are free, and an unbounded one is not optimizable;
- the structure, the parameterization and the compiled artifact each get their own identifier;
- scale behaviour (ADR-0086) is carried through the tree, not just operand classes;
- ambiguous expressions are refused, never guessed.

## Decision

1. **A new package, `crucible/dsl/`**, in its own layer of the import contract. It sits below
   `execution | portfolio` and above `accounting | data | orders`. `strategy_spec`, `experiments`
   and `live` can therefore import it, and C4b can read feature availability from `data` (C2 stays
   the single source of truth). In C4a it imports only `crucible.core`.
   `crucible.core.canonical.canonical_json` is moved down from `experiments/artifact_id.py`, which
   re-exports it with identical bytes, so the DSL and the sealed artifacts share one canonical-JSON
   function.
2. **Grammar `GRAMMAR_VERSION = "1"`.**
   - **What it has:**
     - arithmetic `+ - * /` and unary minus;
     - comparisons `> >= < <=`;
     - `and`, `or`, `not`;
     - `if(c, a, b)` and calls from the operator table;
     - the features `open high low close volume time_of_day`;
     - integer and decimal literals;
     - parameters `$name`, optionally declared as `$name:int[5,200]=20`.
   - **What it refuses as ambiguous:**
     - `==` and `!=` on real-valued series;
     - chained comparisons;
     - exponent and bare-dot numbers;
     - unknown names and wrong arity.
3. **Types carry scale.** Each node has a kind (`series`, `bool`, `literal`) and a dimension:
   - the exponent of price (close = 1, close/close = 0, close·close = 2);
   - the exponent of volume;
   - a time flag.

   The rules:
   - Multiplication and division add or subtract the exponents.
   - Addition, subtraction, `min`, `max`, the comparisons and the branches of `if` require the
     dimensions to unify. A literal unifies only with operands of price exponent 0. So `volume > 1000`
     is accepted and `close > 4500` is refused. ADR-0086 is thereby enforced by the type of every
     node, not by classifying the two sides of a comparison as `strategy_spec/scale.py` does.
   - The root's price degree is exposed. C4b refuses a score of non-zero degree on ratio-adjusted
     data.
   - `cs_rank` accepts only dimensionless arguments, never raw prices or volumes.
4. **Operator table `OPERATOR_TABLE_VERSION = "1"`.**
   - The operators are `delay`, `delta`, `ts_mean`, `ts_std`, `ts_min`, `ts_max`, `ts_rank`,
     `ts_zscore`, `ema`, `cs_rank`, `abs`, `sign`, `min`, `max` and `if`.
   - Each declares its signature, its result-type rule and its window arguments.
   - A window is an int literal, or an int parameter whose default and bounds lie in 1..2000.
   - Each operator carries its own semantic version, which goes into the compiled id.
   - C4a declares the signatures; C4b implements them.
5. **Free parameters.**
   - Only `$` marks a free value.
   - The type is declared, or inferred from the default.
   - Bounds come in pairs and contain the default.
   - Every declaration of a name must be identical, and all its references share one binding.
   - A parameter without bounds can be extracted and bound, but it is not optimizable.
6. **Bounded canonicalization.** These rewrites are applied, and the expression is type-checked
   again after them:
   - **Constant folding** of fixed literals only, with float64 arithmetic exactly as evaluation
     would do it. Division by zero and non-finite results are refused, and parameters are never
     folded.
   - **The exact identities** `x*1`, `1*x`, `x/1` and `x-0`.
   - **Double negation:** `-(-x)` and `not not b`.
   - **Sorting** the two direct operands of `+`, `*`, `min` and `max`, using a key in which
     parameters are anonymous.

   What it leaves alone:
   - Nothing is flattened or re-associated, because floating-point addition is not associative.
   - `x + 0` is **kept**. It maps −0.0 to +0.0, which can change a later division or sign, so
     removing it would change evaluation semantics. This is the one place the owner's list ("remove
     identities such as `x + 0`") is narrowed, and it is narrowed for the owner's own constraint.

   Parameters are renumbered `$0, $1, …` by their first occurrence, so repeated and independent
   parameters stay distinct.
7. **Three identities.**
   - `structure_id` (`DSX-`) hashes:
     - the grammar and operator-table versions;
     - the canonical form: operators, topology, features, fixed literals, and typed parameter
       placeholders with their binding pattern.

     It ignores parameter names, defaults and ranges. Variants of one idea therefore share it.
   - `parameterization_id` (`DSP-`) adds each placeholder's type, value and bounds.
   - `compiled_id` (`DSC-`) is defined here and built in C4b. It adds the compiler version, the
     semantic version of every operator used, and the input datasets.
8. **Structural metrics** on the canonical tree:
   - nodes and depth;
   - operator counts and features;
   - fixed literals;
   - distinct, referenced and optimizable parameters;
   - the result type.

## Alternatives considered

- **Extend `strategy_spec` into the DSL.** Its models are a product contract with stable hashes,
  and they sit above the layer that live needs. Rejected; a later step may compile specs to the DSL.
- **Reuse `strategy_spec/scale.py`.** It sits in a higher layer and classifies operand kinds only,
  not degrees through arithmetic. Rejected in favour of exponents on every node.
- **Full algebraic simplification** (associativity, distribution, `x+0`). It changes floating-point
  results and null behaviour, and the canonical form would become unpredictable. Rejected.
- **One hash for everything.** It cannot group variants of one structure or tell a reparameterization
  from a new idea. Rejected for three ids.

## Consequences

- **Grouping and deduplication work on `structure_id`; reproducibility uses `parameterization_id`.**
  Every later stage relies on this: C5 batches, C6 trial counts, C7 perturbation.
- **Some expressions that `strategy_spec` accepts are refused.** A literal compared with a
  dimensionless indicator is fine in both. A price compared with a literal is refused by the DSL
  on every input; `strategy_spec` refuses it only on adjusted data.
- **Version bumps.** Changing the grammar or the operator table changes `structure_id`, so it
  requires a version bump and a CHANGELOG entry.
