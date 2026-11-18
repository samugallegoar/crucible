"""The versioned CME Globex session table for the equity-index futures (Fathom C3b, ADR-0091).

Every entry is transcribed from a CME (or CFTC-filed) document, cited by key in ``SOURCES``
with the SHA-256 of the bytes read. Times are ``America/Chicago`` wall clock. Read with
``crucible.data.cme_sessions.SessionCalendar``; never edit an entry without its source, and bump
``TABLE_VERSION`` on any change (a run records the version and the table hash).

Coverage: ES/NQ/YM from trade date 2010-06-07 (the first raw bar, ADR-0085), RTY from 2017-07-10
(the CME contract's first bar), NKD from 2012-11-19 (the first schedule that names it; the 2010-2012
holiday documents carry NKD-specific exceptions that are not transcribed), to 2027-12-31 (the end
of CME's published schedule when retrieved). Holidays of 2023 (except Labor Day, Christmas and New
Year) and Martin Luther King Day 2024 are ``unsourced``: their published schedules were not
archived, and the sessions touching them are built from the regime and flagged unverified.
"""

from __future__ import annotations

import datetime as dt

from crucible.data.cme_sessions import (
    NoTradeDate,
    ScheduleSource,
    SessionOverride,
    SessionRegime,
    SessionTable,
    UnscheduledEvent,
    UnsourcedWindow,
)

TABLE_VERSION = "cme-equity-sessions-1"
RETRIEVED = "2026-11-17"

ALL = frozenset({"ES", "NQ", "YM", "RTY", "NKD"})
US = frozenset({"ES", "NQ", "YM", "RTY"})
NKD = frozenset({"NKD"})

_CME = "https://www.cmegroup.com"
_HOL = f"{_CME}/tools-information/holiday-calendar/files/"
_WB = "https://web.archive.org/web/"


def _t(text: str) -> dt.time:
    h, m = text.split(":")
    return dt.time(int(h), int(m))


def _d(text: str) -> dt.date:
    return dt.date.fromisoformat(text)


def _w(text: str) -> dt.datetime:
    return dt.datetime.fromisoformat(text)  # naive Chicago wall clock, by design


# --- sources ---------------------------------------------------------------------------------

_REGIME_SOURCES = (
    ScheduleSource(
        key="cme-eq-trading-hours",
        title="CME Group equity index products: current and new CME Globex trading hours",
        publisher="CME Group",
        url="http://www.cmegroup.com/education/files/eq-trading-hours.pdf",
        retrieved=RETRIEVED,
        published="2012-11",
        archive_url=f"{_WB}20140822112713/http://www.cmegroup.com/education/files/eq-trading-hours.pdf",
        sha256="034558fe3682b2338a826b0e9dca249b7a0fe544066391d65bc3395836092497",
    ),
    ScheduleSource(
        key="cme-ser-6465",
        title="SER-6465 New Trading Hours: Equity Index Futures & Options on Equity Index Futures "
        "on Monday, November 19, 2012",
        publisher="CME Group",
        url=(
            f"{_CME}/rulebook/files/"
            "ser-6465_Equity_Index_Futures_Options_on_Equity_Index_Futures_20121114.pdf"
        ),
        retrieved=RETRIEVED,
        published="2012-11-14",
        archive_url=(
            f"{_WB}20130412064716/http://www.cmegroup.com/rulebook/files/"
            "ser-6465_Equity_Index_Futures_Options_on_Equity_Index_Futures_20121114.pdf"
        ),
        sha256="e914dd32e7c7bbdc4147fd12fb920ea358f2cc1009d0792c570fe9f4cc7a4e07",
    ),
    ScheduleSource(
        key="cme-ser-6554r",
        title="SER-6554R Modification of Trading Hours for CME International Equity Index Futures, "
        "effective Monday, March 4, 2013",
        publisher="CME Group",
        url=f"{_CME}/tools-information/lookups/advisories/market-regulation/SER-6554R.html",
        retrieved=RETRIEVED,
        published="2013-02-21",
        archive_url=(
            f"{_WB}20191213210834/https://www.cmegroup.com/tools-information/lookups/advisories/"
            "market-regulation/SER-6554R.html"
        ),
        sha256="826a3490c4e027bdb002d2628b6d2770c0485234da410b22ca0f891a5d58e341",
    ),
    ScheduleSource(
        key="cme-globex-notice-20150907",
        title="CME Globex Notices, September 7, 2015: Changes to Daily Maintenance Period for CME "
        "Globex (CME and CBOT equity close 16:00 CT from Monday, September 21)",
        publisher="CME Group",
        url=f"{_CME}/tools-information/lookups/advisories/electronic-trading/20150907.html",
        retrieved=RETRIEVED,
        published="2015-09-07",
        archive_url=(
            f"{_WB}20151027030439/http://www.cmegroup.com/tools-information/lookups/advisories/"
            "electronic-trading/20150907.html"
        ),
        sha256="c53ec27a927a5f253a7902322cb376afe028d66f31e7526168da05e324a151ad",
    ),
    ScheduleSource(
        key="cftc-cme-20-244",
        title="CME Submission 20-244: Elimination of the CME Globex trading halt for all CME and "
        "CBOT equity futures and options, effective trade date Monday, June 28, 2021",
        publisher="CME Group (filed with the CFTC)",
        url="https://cftc.gov/filings/orgrules/rule061421cmedcm002.pdf",
        retrieved=RETRIEVED,
        published="2021-06-11",
        sha256="5e3058bcf41de9894cb2a6c29ae59cfce0fe3821a7ed1c8aa8531237fd194ab8",
    ),
)

_SPECIAL_SOURCES = (
    ScheduleSource(
        key="cme-pr-20121028-sandy",
        title="Media alert: CME Group to close U.S. equity index futures and options on futures "
        "Monday (Hurricane Sandy)",
        publisher="CME Group",
        url=f"{_CME}/media-room/press-releases/2012/10/28/"
        "media_alert_cme_grouptocloseusequityindexfuturesandoptionsonfutu.html",
        retrieved=RETRIEVED,
        published="2012-10-28",
    ),
    ScheduleSource(
        key="cme-pr-20121029-sandy",
        title="CME Group to reopen U.S. equity index and interest rate complexes tonight",
        publisher="CME Group",
        url=f"{_CME}/media-room/press-releases/2012/10/29/"
        "cme_group_to_reopenusequityindexandinterestratecomplexestonight.html",
        retrieved=RETRIEVED,
        published="2012-10-29",
    ),
    ScheduleSource(
        key="cme-pr-20121030-sandy",
        title="CME Group to reopen U.S. equity index complex tonight, resume normal trading hours",
        publisher="CME Group",
        url="https://investor.cmegroup.com/news-releases/news-release-details/"
        "cme-group-reopen-us-equity-index-complex-tonight-resume-normal",
        retrieved=RETRIEVED,
        published="2012-10-30",
    ),
    ScheduleSource(
        key="cme-ser-8289",
        title="SER-8289 National Day of Mourning for former President George H. W. Bush",
        publisher="CME Group",
        url=f"{_CME}/notices/ser/2018/12/SER-8289.pdf",
        retrieved=RETRIEVED,
        published="2018-12-03",
        sha256="04f7ad6b22bac974bcb26388f70b34c505b4d9530c8ecd480b960123b0ee583d",
    ),
    ScheduleSource(
        key="cme-pr-20241230-carter",
        title="CME Group announces trading hours for U.S. National Day of Mourning to honor former "
        "President Jimmy Carter",
        publisher="CME Group",
        url=f"{_CME}/media-room/press-releases/2025/12/30/"
        "cme_group_announcestradinghoursforusnationaldayofmourningtohonor.html",
        retrieved=RETRIEVED,
        published="2024-12-30",
    ),
)

_API_SOURCES = (
    ScheduleSource(
        key="cme-api-live-2026-11-17",
        title="CME Group trading-hours-by-product service, ids 133 ES, 146 NQ, 318 YM, 8314 RTY, "
        "168 NKD, event dates 2025-11-01..2027-12-31 (data from 2025-11-17)",
        publisher="CME Group",
        url=f"{_CME}/services/trading-hours-by-product?id=133,146,318,8314,168",
        retrieved="2026-11-17T22:10:06Z",
        sha256="a19fca133bca4d49ea8cd5d747cd34ba04a12199148078781e87272813a5a46a",
    ),
    ScheduleSource(
        key="cme-api-wayback-2023-2025",
        title="Wayback Machine captures of the CME trading-hours-by-product service (ES, id 133) "
        "for holiday windows 2023-09..2026-01",
        publisher="CME Group (archived by the Internet Archive)",
        url=f"{_CME}/services/trading-hours-by-product",
        retrieved=RETRIEVED,
        archive_url="https://web.archive.org/cdx/search/cdx?url=cmegroup.com/services/trading-hours-by-product",
    ),
)


def _holiday_source(
    key: str, title: str, file: str, sha256: str, zip_year: int | None
) -> ScheduleSource:
    archive = (
        f"{_WB}*/{_HOL}{zip_year}-holiday-calendars.zip" if zip_year else f"{_WB}*/{_HOL}{file}"
    )
    return ScheduleSource(
        key=key,
        title=title,
        publisher="CME Group",
        url=f"{_HOL}{file}",
        retrieved=RETRIEVED,
        archive_url=archive,
        sha256=sha256,
    )


# --- regimes ---------------------------------------------------------------------------------

REGIMES = (
    SessionRegime(
        name="globex-2010",
        roots=frozenset({"ES", "NQ", "YM"}),
        first_trade_date=_d("2010-06-07"),
        last_trade_date=_d("2012-11-16"),
        open_previous_day=_t("15:30"),
        close=_t("15:15"),
        breaks=((_t("16:30"), _t("17:00")),),
        sources=("cme-eq-trading-hours",),
    ),
    SessionRegime(
        name="globex-2012-11",
        roots=frozenset({"ES", "NQ", "YM"}),
        first_trade_date=_d("2012-11-19"),
        last_trade_date=_d("2015-09-18"),
        open_previous_day=_t("17:00"),
        close=_t("16:15"),
        breaks=((_t("15:15"), _t("15:30")),),
        sources=("cme-ser-6465", "cme-eq-trading-hours"),
    ),
    SessionRegime(
        name="globex-2012-11-nkd",
        roots=NKD,
        first_trade_date=_d("2012-11-19"),
        last_trade_date=_d("2013-03-01"),
        open_previous_day=_t("17:00"),
        close=_t("16:15"),
        breaks=((_t("15:15"), _t("15:30")),),
        sources=("cme-ser-6465",),
    ),
    SessionRegime(
        name="globex-2013-03-nkd",
        roots=NKD,
        first_trade_date=_d("2013-03-04"),
        last_trade_date=_d("2015-09-18"),
        open_previous_day=_t("17:00"),
        close=_t("16:15"),
        breaks=(),
        sources=("cme-ser-6554r",),
    ),
    SessionRegime(
        name="globex-2015-09",
        roots=US,
        first_trade_date=_d("2015-09-21"),
        last_trade_date=_d("2021-06-25"),
        open_previous_day=_t("17:00"),
        close=_t("16:00"),
        breaks=((_t("15:15"), _t("15:30")),),
        sources=("cme-globex-notice-20150907", "cme-ser-6465"),
    ),
    SessionRegime(
        name="globex-2015-09-nkd",
        roots=NKD,
        first_trade_date=_d("2015-09-21"),
        last_trade_date=None,
        open_previous_day=_t("17:00"),
        close=_t("16:00"),
        breaks=(),
        sources=("cme-globex-notice-20150907", "cme-ser-6554r"),
    ),
    SessionRegime(
        name="globex-2021-06",
        roots=US,
        first_trade_date=_d("2021-06-28"),
        last_trade_date=None,
        open_previous_day=_t("17:00"),
        close=_t("16:00"),
        breaks=(),
        sources=("cftc-cme-20-244", "cme-globex-notice-20150907"),
    ),
)

COVERAGE = {
    "ES": (_d("2010-06-07"), _d("2027-12-31")),
    "NQ": (_d("2010-06-07"), _d("2027-12-31")),
    "YM": (_d("2010-06-07"), _d("2027-12-31")),
    "RTY": (_d("2017-07-10"), _d("2027-12-31")),
    "NKD": (_d("2012-11-19"), _d("2027-12-31")),
}


# --- per-trade-date entries ------------------------------------------------------------------

_Session = tuple[str | None, str | None, tuple[tuple[str, str], ...]]


class _Builder:
    def __init__(self) -> None:
        self.overrides: list[SessionOverride] = []
        self.closed: list[NoTradeDate] = []
        self.unsourced: list[UnsourcedWindow] = []

    def add(
        self,
        source: str,
        note: str,
        *,
        closed: tuple[str, ...] = (),
        sessions: dict[str, _Session] | None = None,
        kind: str = "holiday",
        roots: frozenset[str] = ALL,
        unsourced_for: frozenset[str] = frozenset(),
    ) -> None:
        """``unsourced_for``: roots the source does not cover; every session whose calendar days
        reach the entry's dates (the evening before each) is unverified for them."""
        days = sorted({_d(d) for d in closed} | {_d(d) for d in (sessions or {})})
        if unsourced_for and days:
            self.unsourced.append(
                UnsourcedWindow(
                    days[0] - dt.timedelta(days=1),
                    days[-1] - dt.timedelta(days=1),
                    unsourced_for,
                    f"{note}: {source} covers {sorted(roots)} only",
                )
            )
        for day in closed:
            self.closed.append(NoTradeDate(date=_d(day), roots=roots, source=source, note=note))
        for day, (opened, closed_at, halts) in (sessions or {}).items():
            self.overrides.append(
                SessionOverride(
                    trade_date=_d(day),
                    roots=roots,
                    source=source,
                    kind="special" if kind == "special" else "holiday",
                    note=note,
                    open=_w(opened) if opened else None,
                    close=_w(closed_at) if closed_at else None,
                    halts=tuple((_w(a), _w(b)) for a, b in halts),
                )
            )


def _h(a: str, b: str) -> tuple[tuple[str, str], ...]:
    return ((a, b),)


B = _Builder()

# 2010-2011: the annual holiday-calendar zips (PDF schedules). Monday holidays: Sunday 17:00 open
# for Tuesday's trade date, halt 10:30-17:00 on the holiday.
B.add(
    "cme-hol-2010-07-04",
    "Independence Day (observed Mon 2010-07-05)",
    closed=("2010-07-05",),
    sessions={"2010-07-06": ("2010-07-04 17:00", None, _h("2010-07-05 10:30", "2010-07-05 17:00"))},
)
B.add(
    "cme-hol-2010-labor",
    "Labor Day",
    closed=("2010-09-06",),
    sessions={"2010-09-07": ("2010-09-05 17:00", None, _h("2010-09-06 10:30", "2010-09-06 17:00"))},
)
B.add(
    "cme-hol-2010-thanksgiving",
    "Thanksgiving",
    closed=("2010-11-25",),
    sessions={
        "2010-11-26": (
            "2010-11-24 15:30",
            "2010-11-26 12:15",
            _h("2010-11-25 10:30", "2010-11-25 17:00"),
        )
    },
)
B.add("cme-hol-2010-christmas", "Christmas (observed Fri 2010-12-24)", closed=("2010-12-24",))
B.add(
    "cme-hol-2011-mlk",
    "Martin Luther King Jr. Day",
    closed=("2011-01-17",),
    sessions={"2011-01-18": ("2011-01-16 17:00", None, _h("2011-01-17 10:30", "2011-01-17 17:00"))},
)
B.add(
    "cme-hol-2011-presidents",
    "Presidents Day",
    closed=("2011-02-21",),
    sessions={"2011-02-22": ("2011-02-20 17:00", None, _h("2011-02-21 10:30", "2011-02-21 17:00"))},
)
B.add("cme-hol-2011-good-friday", "Good Friday", closed=("2011-04-22",))
B.add(
    "cme-hol-2011-memorial",
    "Memorial Day",
    closed=("2011-05-30",),
    sessions={"2011-05-31": ("2011-05-29 17:00", None, _h("2011-05-30 10:30", "2011-05-30 17:00"))},
)
B.add(
    "cme-hol-2011-07-04",
    "Independence Day",
    closed=("2011-07-04",),
    sessions={"2011-07-05": ("2011-07-03 17:00", None, _h("2011-07-04 10:30", "2011-07-04 17:00"))},
)
B.add(
    "cme-hol-2011-labor",
    "Labor Day",
    closed=("2011-09-05",),
    sessions={"2011-09-06": ("2011-09-04 17:00", None, _h("2011-09-05 10:30", "2011-09-05 17:00"))},
)
B.add(
    "cme-hol-2011-thanksgiving",
    "Thanksgiving",
    closed=("2011-11-24",),
    sessions={
        "2011-11-25": (
            "2011-11-23 15:30",
            "2011-11-25 12:15",
            _h("2011-11-24 10:30", "2011-11-24 17:00"),
        )
    },
)
B.add(
    "cme-hol-2011-christmas",
    "Christmas (observed Mon 2011-12-26); Tuesday opens 05:00",
    closed=("2011-12-26",),
    sessions={"2011-12-27": ("2011-12-27 05:00", None, ())},
)
B.add(
    "cme-hol-2012-new-year",
    "New Year (observed Mon 2012-01-02); Tuesday opens 05:00",
    closed=("2012-01-02",),
    sessions={"2012-01-03": ("2012-01-03 05:00", None, ())},
)

# Special closures: announced days (Sandy: hours) ahead in CME notices.
B.add(
    "cme-pr-20121028-sandy",
    "Hurricane Sandy: equity index close 08:15",
    kind="special",
    roots=US,
    sessions={"2012-10-29": (None, "2012-10-29 08:15", ())},
)
B.add(
    "cme-pr-20121029-sandy",
    "Hurricane Sandy: reopen 17:00 for overnight trading, close 08:15",
    kind="special",
    roots=US,
    sessions={"2012-10-30": ("2012-10-29 17:00", "2012-10-30 08:15", ())},
)
B.add(
    "cme-pr-20121030-sandy",
    "Hurricane Sandy: reopen 17:00, normal hours",
    kind="special",
    roots=US,
    sessions={"2012-10-31": ("2012-10-30 17:00", None, ())},
)
B.add(
    "cme-ser-8289",
    "National Day of Mourning (G. H. W. Bush): U.S. equity close 08:30",
    kind="special",
    roots=US,
    sessions={"2018-12-05": (None, "2018-12-05 08:30", ())},
)
B.add(
    "cme-pr-20241230-carter",
    "National Day of Mourning (J. Carter): U.S. equity open until 08:30",
    kind="special",
    roots=US,
    sessions={"2025-01-09": (None, "2025-01-09 08:30", ())},
)

# 2023-2025: Wayback captures of the CME trading-hours service for ES only. They apply to the
# four U.S. roots (one schedule in every holiday document); NKD differs on U.S. early closes, so its
# dates are unsourced windows.
_WBK = "cme-api-wayback-2023-2025"
B.add(
    _WBK,
    "Labor Day 2023",
    closed=("2023-09-04",),
    sessions={"2023-09-05": ("2023-09-03 17:00", None, _h("2023-09-04 12:00", "2023-09-04 17:00"))},
    roots=US,
    unsourced_for=NKD,
)
B.add(
    _WBK,
    "Christmas (observed Mon 2023-12-25)",
    closed=("2023-12-25",),
    sessions={"2023-12-26": ("2023-12-25 17:00", None, ())},
    roots=US,
    unsourced_for=NKD,
)
B.add(
    _WBK,
    "New Year 2024",
    closed=("2024-01-01",),
    sessions={"2024-01-02": ("2024-01-01 17:00", None, ())},
    roots=US,
    unsourced_for=NKD,
)
B.add(
    _WBK,
    "Presidents Day 2024",
    closed=("2024-02-19",),
    sessions={"2024-02-20": ("2024-02-18 17:00", None, _h("2024-02-19 12:00", "2024-02-19 17:00"))},
    roots=US,
    unsourced_for=NKD,
)
B.add(_WBK, "Good Friday 2024", closed=("2024-03-29",), roots=US, unsourced_for=NKD)
B.add(
    _WBK,
    "Memorial Day 2024",
    closed=("2024-05-27",),
    sessions={"2024-05-28": ("2024-05-26 17:00", None, _h("2024-05-27 12:00", "2024-05-27 17:00"))},
    roots=US,
    unsourced_for=NKD,
)
B.add(
    _WBK,
    "Juneteenth 2024 (Wed)",
    closed=("2024-06-19",),
    sessions={"2024-06-20": ("2024-06-18 17:00", None, _h("2024-06-19 12:00", "2024-06-19 17:00"))},
    roots=US,
    unsourced_for=NKD,
)
B.add(
    _WBK,
    "Independence Day 2024 (Thu)",
    closed=("2024-07-04",),
    sessions={
        "2024-07-03": (None, "2024-07-03 12:15", ()),
        "2024-07-05": ("2024-07-03 17:00", None, _h("2024-07-04 12:00", "2024-07-04 17:00")),
    },
    roots=US,
    unsourced_for=NKD,
)
B.add(
    _WBK,
    "Labor Day 2024",
    closed=("2024-09-02",),
    sessions={"2024-09-03": ("2024-09-01 17:00", None, _h("2024-09-02 12:00", "2024-09-02 17:00"))},
    roots=US,
    unsourced_for=NKD,
)
B.add(
    _WBK,
    "Thanksgiving 2024",
    closed=("2024-11-28",),
    sessions={
        "2024-11-29": (
            "2024-11-27 17:00",
            "2024-11-29 12:15",
            _h("2024-11-28 12:00", "2024-11-28 17:00"),
        )
    },
    roots=US,
    unsourced_for=NKD,
)
B.add(
    _WBK,
    "Christmas 2024",
    closed=("2024-12-25",),
    sessions={
        "2024-12-24": (None, "2024-12-24 12:15", ()),
        "2024-12-26": ("2024-12-25 17:00", None, ()),
    },
    roots=US,
    unsourced_for=NKD,
)
B.add(
    _WBK,
    "New Year 2025",
    closed=("2025-01-01",),
    sessions={"2025-01-02": ("2025-01-01 17:00", None, ())},
    roots=US,
    unsourced_for=NKD,
)
B.add(
    _WBK,
    "Martin Luther King Jr. Day 2025",
    closed=("2025-01-20",),
    sessions={"2025-01-21": ("2025-01-19 17:00", None, _h("2025-01-20 12:00", "2025-01-20 17:00"))},
    roots=US,
    unsourced_for=NKD,
)
B.add(
    _WBK,
    "Presidents Day 2025",
    closed=("2025-02-17",),
    sessions={"2025-02-18": ("2025-02-16 17:00", None, _h("2025-02-17 12:00", "2025-02-17 17:00"))},
    roots=US,
    unsourced_for=NKD,
)
B.add(_WBK, "Good Friday 2025", closed=("2025-04-18",), roots=US, unsourced_for=NKD)
B.add(
    _WBK,
    "Memorial Day 2025",
    closed=("2025-05-26",),
    sessions={"2025-05-27": ("2025-05-25 17:00", None, _h("2025-05-26 12:00", "2025-05-26 17:00"))},
    roots=US,
    unsourced_for=NKD,
)
B.add(
    _WBK,
    "Juneteenth 2025 (Thu)",
    closed=("2025-06-19",),
    sessions={"2025-06-20": ("2025-06-18 17:00", None, _h("2025-06-19 12:00", "2025-06-19 17:00"))},
    roots=US,
    unsourced_for=NKD,
)
B.add(
    _WBK,
    "Independence Day 2025 (Fri): Thursday 12:15 close, Friday its own trade date to 12:00",
    sessions={
        "2025-07-03": (None, "2025-07-03 12:15", ()),
        "2025-07-04": ("2025-07-03 17:00", "2025-07-04 12:00", ()),
    },
    roots=US,
    unsourced_for=NKD,
)
B.add(
    _WBK,
    "Labor Day 2025",
    closed=("2025-09-01",),
    sessions={"2025-09-02": ("2025-08-31 17:00", None, _h("2025-09-01 12:00", "2025-09-01 17:00"))},
    roots=US,
    unsourced_for=NKD,
)

# 2025-11 .. 2027-12: the live CME trading-hours service (all five products identical).
_API = "cme-api-live-2026-11-17"
B.add(
    _API,
    "Thanksgiving 2025",
    closed=("2025-11-27",),
    sessions={
        "2025-11-28": (
            "2025-11-26 17:00",
            "2025-11-28 12:15",
            _h("2025-11-27 12:00", "2025-11-27 17:00"),
        )
    },
)
B.add(
    _API,
    "Christmas 2025",
    closed=("2025-12-25",),
    sessions={
        "2025-12-24": (None, "2025-12-24 12:15", ()),
        "2025-12-26": ("2025-12-25 17:00", None, ()),
    },
)
B.add(
    _API,
    "New Year 2026",
    closed=("2026-01-01",),
    sessions={"2026-01-02": ("2026-01-01 17:00", None, ())},
)
B.add(
    _API,
    "Martin Luther King Jr. Day 2026",
    closed=("2026-01-19",),
    sessions={"2026-01-20": ("2026-01-18 17:00", None, _h("2026-01-19 12:00", "2026-01-19 17:00"))},
)
B.add(
    _API,
    "Presidents Day 2026",
    closed=("2026-02-16",),
    sessions={"2026-02-17": ("2026-02-15 17:00", None, _h("2026-02-16 12:00", "2026-02-16 17:00"))},
)
B.add(
    _API,
    "Good Friday 2026: early close 08:15",
    sessions={"2026-04-03": (None, "2026-04-03 08:15", ())},
)
B.add(
    _API,
    "Memorial Day 2026",
    closed=("2026-05-25",),
    sessions={"2026-05-26": ("2026-05-24 17:00", None, _h("2026-05-25 12:00", "2026-05-25 17:00"))},
)
B.add(
    _API,
    "Juneteenth 2026 (Fri): Thursday 17:00 opens Monday's trade date, Friday halt 12:00",
    closed=("2026-06-19",),
    sessions={"2026-06-22": ("2026-06-18 17:00", None, _h("2026-06-19 12:00", "2026-06-21 17:00"))},
)
B.add(
    _API,
    "Independence Day 2026 (observed Fri 07-03): Thursday 17:00 opens Monday's trade date",
    closed=("2026-07-03",),
    sessions={"2026-07-06": ("2026-07-02 17:00", None, _h("2026-07-03 12:00", "2026-07-05 17:00"))},
)
B.add(
    _API,
    "Labor Day 2026",
    closed=("2026-09-07",),
    sessions={"2026-09-08": ("2026-09-06 17:00", None, _h("2026-09-07 12:00", "2026-09-07 17:00"))},
)
B.add(
    _API,
    "Thanksgiving 2026",
    closed=("2026-11-26",),
    sessions={
        "2026-11-27": (
            "2026-11-25 17:00",
            "2026-11-27 12:15",
            _h("2026-11-26 12:00", "2026-11-26 17:00"),
        )
    },
)
B.add(
    _API,
    "Christmas 2026 (Fri)",
    closed=("2026-12-25",),
    sessions={"2026-12-24": (None, "2026-12-24 12:15", ())},
)
B.add(_API, "New Year 2027 (Fri)", closed=("2027-01-01",))
B.add(
    _API,
    "Martin Luther King Jr. Day 2027",
    closed=("2027-01-18",),
    sessions={"2027-01-19": ("2027-01-17 17:00", None, _h("2027-01-18 12:00", "2027-01-18 17:00"))},
)
B.add(
    _API,
    "Presidents Day 2027",
    closed=("2027-02-15",),
    sessions={"2027-02-16": ("2027-02-14 17:00", None, _h("2027-02-15 12:00", "2027-02-15 17:00"))},
)
B.add(_API, "Good Friday 2027", closed=("2027-03-26",))
B.add(
    _API,
    "Memorial Day 2027",
    closed=("2027-05-31",),
    sessions={"2027-06-01": ("2027-05-30 17:00", None, _h("2027-05-31 12:00", "2027-05-31 17:00"))},
)
B.add(
    _API,
    "Juneteenth 2027 (observed Fri 06-18): Thursday 17:00 opens Monday's trade date",
    closed=("2027-06-18",),
    sessions={"2027-06-21": ("2027-06-17 17:00", None, _h("2027-06-18 12:00", "2027-06-20 17:00"))},
)
B.add(
    _API,
    "Independence Day 2027 (observed Mon 07-05)",
    closed=("2027-07-05",),
    sessions={"2027-07-06": ("2027-07-04 17:00", None, _h("2027-07-05 12:00", "2027-07-05 17:00"))},
)
B.add(
    _API,
    "Labor Day 2027",
    closed=("2027-09-06",),
    sessions={"2027-09-07": ("2027-09-05 17:00", None, _h("2027-09-06 12:00", "2027-09-06 17:00"))},
)
B.add(
    _API,
    "Thanksgiving 2027",
    closed=("2027-11-25",),
    sessions={
        "2027-11-26": (
            "2027-11-24 17:00",
            "2027-11-26 12:15",
            _h("2027-11-25 12:00", "2027-11-25 17:00"),
        )
    },
)
B.add(_API, "Christmas 2027 (observed Fri 12-24)", closed=("2027-12-24",))

UNSOURCED = (
    UnsourcedWindow(
        _d("2023-01-15"),
        _d("2023-01-16"),
        ALL,
        "Martin Luther King Jr. Day 2023: no archived schedule",
    ),
    UnsourcedWindow(
        _d("2023-02-19"), _d("2023-02-20"), ALL, "Presidents Day 2023: no archived schedule"
    ),
    UnsourcedWindow(
        _d("2023-04-06"),
        _d("2023-04-07"),
        ALL,
        "Good Friday 2023: the clearing advisory confirms an abbreviated equity session, "
        "its close time is not archived",
    ),
    UnsourcedWindow(
        _d("2023-05-28"), _d("2023-05-29"), ALL, "Memorial Day 2023: no archived schedule"
    ),
    UnsourcedWindow(
        _d("2023-06-18"), _d("2023-06-19"), ALL, "Juneteenth 2023: no archived schedule"
    ),
    UnsourcedWindow(
        _d("2023-07-02"), _d("2023-07-04"), ALL, "Independence Day 2023: no archived schedule"
    ),
    UnsourcedWindow(
        _d("2023-11-22"), _d("2023-11-23"), ALL, "Thanksgiving 2023: no archived schedule"
    ),
    UnsourcedWindow(
        _d("2024-01-14"),
        _d("2024-01-15"),
        ALL,
        "Martin Luther King Jr. Day 2024: no archived schedule",
    ),
)

UNSCHEDULED = (
    UnscheduledEvent(
        trade_date=_d("2025-11-28"),
        roots=ALL,
        source=_API,
        note="CME Globex outage (data-centre cooling failure) from the evening of 2025-11-27; the "
        "service later shows a 07:30 reopen. The scheduled session is kept: the missing bars are a "
        "data gap, not a schedule.",
    ),
)

CONFLICTS = (
    "2013 Martin Luther King Jr. Day: the draft 2013-martin-luther-king-done.docx gives a 15:15 "
    "close, the published PDF 16:15; the published PDF is used.",
    "2026-06-20, 2026-07-04, 2027-06-19 (Saturdays): the live service lists 'open 05:00 / closed "
    "17:00' events for the next trade date; no Saturday session exists for these products and "
    "the entries are ignored as a feed artefact.",
)

_HOLIDAY_FILES: tuple[tuple[str, str, str, str, int | None], ...] = (
    (
        "cme-hol-2010-07-04",
        "Fourth of July Holiday Schedule 2010",
        "2010-4th-of-july.pdf",
        "5f0d1c8523f54dc20c760813201451af4fb3002baf5f45f29ffa62b936d50359",
        2010,
    ),
    (
        "cme-hol-2010-labor",
        "Labor Day Holiday Schedule 2010",
        "2010-labor-day.pdf",
        "7162c915c88324287c194760f0d14494db3b983ef03cbb94d2e7495fe7245c58",
        2010,
    ),
    (
        "cme-hol-2010-thanksgiving",
        "Thanksgiving Holiday Schedule 2010",
        "2010-thanksgiving.pdf",
        "d050b814d9d6c7646c1751e0d3783567c477a91541d4e921971dccb10370d376",
        2010,
    ),
    (
        "cme-hol-2010-christmas",
        "Christmas Holiday Schedule 2010",
        "2010-christmas.pdf",
        "09e9f6433be118a898388334733cc0a689ca8324c06c503e550600065b1463c4",
        2010,
    ),
    (
        "cme-hol-2011-mlk",
        "Martin Luther King Holiday Schedule 2011",
        "2011-martin-luther-king-done.pdf",
        "e7ff2274c65e061b4239c0bae9495524d988bc2f217b81a7421e2e038dd42661",
        2011,
    ),
    (
        "cme-hol-2011-presidents",
        "President's Day Holiday Schedule 2011",
        "2011-presidents-day-done.pdf",
        "c9f1012fbcba729bd6c0a3663adc0de774349de9ed97f6d65a16742836da34eb",
        2011,
    ),
    (
        "cme-hol-2011-good-friday",
        "Good Friday Holiday Schedule 2011",
        "2011-good-friday-done.pdf",
        "8e815e092690cf27cfa862eaa509104024b5091b0e28b48ed41651975354acdb",
        2011,
    ),
    (
        "cme-hol-2011-memorial",
        "Memorial Day Holiday Schedule 2011",
        "2011-memorial-day-done.pdf",
        "8c1e18db41299d57d1207b811107544afd1181c067cce8b12726d9eebea70a33",
        2011,
    ),
    (
        "cme-hol-2011-07-04",
        "Fourth of July Holiday Schedule 2011",
        "2011-4th-of-july-done.pdf",
        "28c499845a3d863dd075d2592a6ec7f3e08fcea550ca0c2245f86a2bad807abe",
        2011,
    ),
    (
        "cme-hol-2011-labor",
        "Labor Day Holiday Schedule 2011",
        "2011-labor-day-done.pdf",
        "76632b66309d025a1e35e92729e8c0822e4cb7bb1b963a2760f79f6218fa9f17",
        2011,
    ),
    (
        "cme-hol-2011-thanksgiving",
        "Thanksgiving Holiday Schedule 2011",
        "2011-thanksgiving-done.pdf",
        "3fc2a5cb23a53f0a08b94f01eb181c7547f6909f10ed67ae7611539e4de5fe8f",
        2011,
    ),
    (
        "cme-hol-2011-christmas",
        "Christmas Holiday Schedule 2011",
        "2011-christmas  (2).pdf",
        "29351a914eb6078fc4ee7a3699c2cd2aee03157bc5c13763a64774504cdac4d3",
        2011,
    ),
    (
        "cme-hol-2012-new-year",
        "New Year's 2012 Holiday Schedule",
        "2012-new-years.pdf",
        "836775c7a3fc298e16037a5b6b462817068e913695cb9e0a729cb7c7f665838d",
        2011,
    ),
)

# 2012-2022: the annual holiday-calendar zips and the individual 2012/2022 files (PDF where
# published, XLS otherwise), transcribed per document.
_HOLIDAY_FILES = (
    *_HOLIDAY_FILES,
    (
        "cme-hol-2012-mlk",
        "2012 MLK holiday schedule",
        "2012-martin-luther-king.pdf",
        "458c94af0fd7b7d8445c229de6bbe05648ea588c2fea88180eefe46486e4d265",
        None,
    ),
    (
        "cme-hol-2012-presidents",
        "2012 Presidents holiday schedule",
        "2012-presidents-day.pdf",
        "4b5daad7813d41cdd9a104cca3a656bf303672f03c6c51ff5a13771d840ef131",
        None,
    ),
    (
        "cme-hol-2012-good-friday",
        "2012 Good Friday holiday schedule",
        "2012-good-friday.pdf",
        "81440c44afb97ea4b3a44b86aa4cf21e2e4cb7ba5839fabd95b29d0c928b2ea8",
        None,
    ),
    (
        "cme-hol-2012-memorial",
        "2012 Memorial holiday schedule",
        "2012-memorial-day.pdf",
        "5dc5cf9883232978ec1e80bd5bd50a2043535e93d7e52acddf4fd7e68938e848",
        None,
    ),
    (
        "cme-hol-2012-independence-day",
        "2012 Independence Day holiday schedule",
        "2012-4th-of-july.pdf",
        "9b35b802ff0e399226ac0811761fc7e03487d8dec401c19a7e383750cbca5faf",
        None,
    ),
    (
        "cme-hol-2012-labor",
        "2012 Labor holiday schedule",
        "2012-labor-day.pdf",
        "2f951bede1d6084977c8bed2f1cc4c993ebedd904aa0d56027668d2cb808ee39",
        None,
    ),
    (
        "cme-hol-2012-thanksgiving",
        "2012 Thanksgiving holiday schedule",
        "2012-thanksgiving.pdf",
        "052e381bbd4eb0790c6d38e3866874738d6da081da62643e525c25674b2608e1",
        None,
    ),
    (
        "cme-hol-2012-christmas",
        "2012 Christmas holiday schedule",
        "2012-christmas.pdf",
        "de3b16aaae2ef887e46c965f902d8d0e43afa6e18dc1f721baaa40ea6b18b5e9",
        None,
    ),
    (
        "cme-hol-2013-new-year",
        "2013 New Year holiday schedule",
        "2013-new-years.doc",
        "cfac9962b5b77c0284809bc8151cdf59ea933d05f35aab2e7977c4f3391ec26c",
        2012,
    ),
    (
        "cme-hol-2013-mlk",
        "2013 MLK holiday schedule",
        "2013-martin-luther-king.pdf",
        "f688165d1b4253288a2473eaffa5ed1793f619ff94ca7dd4a839028c66ebad55",
        2013,
    ),
    (
        "cme-hol-2013-presidents",
        "2013 Presidents holiday schedule",
        "2013-presidents-day.pdf",
        "e1242116eec5b7f3c5748e61adbf5bf7a809f48739ad456391f1d8b4bafceff6",
        2013,
    ),
    (
        "cme-hol-2013-good-friday",
        "2013 Good Friday holiday schedule",
        "2013-good-friday.pdf",
        "c05e590c950581e19ac2e8ee5327ebcfb4fc111b231b506abefae44534ee9b68",
        2013,
    ),
    (
        "cme-hol-2013-memorial",
        "2013 Memorial holiday schedule",
        "2013-memorial-day.pdf",
        "7cc47e352ff4874614fdb583cecd41b3ac3fcf95be6199ea5d489b8b34d2afe7",
        2013,
    ),
    (
        "cme-hol-2013-independence-day",
        "2013 Independence Day holiday schedule",
        "2013-4th-of-july-done.pdf",
        "768c7813542459dbc5443e79e514bb12fd511d93284beeb880af167f6049e0f0",
        2013,
    ),
    (
        "cme-hol-2013-labor",
        "2013 Labor holiday schedule",
        "2013-labor-day.pdf",
        "8f22671fa723d33fe36d58bb29e80ebd15370d3bf9000a9b45d56a0cab0608ef",
        2013,
    ),
    (
        "cme-hol-2013-thanksgiving",
        "2013 Thanksgiving holiday schedule",
        "2013-thanksgiving.pdf",
        "1f7f6428990a5bd01065f31c4388bf5aeeb12d9219e5af6d16b1cec86bbc158b",
        2013,
    ),
    (
        "cme-hol-2013-christmas",
        "2013 Christmas holiday schedule",
        "2013-christmas.pdf",
        "1389ade6b120383d05e8d6e8ed9c38f1e2394dd250c86b19606548618285e848",
        2013,
    ),
    (
        "cme-hol-2014-new-year",
        "2014 New Year holiday schedule",
        "2014-new-years.pdf",
        "907a0485a4aa2e391b25f5ea7322fa11e59d77bc43f097dbbc94b345cb1defbf",
        2013,
    ),
    (
        "cme-hol-2014-mlk",
        "2014 MLK holiday schedule",
        "2014-martin-luther-king-holiday-schedule.xls",
        "41649bcb888601efda5889878e5420cc4d844716a5897568228c267f02f06417",
        2014,
    ),
    (
        "cme-hol-2014-presidents",
        "2014 Presidents holiday schedule",
        "2014-presidents-day-holiday-schedule.xls",
        "ef76bc22b61f969710a1379538d3e7713bc43f3f4e3f7d3ad81b7ccbe5b7ebe9",
        2014,
    ),
    (
        "cme-hol-2014-good-friday",
        "2014 Good Friday holiday schedule",
        "2014-good-friday-holiday-schedule.xls",
        "f8c32e4cf7f261224d2b7edb950dcd172439c7e91659105e1c9a8ad8916c3d88",
        2014,
    ),
    (
        "cme-hol-2014-memorial",
        "2014 Memorial holiday schedule",
        "2014-memorial-day-holiday-schedule.pdf",
        "a8e020149657b4e4730c2a357015d096a9fd47e2054ca59a85d6e6548ccb6023",
        2014,
    ),
    (
        "cme-hol-2014-independence-day",
        "2014 Independence Day holiday schedule",
        "2014-4th-of-july-holiday-schedule.pdf",
        "34faa82435c6d8bb1088593c8945b6a5faaaa67b36c6a6422a24e4a25572ba77",
        2014,
    ),
    (
        "cme-hol-2014-labor",
        "2014 Labor holiday schedule",
        "2014-labor-day-holiday-schedule.pdf",
        "dfd92a530d114a1f1c68dd52be4315fd307d8f8cfb344d71de78334b9c73e4d6",
        2014,
    ),
    (
        "cme-hol-2014-thanksgiving",
        "2014 Thanksgiving holiday schedule",
        "2014-thanksgiving-holiday-schedule.pdf",
        "a90ae1f39414337f1a8600f55bf3a0a587214d987074885a47cfea307bc8054a",
        2014,
    ),
    (
        "cme-hol-2014-christmas",
        "2014 Christmas holiday schedule",
        "2014-christmas-holiday-schedule.pdf",
        "8125a18c9cad9b770be39b89c3193ee419240d409e39aa510d6eb3e8eba94e25",
        2014,
    ),
    (
        "cme-hol-2015-new-year",
        "2015 New Year holiday schedule",
        "2015-new-years-holiday-schedule.pdf",
        "196b4ec04bcfce2cfd9783262023afe9da73bcdef1b983c8c4b464b2e115bb8a",
        2014,
    ),
    (
        "cme-hol-2015-mlk",
        "2015 MLK holiday schedule",
        "2015-martin-luther-king-holiday-schedule.pdf",
        "67395dcb63d86b6e1f573a5aa37269a685dfe1b17d23edd7d95449899bce090a",
        2015,
    ),
    (
        "cme-hol-2015-presidents",
        "2015 Presidents holiday schedule",
        "2015-presidents-day-holiday-schedule.pdf",
        "c81b04bcf43dbfd2b7c2f7aba559992cde8bb8eee59e7b310b643b636d290b94",
        2015,
    ),
    (
        "cme-hol-2015-good-friday",
        "2015 Good Friday holiday schedule",
        "2015-good-friday-holiday-schedule.pdf",
        "67873caa987c9eee8de38d02a5c18d8f7d46fd82a486bab34821f6e6f6363e0b",
        2015,
    ),
    (
        "cme-hol-2015-memorial",
        "2015 Memorial holiday schedule",
        "2015-memorial-day-holiday-schedule.pdf",
        "4ad4398fa092393fa77cd8ed9c58ecc0f1669a41fd38a9b4cab5b05790d2dfec",
        2015,
    ),
    (
        "cme-hol-2015-independence-day",
        "2015 Independence Day holiday schedule",
        "2015-4th-of-july-holiday-schedule.pdf",
        "1013e6ebea1829591946c9aa513ec6e3f99c64d99be14814610e601bb5dcc0fb",
        2015,
    ),
    (
        "cme-hol-2015-labor",
        "2015 Labor holiday schedule",
        "2015-labor-day-holiday-schedule.pdf",
        "4aab7fdb5e57420a243bbc26be6ecfa00a6317937afe3b772dfcdd8db1dd50fd",
        2015,
    ),
    (
        "cme-hol-2015-thanksgiving",
        "2015 Thanksgiving holiday schedule",
        "2015-thanksgiving-holiday-schedule.pdf",
        "ef96d05289667c635f435884a0a2407bcbec63149ff96e802b719100c85c887f",
        2015,
    ),
    (
        "cme-hol-2015-christmas",
        "2015 Christmas holiday schedule",
        "2015-christmas-holiday-schedule.pdf",
        "7fde46210798f2cb4299903400b41ef6e2cb9aa287f8d3d360ba59d835b482ec",
        2015,
    ),
    (
        "cme-hol-2016-new-year",
        "2016 New Year holiday schedule",
        "2016-new-years-holiday-schedule.pdf",
        "118196a469dd40ad6a40594da273f726f6cb3e503f9cc1b8fd2057cf2fa32c61",
        2015,
    ),
    (
        "cme-hol-2016-mlk",
        "2016 MLK holiday schedule",
        "2016-martin-luther-king-holiday-schedule.pdf",
        "0fac2d08a84f8e9a637573438adfab33ba91c69e76b6dce01f0ca4cbcde8aff1",
        2016,
    ),
    (
        "cme-hol-2016-presidents",
        "2016 Presidents holiday schedule",
        "2016-presidents-day-holiday-schedule.pdf",
        "b5264dd479efd69df495de170cdd58326f64e9e31a2ed7cca6d7d96cc424c9c2",
        2016,
    ),
    (
        "cme-hol-2016-good-friday",
        "2016 Good Friday holiday schedule",
        "2016-good-friday-holiday-schedule.pdf",
        "632c4e3e451fd972e4cccb743f7dfa7a41896044cafc0e82953e0c6fb6d0bc42",
        2016,
    ),
    (
        "cme-hol-2016-memorial",
        "2016 Memorial holiday schedule",
        "2016-memorial-day-holiday-schedule.pdf",
        "03fa4af1988ae7a54c6e5426b83a76e54825ac4398f7a2be6e77be82fe8ab9f9",
        2016,
    ),
    (
        "cme-hol-2016-independence-day",
        "2016 Independence Day holiday schedule",
        "2016-4th-of-july-holiday-schedule.pdf",
        "533a49be68619dbd003b3e749485be46051018d3613d44a3043bf8a087fec9ad",
        2016,
    ),
    (
        "cme-hol-2016-labor",
        "2016 Labor holiday schedule",
        "2016-labor-day-holiday-schedule.pdf",
        "a4c0676ad117a63894b84637e8e5a7734ed17d7e2d1ee09d5a96370c7fd53b4a",
        2016,
    ),
    (
        "cme-hol-2016-thanksgiving",
        "2016 Thanksgiving holiday schedule",
        "2016-thanksgiving-holiday-schedule.pdf",
        "b3c4dbe2d60bf5530316653d381ba28f1eb4ed6ec55844dca976b1852941c2b1",
        2016,
    ),
    (
        "cme-hol-2016-christmas",
        "2016 Christmas holiday schedule",
        "2016-christmas-holiday-schedule.pdf",
        "42efeb845763d3d8a288dd9f9349bfcaf88badebf49ee1c6bc645a72ec01d252",
        2016,
    ),
    (
        "cme-hol-2017-new-year",
        "2017 New Year holiday schedule",
        "2017-new-years-holiday-schedule.pdf",
        "493e9cd3fb8ae7ce8b059f30516dedd83631a101e63ecd4c9201fa24c8a2aae8",
        2016,
    ),
    (
        "cme-hol-2017-mlk",
        "2017 MLK holiday schedule",
        "2017-martin-luther-king-holiday-schedule.xls",
        "c11937ee9995dd712f23631dd235571d87d2c387bc21e074cc87905b68980d58",
        2017,
    ),
    (
        "cme-hol-2017-presidents",
        "2017 Presidents holiday schedule",
        "2017-presidents-day-holiday-schedule.xls",
        "2ec7b623faa8f17ab5946091492be0dacbd29e6446ab3789e0ba4fa5ccd58b54",
        2017,
    ),
    (
        "cme-hol-2017-good-friday",
        "2017 Good Friday holiday schedule",
        "2017-good-friday-holiday-schedule.xls",
        "bdc8775f7061ae1e377421fe7a951446c0066ba11d1dbfc7bebba9e7c9415ccb",
        2017,
    ),
    (
        "cme-hol-2017-memorial",
        "2017 Memorial holiday schedule",
        "2017-memorial-day-holiday-schedule.xls",
        "883c04ff26743aee4a6b2a984a17111bb1fad21458c21fbee4b33bd75e7b7956",
        2017,
    ),
    (
        "cme-hol-2017-independence-day",
        "2017 Independence Day holiday schedule",
        "2017-4th-of-july-holiday-schedule.xls",
        "3e87d972cc318bdbece668b0d213708d515d80519369afe56a021de43c29b1ce",
        2017,
    ),
    (
        "cme-hol-2017-labor",
        "2017 Labor holiday schedule",
        "2017-labor-day-holiday-schedule.xls",
        "1f14dd5fb7e4dcb083b28f45443c45f974abcfb028b427a78e67f0a19009d42d",
        2017,
    ),
    (
        "cme-hol-2017-thanksgiving",
        "2017 Thanksgiving holiday schedule",
        "2017-thanksgiving-holiday-schedule.xls",
        "b6bc3dba9f1e0c5a86d543e389d15cea6006f456e6dc2cfd7813eae31db2f869",
        2017,
    ),
    (
        "cme-hol-2017-christmas",
        "2017 Christmas holiday schedule",
        "2017-christmas-holiday-schedule.xls",
        "bfb291c9c08764ee2bcf0327690b98c58cbb4cf493723c7b1464eccb0d062d30",
        2017,
    ),
    (
        "cme-hol-2018-new-year",
        "2018 New Year holiday schedule",
        "2018-new-years-holiday-schedule.xls",
        "fd59f0a57cb3c7d6964b22031a07666f2ba8ec1dc0a299a50759ddb8dd8ac235",
        2017,
    ),
    (
        "cme-hol-2018-mlk",
        "2018 MLK holiday schedule",
        "2018-martin-luther-king-holiday-schedule.xls",
        "703fdccaaee78bebfdc5bfb7586c0699bfde576cc2c36d113a37549dfafa3a2d",
        2018,
    ),
    (
        "cme-hol-2018-presidents",
        "2018 Presidents holiday schedule",
        "2018-presidents-day-holiday-schedule.xls",
        "2b3368ef69a3f850ff27a1e3773cfb327e187c31759b96c3f948c6ad91690f8b",
        2018,
    ),
    (
        "cme-hol-2018-good-friday",
        "2018 Good Friday holiday schedule",
        "2018-good-friday-holiday-schedule.xls",
        "ec3ffb0a85d061adbb53678353428eaeade9817963d6b5069db228844d9fbedf",
        2018,
    ),
    (
        "cme-hol-2018-memorial",
        "2018 Memorial holiday schedule",
        "2018-memorial-day-holiday-schedule.xls",
        "b3524e36abf39b038137145620cfe1a0d46022ce732ae623d6b71af8a4b8750b",
        2018,
    ),
    (
        "cme-hol-2018-independence-day",
        "2018 Independence Day holiday schedule",
        "2018-4th-of-july-holiday-schedule.xls",
        "8ed9e0f74c2bcdfdda8fa80c915e6bba5ed3c5ca7ec89476f11db03b256784ae",
        2018,
    ),
    (
        "cme-hol-2018-labor",
        "2018 Labor holiday schedule",
        "2018-labor-day-holiday-schedule.xls",
        "9b8c892dd3faba6900aae949f7f0c63b525191a76dccc938aa9859920b71b40d",
        2018,
    ),
    (
        "cme-hol-2018-thanksgiving",
        "2018 Thanksgiving holiday schedule",
        "2018-thanksgiving-holiday-schedule.xls",
        "31fc95f5b27f8689477b4abb557f14b2cf9ac481262926e30b78adf1455adff1",
        2018,
    ),
    (
        "cme-hol-2018-christmas",
        "2018 Christmas holiday schedule",
        "2018-christmas-holiday-schedule.xls",
        "b97ee5f47d55c4383c7f1fa7d554eba3c7f0e8ded18343aadd06d7908d9e7a91",
        2018,
    ),
    (
        "cme-hol-2019-new-year",
        "2019 New Year holiday schedule",
        "2019-new-years-holiday-schedule.xls",
        "aef68d200c7650ed0e48e4324d0f2a25eda81ecf010e808b7e8cc57c6e962cab",
        2018,
    ),
    (
        "cme-hol-2019-mlk",
        "2019 MLK holiday schedule",
        "2019-mlk-day-schedule.xls",
        "2a92dd707cab5728574868f16637711cb5ac16f2fa2e9213b54a21c51431df7c",
        2019,
    ),
    (
        "cme-hol-2019-presidents",
        "2019 Presidents holiday schedule",
        "2019-presidents-day-schedule.xls",
        "fbeade59f22839bc70705c4e8b04cadf1078488d2b85f7560107f4be06c70c9f",
        2019,
    ),
    (
        "cme-hol-2019-good-friday",
        "2019 Good Friday holiday schedule",
        "2019-good-friday-schedule.xls",
        "ee0141e0aceb9414f755ecf6221368196278a62cc0a2e91f4720277fae3b1a2e",
        2019,
    ),
    (
        "cme-hol-2019-memorial",
        "2019 Memorial holiday schedule",
        "2019-memorial-day-schedule.xls",
        "4a30a74de7a2285af289574f9820f495ffdf149dbac44ab949be5dfff10a9f00",
        2019,
    ),
    (
        "cme-hol-2019-independence-day",
        "2019 Independence Day holiday schedule",
        "2019-independence-day-schedule.xls",
        "6d8534e146a744f21f2970172ebd00ff9977ab905c6292cf1b206a4ca0a5a0fc",
        2019,
    ),
    (
        "cme-hol-2019-labor",
        "2019 Labor holiday schedule",
        "2019-labor-day-schedule.xls",
        "37f506f22c7ec2a3c4c6e8386c7caff546ae5915097e11f8e1ed62a1cbe9e7b7",
        2019,
    ),
    (
        "cme-hol-2019-thanksgiving",
        "2019 Thanksgiving holiday schedule",
        "2019-thanksgiving-schedule.xls",
        "b125e5c52f76df0cf418a2329710099a1a48ac197770e0d2ccb082c7c5b3c3c5",
        2019,
    ),
    (
        "cme-hol-2019-christmas",
        "2019 Christmas holiday schedule",
        "2019-christmas-holiday-schedule.xls",
        "49b64d21d3c718b76cf07699d57189483a15e48beb367b2101e4b0a5efc87e97",
        2019,
    ),
    (
        "cme-hol-2020-new-year",
        "2020 New Year holiday schedule",
        "2019-2020-new-years-holiday-schedule.xls",
        "d1b38e2477b0389ef05c07606f81bf77fedbc141397bc2606ca5afe58fbc6cf5",
        2019,
    ),
    (
        "cme-hol-2020-mlk",
        "2020 MLK holiday schedule",
        "2020-mlk-day-schedule.xls",
        "51ab36645ea68133de299f9c849f1361521399eb1334d55cc1a6d28de0faeb5b",
        2020,
    ),
    (
        "cme-hol-2020-presidents",
        "2020 Presidents holiday schedule",
        "2020-presidents-day-schedule.xls",
        "c2cca1682edf5ad23bd27557826d67cbfbaf9580ded525e45d53936618532683",
        2020,
    ),
    (
        "cme-hol-2020-good-friday",
        "2020 Good Friday holiday schedule",
        "2020-good-friday-schedule.xls",
        "4b5f23b22f4dcfc3f933d6a3b3c1e3193172045165ebf24618e78a25dd334aed",
        2020,
    ),
    (
        "cme-hol-2020-memorial",
        "2020 Memorial holiday schedule",
        "2020-memorial-day-schedule.xls",
        "70f0c3601c1f8405624f6eafdc389753e70c3139dbd455160648a3e0d8598cdb",
        2020,
    ),
    (
        "cme-hol-2020-independence-day",
        "2020 Independence Day holiday schedule",
        "2020-independence-day-schedule.xls",
        "4c107d4efaa2a97552b2f5b61bc22cf77b961a779ed92e4ad86c22238f5fdef4",
        2020,
    ),
    (
        "cme-hol-2020-labor",
        "2020 Labor holiday schedule",
        "2020-labor-day-schedule.xls",
        "2bc2473956f5243fca2af55b41af13a5b1d79c625526daa644a006d0a44a91db",
        2020,
    ),
    (
        "cme-hol-2020-thanksgiving",
        "2020 Thanksgiving holiday schedule",
        "2020-thanksgiving-schedule.xls",
        "161bf66991c2add69a6a3a8a8b084974dae7f01e757b47b50f7cf5d27405f0cc",
        2020,
    ),
    (
        "cme-hol-2020-christmas",
        "2020 Christmas holiday schedule",
        "2020-christmas-holiday-schedule.xls",
        "48eea6b5ace1de6d62bdb7ba09c6902101cc1e2ec13ee9fb60e5271eda5e9775",
        2020,
    ),
    (
        "cme-hol-2021-new-year",
        "2021 New Year holiday schedule",
        "2021-new-years-holiday-schedule.xls",
        "46ff5f0b845c999c644039d40e2c8f8fab1abf617968f9745aec3f6bce27ab8c",
        2020,
    ),
    (
        "cme-hol-2021-mlk",
        "2021 MLK holiday schedule",
        "2021-mlk-day-holiday-schedule.xls",
        "6d14fc3bea5f325bbc53ba2de77061561085c2530e23b740e1c7b2f8c2b370ab",
        2021,
    ),
    (
        "cme-hol-2021-presidents",
        "2021 Presidents holiday schedule",
        "2021-presidents-day-holiday-schedule.xls",
        "f2000b0f94d11de0882f86ad8c5bd1d4703eb198a728b1cf616d09ac3a3fb890",
        2021,
    ),
    (
        "cme-hol-2021-good-friday",
        "2021 Good Friday holiday schedule",
        "2021-good-friday-holiday-schedule.xls",
        "0bb04c395a8b5facff8c285405df3b65cc269d0ccc48f26a62b0f9c5886124f6",
        2021,
    ),
    (
        "cme-hol-2021-memorial",
        "2021 Memorial holiday schedule",
        "2021-memorial-day-holiday-schedule.xls",
        "108f7e9caec304b6e5d97b288e064e758190c545a397efc857dddc844b5a156e",
        2021,
    ),
    (
        "cme-hol-2021-independence-day",
        "2021 Independence Day holiday schedule",
        "2021-independence-day-holiday-schedule.xls",
        "4f550bbe6e9de1c589da9c131ce1a042123fc60da2a15f94313dc7d3689e1a7d",
        2021,
    ),
    (
        "cme-hol-2021-labor",
        "2021 Labor holiday schedule",
        "2021-labor-day-holiday-schedule.xls",
        "a8b747bd5709864ae87e5c034c29e35fe134fe30c10f22f45aa2ce9c8da6811d",
        2021,
    ),
    (
        "cme-hol-2021-thanksgiving",
        "2021 Thanksgiving holiday schedule",
        "2021-thanksgiving-holiday-schedule.xls",
        "127744cc8570a05f21e54f112cbe24bfe05e233ffc0ceb2ec4c6884b4fa0dad3",
        2021,
    ),
    (
        "cme-hol-2021-christmas",
        "2021 Christmas holiday schedule",
        "2021-christmas-holiday-schedule.xls",
        "c9d4f032b3371e6d05d805fcf2420215b136670d26eedc4e3f5aee1bd63e35af",
        2021,
    ),
    (
        "cme-hol-2022-mlk",
        "2022 MLK holiday schedule",
        "2022-mlk-day-holiday-schedule.xls",
        "896944fa701062e2e1ee305f8adb696ba8ab03655a96874c7885f2328177626e",
        None,
    ),
    (
        "cme-hol-2022-presidents",
        "2022 Presidents holiday schedule",
        "2022-presidents-day-holiday-schedule.xls",
        "07932975d04ccabad0fb53f33f946f1a6fd8a696bafdb21f95f030ede9a84516",
        None,
    ),
    (
        "cme-hol-2022-good-friday",
        "2022 Good Friday holiday schedule",
        "2022-good-friday-holiday-schedule.xls",
        "a82936ab14d1b1f7041583123289c4de401c66ace4eea7e90fa9f60c1a3f3b7e",
        None,
    ),
    (
        "cme-hol-2022-memorial",
        "2022 Memorial holiday schedule",
        "2022-memorial-day-holiday-schedule.xls",
        "0d1b1f89a315cae22a5857a7027a514e3086c1cccfee42fddddff3caba0c2230",
        None,
    ),
    (
        "cme-hol-2022-juneteenth",
        "2022 Juneteenth holiday schedule",
        "2022-juneteenth-holiday-schedule.xls",
        "bc9f2caf26a73a13029f177fcc6468bdc8662899ff935f44329ee1a95c8b667b",
        None,
    ),
    (
        "cme-hol-2022-independence-day",
        "2022 Independence Day holiday schedule",
        "2022-independence-day-holiday-schedule.xls",
        "1ea0459d8aa0fd7ec5147614855f6d0d43607efefdc3aa9c6b1e18ddbfd54fde",
        None,
    ),
    (
        "cme-hol-2022-labor",
        "2022 Labor holiday schedule",
        "2022-labor-day-holiday-schedule.xls",
        "28d533f25d1af74af043e411635f1933fd4ff6359c80c049f87f019d2f1d57d0",
        None,
    ),
    (
        "cme-hol-2022-thanksgiving",
        "2022 Thanksgiving holiday schedule",
        "2022-thanksgiving-holiday-schedule.xls",
        "64341a65350de982a6a05760504132e173611151ae3164c6f9437509a406edcb",
        None,
    ),
    (
        "cme-hol-2022-christmas",
        "2022 Christmas holiday schedule",
        "2022-christmas-holiday-schedule.xls",
        "2dd1d531514989845dcb6ce6d767db5dd3f956ac6777ab1cfe36d6843f3762e7",
        None,
    ),
    (
        "cme-hol-2023-new-year",
        "2023 New Year holiday schedule (updated 2022-06-29)",
        "2023-new-years-holiday-schedule.xls",
        "eefafd1066f406edbe6167ddf8ad13c0697b124a337c0893ce5a5da200c783d3",
        None,
    ),
)

B.add(
    "cme-hol-2012-mlk",
    "2012 MLK",
    closed=("2012-01-16",),
    sessions={
        "2012-01-17": ("2012-01-15 17:00", None, (("2012-01-16 10:30", "2012-01-16 17:00"),))
    },
)
B.add(
    "cme-hol-2012-presidents",
    "2012 Presidents",
    closed=("2012-02-20",),
    sessions={
        "2012-02-21": ("2012-02-19 17:00", None, (("2012-02-20 10:30", "2012-02-20 17:00"),))
    },
)
B.add(
    "cme-hol-2012-good-friday",
    "2012 Good Friday",
    sessions={"2012-04-06": (None, "2012-04-06 08:15", ())},
)
B.add(
    "cme-hol-2012-memorial",
    "2012 Memorial",
    closed=("2012-05-28",),
    sessions={
        "2012-05-29": ("2012-05-27 17:00", None, (("2012-05-28 10:30", "2012-05-28 17:00"),))
    },
)
B.add(
    "cme-hol-2012-independence-day",
    "2012 Independence Day",
    closed=("2012-07-04",),
    sessions={
        "2012-07-03": (None, "2012-07-03 12:15", ()),
        "2012-07-05": ("2012-07-03 15:30", None, (("2012-07-04 10:30", "2012-07-04 17:00"),)),
    },
)
B.add(
    "cme-hol-2012-labor",
    "2012 Labor",
    closed=("2012-09-03",),
    sessions={
        "2012-09-04": ("2012-09-02 17:00", None, (("2012-09-03 10:30", "2012-09-03 17:00"),))
    },
)
B.add(
    "cme-hol-2012-thanksgiving",
    "2012 Thanksgiving",
    closed=("2012-11-22",),
    sessions={
        "2012-11-23": (
            "2012-11-21 17:00",
            "2012-11-23 12:15",
            (("2012-11-22 10:30", "2012-11-22 17:00"),),
        )
    },
)
B.add(
    "cme-hol-2012-christmas",
    "2012 Christmas",
    closed=("2012-12-25",),
    sessions={
        "2012-12-24": (None, "2012-12-24 12:15", ()),
        "2012-12-26": ("2012-12-26 05:00", None, ()),
    },
)
B.add(
    "cme-hol-2013-new-year",
    "2013 New Year",
    closed=("2013-01-01",),
    sessions={"2013-01-02": ("2013-01-02 05:00", None, ())},
)
B.add(
    "cme-hol-2013-mlk",
    "2013 MLK",
    closed=("2013-01-21",),
    sessions={
        "2013-01-22": ("2013-01-20 17:00", None, (("2013-01-21 10:30", "2013-01-21 17:00"),))
    },
)
B.add(
    "cme-hol-2013-presidents",
    "2013 Presidents",
    closed=("2013-02-18",),
    sessions={
        "2013-02-19": ("2013-02-17 17:00", None, (("2013-02-18 10:30", "2013-02-18 17:00"),))
    },
)
B.add(
    "cme-hol-2013-good-friday",
    "2013 Good Friday",
    closed=("2013-03-29",),
    sessions={"2013-04-01": ("2013-03-31 17:00", None, ())},
)
B.add(
    "cme-hol-2013-memorial",
    "2013 Memorial",
    closed=("2013-05-27",),
    sessions={
        "2013-05-28": ("2013-05-26 17:00", None, (("2013-05-27 10:30", "2013-05-27 17:00"),))
    },
)
B.add(
    "cme-hol-2013-independence-day",
    "2013 Independence Day",
    closed=("2013-07-04",),
    sessions={
        "2013-07-03": (None, "2013-07-03 12:15", ()),
        "2013-07-05": ("2013-07-03 17:00", None, (("2013-07-04 10:30", "2013-07-04 17:00"),)),
    },
)
B.add(
    "cme-hol-2013-labor",
    "2013 Labor",
    closed=("2013-09-02",),
    sessions={
        "2013-09-03": ("2013-09-01 17:00", None, (("2013-09-02 10:30", "2013-09-02 17:00"),))
    },
)
B.add(
    "cme-hol-2013-thanksgiving",
    "2013 Thanksgiving",
    closed=("2013-11-28",),
    sessions={
        "2013-11-29": (
            "2013-11-27 17:00",
            "2013-11-29 12:15",
            (("2013-11-28 10:30", "2013-11-28 17:00"),),
        )
    },
)
B.add(
    "cme-hol-2013-christmas",
    "2013 Christmas",
    closed=("2013-12-25",),
    sessions={
        "2013-12-24": (None, "2013-12-24 12:15", ()),
        "2013-12-26": ("2013-12-26 05:00", None, ()),
    },
)
B.add(
    "cme-hol-2014-new-year",
    "2014 New Year",
    closed=("2014-01-01",),
    sessions={"2014-01-02": ("2014-01-02 05:00", None, ())},
)
B.add(
    "cme-hol-2014-mlk",
    "2014 MLK",
    closed=("2014-01-20",),
    sessions={
        "2014-01-21": ("2014-01-19 17:00", None, (("2014-01-20 10:30", "2014-01-20 17:00"),))
    },
)
B.add(
    "cme-hol-2014-presidents",
    "2014 Presidents",
    closed=("2014-02-17",),
    sessions={
        "2014-02-18": ("2014-02-16 17:00", None, (("2014-02-17 10:30", "2014-02-17 17:00"),))
    },
)
B.add(
    "cme-hol-2014-good-friday",
    "2014 Good Friday",
    closed=("2014-04-18",),
    sessions={"2014-04-21": ("2014-04-20 17:00", None, ())},
)
B.add(
    "cme-hol-2014-memorial",
    "2014 Memorial",
    closed=("2014-05-26",),
    sessions={
        "2014-05-27": ("2014-05-25 17:00", None, (("2014-05-26 12:00", "2014-05-26 17:00"),))
    },
)
B.add(
    "cme-hol-2014-independence-day",
    "2014 Independence Day",
    closed=("2014-07-04",),
    sessions={
        "2014-07-03": (None, "2014-07-03 12:15", ()),
        "2014-07-07": ("2014-07-03 17:00", None, (("2014-07-04 12:00", "2014-07-06 17:00"),)),
    },
)
B.add(
    "cme-hol-2014-labor",
    "2014 Labor",
    closed=("2014-09-01",),
    sessions={
        "2014-09-02": ("2014-08-31 17:00", None, (("2014-09-01 12:00", "2014-09-01 17:00"),))
    },
)
B.add(
    "cme-hol-2014-thanksgiving",
    "2014 Thanksgiving",
    closed=("2014-11-27",),
    sessions={
        "2014-11-28": (
            "2014-11-26 17:00",
            "2014-11-28 12:15",
            (("2014-11-27 12:00", "2014-11-27 17:00"),),
        )
    },
)
B.add(
    "cme-hol-2014-christmas",
    "2014 Christmas",
    closed=("2014-12-25",),
    sessions={
        "2014-12-24": (None, "2014-12-24 12:15", ()),
        "2014-12-26": ("2014-12-25 17:00", None, ()),
    },
)
B.add(
    "cme-hol-2015-new-year",
    "2015 New Year",
    closed=("2015-01-01",),
    sessions={"2015-01-02": ("2015-01-01 17:00", None, ())},
)
B.add(
    "cme-hol-2015-mlk",
    "2015 MLK",
    closed=("2015-01-19",),
    sessions={
        "2015-01-20": ("2015-01-18 17:00", None, (("2015-01-19 12:00", "2015-01-19 17:00"),))
    },
)
B.add(
    "cme-hol-2015-presidents",
    "2015 Presidents",
    closed=("2015-02-16",),
    sessions={
        "2015-02-17": ("2015-02-15 17:00", None, (("2015-02-16 12:00", "2015-02-16 17:00"),))
    },
)
B.add(
    "cme-hol-2015-good-friday",
    "2015 Good Friday",
    sessions={"2015-04-03": (None, "2015-04-03 08:15", ())},
)
B.add(
    "cme-hol-2015-memorial",
    "2015 Memorial",
    closed=("2015-05-25",),
    sessions={
        "2015-05-26": ("2015-05-24 17:00", None, (("2015-05-25 12:00", "2015-05-25 17:00"),))
    },
)
B.add(
    "cme-hol-2015-independence-day",
    "2015 Independence Day",
    closed=("2015-07-03",),
    sessions={
        "2015-07-06": ("2015-07-02 17:00", None, (("2015-07-03 12:00", "2015-07-05 17:00"),))
    },
)
B.add(
    "cme-hol-2015-labor",
    "2015 Labor",
    closed=("2015-09-07",),
    sessions={
        "2015-09-08": ("2015-09-06 17:00", None, (("2015-09-07 12:00", "2015-09-07 17:00"),))
    },
)
B.add(
    "cme-hol-2015-thanksgiving",
    "2015 Thanksgiving",
    closed=("2015-11-26",),
    sessions={
        "2015-11-27": (
            "2015-11-25 17:00",
            "2015-11-27 12:15",
            (("2015-11-26 12:00", "2015-11-26 17:00"),),
        )
    },
)
B.add(
    "cme-hol-2015-christmas",
    "2015 Christmas",
    closed=("2015-12-25",),
    sessions={
        "2015-12-24": (None, "2015-12-24 12:15", ()),
        "2015-12-28": ("2015-12-27 17:00", None, ()),
    },
)
B.add(
    "cme-hol-2016-new-year",
    "2016 New Year",
    closed=("2016-01-01",),
    sessions={"2016-01-04": ("2016-01-03 17:00", None, ())},
)
B.add(
    "cme-hol-2016-mlk",
    "2016 MLK",
    closed=("2016-01-18",),
    sessions={
        "2016-01-19": ("2016-01-17 17:00", None, (("2016-01-18 12:00", "2016-01-18 17:00"),))
    },
)
B.add(
    "cme-hol-2016-presidents",
    "2016 Presidents",
    closed=("2016-02-15",),
    sessions={
        "2016-02-16": ("2016-02-14 17:00", None, (("2016-02-15 12:00", "2016-02-15 17:00"),))
    },
)
B.add(
    "cme-hol-2016-good-friday",
    "2016 Good Friday",
    closed=("2016-03-25",),
    sessions={"2016-03-28": ("2016-03-27 17:00", None, ())},
)
B.add(
    "cme-hol-2016-memorial",
    "2016 Memorial",
    closed=("2016-05-30",),
    sessions={
        "2016-05-31": ("2016-05-29 17:00", None, (("2016-05-30 12:00", "2016-05-30 17:00"),))
    },
)
B.add(
    "cme-hol-2016-independence-day",
    "2016 Independence Day",
    closed=("2016-07-04",),
    sessions={
        "2016-07-05": ("2016-07-03 17:00", None, (("2016-07-04 12:00", "2016-07-04 17:00"),))
    },
)
B.add(
    "cme-hol-2016-labor",
    "2016 Labor",
    closed=("2016-09-05",),
    sessions={
        "2016-09-06": ("2016-09-04 17:00", None, (("2016-09-05 12:00", "2016-09-05 17:00"),))
    },
)
B.add(
    "cme-hol-2016-thanksgiving",
    "2016 Thanksgiving",
    closed=("2016-11-24",),
    sessions={
        "2016-11-25": (
            "2016-11-23 17:00",
            "2016-11-25 12:15",
            (("2016-11-24 12:00", "2016-11-24 17:00"),),
        )
    },
)
B.add(
    "cme-hol-2016-christmas",
    "2016 Christmas",
    closed=("2016-12-26",),
    sessions={"2016-12-27": ("2016-12-26 17:00", None, ())},
)
B.add(
    "cme-hol-2017-new-year",
    "2017 New Year",
    closed=("2017-01-02",),
    sessions={"2017-01-03": ("2017-01-02 17:00", None, ())},
)
B.add(
    "cme-hol-2017-mlk",
    "2017 MLK",
    closed=("2017-01-16",),
    sessions={
        "2017-01-17": ("2017-01-15 17:00", None, (("2017-01-16 12:00", "2017-01-16 17:00"),))
    },
)
B.add(
    "cme-hol-2017-presidents",
    "2017 Presidents",
    closed=("2017-02-20",),
    sessions={
        "2017-02-21": ("2017-02-19 17:00", None, (("2017-02-20 12:00", "2017-02-20 17:00"),))
    },
)
B.add(
    "cme-hol-2017-good-friday",
    "2017 Good Friday",
    closed=("2017-04-14",),
    sessions={"2017-04-17": ("2017-04-16 17:00", None, ())},
)
B.add(
    "cme-hol-2017-memorial",
    "2017 Memorial",
    closed=("2017-05-29",),
    sessions={
        "2017-05-30": ("2017-05-28 17:00", None, (("2017-05-29 12:00", "2017-05-29 17:00"),))
    },
)
B.add(
    "cme-hol-2017-independence-day",
    "2017 Independence Day",
    closed=("2017-07-04",),
    sessions={
        "2017-07-03": (None, "2017-07-03 12:15", ()),
        "2017-07-05": ("2017-07-03 17:00", None, (("2017-07-04 12:00", "2017-07-04 17:00"),)),
    },
)
B.add(
    "cme-hol-2017-labor",
    "2017 Labor",
    closed=("2017-09-04",),
    sessions={
        "2017-09-05": ("2017-09-03 17:00", None, (("2017-09-04 12:00", "2017-09-04 17:00"),))
    },
)
B.add(
    "cme-hol-2017-thanksgiving",
    "2017 Thanksgiving",
    closed=("2017-11-23",),
    sessions={
        "2017-11-24": (
            "2017-11-22 17:00",
            "2017-11-24 12:15",
            (("2017-11-23 12:00", "2017-11-23 17:00"),),
        )
    },
)
B.add(
    "cme-hol-2017-christmas",
    "2017 Christmas",
    closed=("2017-12-25",),
    sessions={"2017-12-26": ("2017-12-25 17:00", None, ())},
)
B.add(
    "cme-hol-2018-new-year",
    "2018 New Year",
    closed=("2018-01-01",),
    sessions={"2018-01-02": ("2018-01-01 17:00", None, ())},
)
B.add(
    "cme-hol-2018-mlk",
    "2018 MLK",
    closed=("2018-01-15",),
    sessions={
        "2018-01-16": ("2018-01-14 17:00", None, (("2018-01-15 12:00", "2018-01-15 17:00"),))
    },
)
B.add(
    "cme-hol-2018-presidents",
    "2018 Presidents",
    closed=("2018-02-19",),
    sessions={
        "2018-02-20": ("2018-02-18 17:00", None, (("2018-02-19 12:00", "2018-02-19 17:00"),))
    },
)
B.add(
    "cme-hol-2018-good-friday",
    "2018 Good Friday",
    closed=("2018-03-30",),
    sessions={"2018-04-02": ("2018-04-01 17:00", None, ())},
)
B.add(
    "cme-hol-2018-memorial",
    "2018 Memorial",
    closed=("2018-05-28",),
    sessions={
        "2018-05-29": ("2018-05-27 17:00", None, (("2018-05-28 12:00", "2018-05-28 17:00"),))
    },
)
B.add(
    "cme-hol-2018-independence-day",
    "2018 Independence Day",
    closed=("2018-07-04",),
    sessions={
        "2018-07-03": (None, "2018-07-03 12:15", ()),
        "2018-07-05": ("2018-07-03 17:00", None, (("2018-07-04 12:00", "2018-07-04 17:00"),)),
    },
)
B.add(
    "cme-hol-2018-labor",
    "2018 Labor",
    closed=("2018-09-03",),
    sessions={
        "2018-09-04": ("2018-09-02 17:00", None, (("2018-09-03 12:00", "2018-09-03 17:00"),))
    },
)
B.add(
    "cme-hol-2018-thanksgiving",
    "2018 Thanksgiving",
    closed=("2018-11-22",),
    sessions={
        "2018-11-23": (
            "2018-11-21 17:00",
            "2018-11-23 12:15",
            (("2018-11-22 12:00", "2018-11-22 17:00"),),
        )
    },
)
B.add(
    "cme-hol-2018-christmas",
    "2018 Christmas",
    closed=("2018-12-25",),
    sessions={
        "2018-12-24": (None, "2018-12-24 12:15", ()),
        "2018-12-26": ("2018-12-25 17:00", None, ()),
    },
)
B.add(
    "cme-hol-2019-new-year",
    "2019 New Year",
    closed=("2019-01-01",),
    sessions={"2019-01-02": ("2019-01-01 17:00", None, ())},
)
B.add(
    "cme-hol-2019-mlk",
    "2019 MLK",
    closed=("2019-01-21",),
    sessions={
        "2019-01-22": ("2019-01-20 17:00", None, (("2019-01-21 12:00", "2019-01-21 17:00"),))
    },
)
B.add(
    "cme-hol-2019-presidents",
    "2019 Presidents",
    closed=("2019-02-18",),
    sessions={
        "2019-02-19": ("2019-02-17 17:00", None, (("2019-02-18 12:00", "2019-02-18 17:00"),))
    },
)
B.add(
    "cme-hol-2019-good-friday",
    "2019 Good Friday",
    closed=("2019-04-19",),
    sessions={"2019-04-22": ("2019-04-21 17:00", None, ())},
)
B.add(
    "cme-hol-2019-memorial",
    "2019 Memorial",
    closed=("2019-05-27",),
    sessions={
        "2019-05-28": ("2019-05-26 17:00", None, (("2019-05-27 12:00", "2019-05-27 17:00"),))
    },
)
B.add(
    "cme-hol-2019-independence-day",
    "2019 Independence Day",
    closed=("2019-07-04",),
    sessions={
        "2019-07-03": (None, "2019-07-03 12:15", ()),
        "2019-07-05": ("2019-07-03 17:00", None, (("2019-07-04 12:00", "2019-07-04 17:00"),)),
    },
)
B.add(
    "cme-hol-2019-labor",
    "2019 Labor",
    closed=("2019-09-02",),
    sessions={
        "2019-09-03": ("2019-09-01 17:00", None, (("2019-09-02 12:00", "2019-09-02 17:00"),))
    },
)
B.add(
    "cme-hol-2019-thanksgiving",
    "2019 Thanksgiving",
    closed=("2019-11-28",),
    sessions={
        "2019-11-29": (
            "2019-11-27 17:00",
            "2019-11-29 12:15",
            (("2019-11-28 12:00", "2019-11-28 17:00"),),
        )
    },
)
B.add(
    "cme-hol-2019-christmas",
    "2019 Christmas",
    closed=("2019-12-25",),
    sessions={
        "2019-12-24": (None, "2019-12-24 12:15", ()),
        "2019-12-26": ("2019-12-25 17:00", None, ()),
    },
)
B.add(
    "cme-hol-2020-new-year",
    "2020 New Year",
    closed=("2020-01-01",),
    sessions={"2020-01-02": ("2020-01-01 17:00", None, ())},
)
B.add(
    "cme-hol-2020-mlk",
    "2020 MLK",
    closed=("2020-01-20",),
    sessions={
        "2020-01-21": ("2020-01-19 17:00", None, (("2020-01-20 12:00", "2020-01-20 17:00"),))
    },
)
B.add(
    "cme-hol-2020-presidents",
    "2020 Presidents",
    closed=("2020-02-17",),
    sessions={
        "2020-02-18": ("2020-02-16 17:00", None, (("2020-02-17 12:00", "2020-02-17 17:00"),))
    },
)
B.add(
    "cme-hol-2020-good-friday",
    "2020 Good Friday",
    closed=("2020-04-10",),
    sessions={"2020-04-13": ("2020-04-12 17:00", None, ())},
)
B.add(
    "cme-hol-2020-memorial",
    "2020 Memorial",
    closed=("2020-05-25",),
    sessions={
        "2020-05-26": ("2020-05-24 17:00", None, (("2020-05-25 12:00", "2020-05-25 17:00"),))
    },
)
B.add(
    "cme-hol-2020-independence-day",
    "2020 Independence Day",
    closed=("2020-07-03",),
    sessions={
        "2020-07-06": ("2020-07-02 17:00", None, (("2020-07-03 12:00", "2020-07-05 17:00"),))
    },
)
B.add(
    "cme-hol-2020-labor",
    "2020 Labor",
    closed=("2020-09-07",),
    sessions={
        "2020-09-08": ("2020-09-06 17:00", None, (("2020-09-07 12:00", "2020-09-07 17:00"),))
    },
)
B.add(
    "cme-hol-2020-thanksgiving",
    "2020 Thanksgiving",
    closed=("2020-11-26",),
    sessions={
        "2020-11-27": (
            "2020-11-25 17:00",
            "2020-11-27 12:15",
            (("2020-11-26 12:00", "2020-11-26 17:00"),),
        )
    },
)
B.add(
    "cme-hol-2020-christmas",
    "2020 Christmas",
    closed=("2020-12-25",),
    sessions={
        "2020-12-24": (None, "2020-12-24 12:15", ()),
        "2020-12-28": ("2020-12-27 17:00", None, ()),
    },
)
B.add(
    "cme-hol-2021-new-year",
    "2021 New Year",
    closed=("2021-01-01",),
    sessions={"2021-01-04": ("2021-01-03 17:00", None, ())},
)
B.add(
    "cme-hol-2021-mlk",
    "2021 MLK",
    closed=("2021-01-18",),
    sessions={
        "2021-01-19": ("2021-01-17 17:00", None, (("2021-01-18 12:00", "2021-01-18 17:00"),))
    },
)
B.add(
    "cme-hol-2021-presidents",
    "2021 Presidents",
    closed=("2021-02-15",),
    sessions={
        "2021-02-16": ("2021-02-14 17:00", None, (("2021-02-15 12:00", "2021-02-15 17:00"),))
    },
)
B.add(
    "cme-hol-2021-good-friday",
    "2021 Good Friday",
    sessions={"2021-04-02": (None, "2021-04-02 08:15", ())},
)
B.add(
    "cme-hol-2021-memorial",
    "2021 Memorial",
    closed=("2021-05-31",),
    sessions={
        "2021-06-01": ("2021-05-30 17:00", None, (("2021-05-31 12:00", "2021-05-31 17:00"),))
    },
)
B.add(
    "cme-hol-2021-independence-day",
    "2021 Independence Day",
    closed=("2021-07-05",),
    sessions={
        "2021-07-06": ("2021-07-04 17:00", None, (("2021-07-05 12:00", "2021-07-05 17:00"),))
    },
)
B.add(
    "cme-hol-2021-labor",
    "2021 Labor",
    closed=("2021-09-06",),
    sessions={
        "2021-09-07": ("2021-09-05 17:00", None, (("2021-09-06 12:00", "2021-09-06 17:00"),))
    },
)
B.add(
    "cme-hol-2021-thanksgiving",
    "2021 Thanksgiving",
    closed=("2021-11-25",),
    sessions={
        "2021-11-26": (
            "2021-11-24 17:00",
            "2021-11-26 12:15",
            (("2021-11-25 12:00", "2021-11-25 17:00"),),
        )
    },
)
B.add(
    "cme-hol-2021-christmas",
    "2021 Christmas",
    closed=("2021-12-24",),
    sessions={"2021-12-27": ("2021-12-26 17:00", None, ())},
)
B.add(
    "cme-hol-2022-mlk",
    "2022 MLK",
    closed=("2022-01-17",),
    sessions={
        "2022-01-18": ("2022-01-16 17:00", None, (("2022-01-17 12:00", "2022-01-17 17:00"),))
    },
)
B.add(
    "cme-hol-2022-presidents",
    "2022 Presidents",
    closed=("2022-02-21",),
    sessions={
        "2022-02-22": ("2022-02-20 17:00", None, (("2022-02-21 12:00", "2022-02-21 17:00"),))
    },
)
B.add(
    "cme-hol-2022-good-friday",
    "2022 Good Friday",
    closed=("2022-04-15",),
    sessions={"2022-04-18": ("2022-04-17 17:00", None, ())},
)
B.add(
    "cme-hol-2022-memorial",
    "2022 Memorial",
    closed=("2022-05-30",),
    sessions={
        "2022-05-31": ("2022-05-29 17:00", None, (("2022-05-30 12:00", "2022-05-30 17:00"),))
    },
)
B.add(
    "cme-hol-2022-juneteenth",
    "2022 Juneteenth",
    closed=("2022-06-20",),
    sessions={
        "2022-06-21": ("2022-06-19 17:00", None, (("2022-06-20 12:00", "2022-06-20 17:00"),))
    },
)
B.add(
    "cme-hol-2022-independence-day",
    "2022 Independence Day",
    closed=("2022-07-04",),
    sessions={
        "2022-07-05": ("2022-07-03 17:00", None, (("2022-07-04 12:00", "2022-07-04 17:00"),))
    },
)
B.add(
    "cme-hol-2022-labor",
    "2022 Labor",
    closed=("2022-09-05",),
    sessions={
        "2022-09-06": ("2022-09-04 17:00", None, (("2022-09-05 12:00", "2022-09-05 17:00"),))
    },
)
B.add(
    "cme-hol-2022-thanksgiving",
    "2022 Thanksgiving",
    closed=("2022-11-24",),
    sessions={
        "2022-11-25": (
            "2022-11-23 17:00",
            "2022-11-25 12:15",
            (("2022-11-24 12:00", "2022-11-24 17:00"),),
        )
    },
)
B.add(
    "cme-hol-2022-christmas",
    "2022 Christmas",
    closed=("2022-12-26",),
    sessions={"2022-12-27": ("2022-12-26 17:00", None, ())},
)
B.add(
    "cme-hol-2023-new-year",
    "2023 New Year (observed Mon 2023-01-02)",
    closed=("2023-01-02",),
    sessions={"2023-01-03": ("2023-01-02 17:00", None, ())},
)


def cme_session_table() -> SessionTable:
    """The table. Refuses an entry whose source key is not in ``SOURCES``."""
    sources = (
        *_REGIME_SOURCES,
        *_SPECIAL_SOURCES,
        *_API_SOURCES,
        *(_holiday_source(*row) for row in _HOLIDAY_FILES),
    )
    keys = {s.key for s in sources}
    if len(keys) != len(sources):
        msg = f"{TABLE_VERSION}: duplicate source keys"
        raise ValueError(msg)
    cited = (
        {s for r in REGIMES for s in r.sources}
        | {o.source for o in B.overrides}
        | {n.source for n in B.closed}
        | {u.source for u in UNSCHEDULED}
    )
    missing = sorted(cited - keys)
    if missing:
        msg = f"{TABLE_VERSION}: entries cite unknown sources {missing}"
        raise ValueError(msg)
    seen: set[tuple[dt.date, str]] = set()
    for o in B.overrides:
        for root in o.roots:
            if (o.trade_date, root) in seen:
                msg = f"{TABLE_VERSION}: two overrides for {root} trade date {o.trade_date}"
                raise ValueError(msg)
            seen.add((o.trade_date, root))
    return SessionTable(
        version=TABLE_VERSION,
        retrieved=RETRIEVED,
        coverage=dict(COVERAGE),
        regimes=REGIMES,
        overrides=tuple(sorted(B.overrides, key=lambda o: o.trade_date)),
        no_trade_dates=tuple(sorted(B.closed, key=lambda n: n.date)),
        unsourced=(*UNSOURCED, *B.unsourced),
        unscheduled=UNSCHEDULED,
        sources=sources,
        conflicts=CONFLICTS,
    )
