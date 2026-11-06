"""Dependent-data resampling primitives: the stationary bootstrap and an automatic block length
(ADR-0083).

Every return-series resampling in the research stack (sequence-risk paths, the reality check) draws
its index matrix here, so a block rule is defined once. Pure functions on arrays with an explicit
``numpy.random.Generator``; nothing here touches an engine or a store.

Why the *stationary* bootstrap (Politis & Romano 1994) and not the fixed circular block of
``validation.monte_carlo.BlockBootstrapTest``: a fixed-length circular block bootstrap is not
stationary (the resampled series' second moments depend on the position inside a block); drawing
the block lengths from a geometric distribution restores stationarity, and the single parameter
(the mean block length) can be estimated from the data (Politis & White 2004, with the correction of
Patton, Politis & White 2009) instead of being the arbitrary ``sqrt(n)``. A mean block length of 1
is the ordinary i.i.d. bootstrap.

What it does **not** do: it does not remove volatility clustering from the quantity being studied,
nor make a sample longer than it is. A bootstrap describes the sampling variability of a statistic
of *this* history; it is not evidence that the history is representative.
"""

from __future__ import annotations

import math

import numpy as np

from crucible.core.errors import ConfigurationError

_Z = 2.0
"""The constant ``c`` of the Politis-White lag rule: a lag is insignificant when
``|rho(k)| < c * sqrt(log10(n) / n)``."""


def _as_1d(values: object, name: str) -> np.ndarray:
    arr = np.asarray(values, dtype=np.float64)
    if arr.ndim != 1:
        msg = f"{name} must be a 1-D series, got shape {arr.shape}"
        raise ConfigurationError(msg)
    if not np.all(np.isfinite(arr)):
        msg = f"{name} contains NaN or infinite values; refusing to resample them"
        raise ConfigurationError(msg)
    return arr


def stationary_bootstrap_indices(
    n: int, length: int, mean_block: float, n_paths: int, rng: np.random.Generator
) -> np.ndarray:
    """``(n_paths, length)`` indices into a series of ``n`` observations, drawn by the stationary
    bootstrap: each position either continues the previous index (+1, wrapping around the end of
    the series) or, with probability ``1 / mean_block``, restarts at a uniform random index. Block
    lengths are therefore geometric with mean ``mean_block``; ``mean_block == 1`` restarts every
    position (the i.i.d. bootstrap).

    Vectorized: the index at position ``t`` is the random start of the block that contains ``t``
    plus the offset from that block's first position, modulo ``n``.
    """
    if n < 1:
        msg = f"cannot resample a series of {n} observations"
        raise ConfigurationError(msg)
    if length < 1 or n_paths < 1:
        msg = f"length and n_paths must be >= 1, got length={length}, n_paths={n_paths}"
        raise ConfigurationError(msg)
    if not (mean_block >= 1.0) or not math.isfinite(mean_block):
        msg = f"mean_block must be a finite number >= 1, got {mean_block}"
        raise ConfigurationError(msg)
    starts = rng.integers(0, n, size=(n_paths, length))
    restart = rng.random(size=(n_paths, length)) < (1.0 / mean_block)
    restart[:, 0] = True  # the first position always opens a block
    position = np.arange(length)
    block_open = np.maximum.accumulate(np.where(restart, position, 0), axis=1)
    block_start = np.take_along_axis(starts, block_open, axis=1)
    return (block_start + (position[None, :] - block_open)) % n


def optimal_block_length(series: object) -> float:
    """Mean block length for the stationary bootstrap of ``series`` (Politis & White 2004;
    Patton, Politis & White 2009 correction).

    ``b = (G**2 / g**2) ** (1/3) * n ** (1/3)`` with ``g`` the (flat-top-windowed) long-run
    variance and ``G`` the lag-weighted autocovariance sum; the lag window ``M`` comes from the
    first run of insignificant autocorrelations. Bounded to ``[1, min(3 * sqrt(n), n / 3)]`` (and
    at least 1). An i.i.d. series gives a value near 1; a persistent one gives a longer block.

    Refuses a series shorter than 10 observations, a constant series (no dependence to estimate)
    and non-finite values: a block length from too little data would be a number without meaning.
    """
    x = _as_1d(series, "series")
    n = x.size
    if n < 10:
        msg = f"cannot choose a block length from {n} observations; need >= 10"
        raise ConfigurationError(msg)
    centered = x - x.mean()
    variance = float(np.dot(centered, centered)) / n
    if variance <= 0.0 or not math.isfinite(variance):
        msg = "cannot choose a block length for a constant series (it has no dependence structure)"
        raise ConfigurationError(msg)
    b_max = max(1.0, min(3.0 * math.sqrt(n), n / 3.0))
    k_n = max(5, int(math.log10(n)))
    m_max = min(math.ceil(math.sqrt(n)) + k_n, n - 1)
    gamma = np.empty(m_max + 1)
    for k in range(m_max + 1):
        gamma[k] = float(np.dot(centered[k:], centered[: n - k])) / n
    rho = gamma / gamma[0]
    critical = _Z * math.sqrt(math.log10(n) / n)
    significant = np.abs(rho) >= critical
    m_hat = m_max
    for m in range(0, m_max - k_n + 1):
        if not significant[m + 1 : m + 1 + k_n].any():
            m_hat = m
            break
    window = min(2 * m_hat, m_max)
    if window < 1:
        return 1.0
    lags = np.arange(1, window + 1)
    t = lags / window
    flat_top = np.where(t <= 0.5, 1.0, 2.0 * (1.0 - t))
    g = float(gamma[0] + 2.0 * np.sum(flat_top * gamma[1 : window + 1]))
    big_g = float(2.0 * np.sum(flat_top * lags * gamma[1 : window + 1]))
    if g <= 0.0:
        return 1.0  # a non-positive long-run variance estimate: fall back to no blocking
    block = (big_g * big_g / (g * g)) ** (1.0 / 3.0) * n ** (1.0 / 3.0)
    return float(min(max(block, 1.0), b_max))
