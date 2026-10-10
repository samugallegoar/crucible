"""Price providers (yfinance, Tiingo) behind one interface (ADR-0063).

Providers sit upstream of the dataset store: a fetch normalizes a provider's answer into
``BAR_SCHEMA`` and writes a dataset with ``build_dataset``; a run never calls a provider.
"""
