"""Accounting: append-only ledger, derived portfolio state, PnL, FX, financing, margin.

Money boundary: ledger amounts and fees are ``decimal.Decimal``; prices,
returns, and analytics are floats. Conversion happens exactly once, when a
priced quantity becomes a cash movement on the ledger.
"""
