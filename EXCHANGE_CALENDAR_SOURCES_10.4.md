# Veltrix v10.4 — Exchange Calendar Sources and Coverage

Calendar data checked on **23 November 2026**. This file records the exchange source, scope and limits for the bundled cash-market exception dataset.

## Bundled venue coverage

| Veltrix clock | Venue represented | Published coverage | Source |
|---|---|---|---|
| Sydney | ASX cash market | 1 Jan 2026 – 31 Dec 2027 | [ASX Trade calendar](https://www.asx.com.au/markets/market-resources/trading-hours-calendar/cash-market-trading-hours/trading-calendar) |
| Tokyo | Tokyo Stock Exchange / JPX market holidays | 1 Jan 2026 – 31 Dec 2027 | [JPX Market Holidays](https://www.jpx.co.jp/english/corporate/about-jpx/calendar/index.html) |
| London | London Stock Exchange on-exchange trading services | 31 Aug 2026 – 31 Dec 2027 | [LSE Business Days](https://www.londonstockexchange.com/en/resources/markets-products/business-days) |
| New York | NYSE cash-market holiday schedule | 1 Jan 2026 – 31 Dec 2027 | [NYSE Holidays & Trading Hours](https://www.nyse.com/trade/hours-calendars) |

## How exceptions are represented

- **CLOSED**: the venue's cash-market schedule is suppressed for that local date. The next opening skips further published closure dates and the normal configured non-trading weekdays.
- **EARLY_CLOSE**: a published normal-trading cessation / early-market-close time shortens that venue's session state and timeline.
- **CLOSE_PROCESS**: the exchange publishes the start of its closing process, but not a definitive end of continuous trading at that timestamp. Veltrix displays and alerts on the process-start time without forcing the market to CLOSED.

The LSE's Christmas Eve and New Year's Eve entries say its markets closing process commences from **12:30 London time**. Veltrix therefore uses a CLOSING PROCESS marker, not a claim that continuous trading ends exactly at 12:30.

ASX early-close times are 14:10 Sydney time, which ASX identifies as the time normal trading ceases. NYSE early closes in the bundled dataset are 13:00 Eastern time.

## Venue and product scope

The four clock labels map to ASX cash equities, Tokyo Stock Exchange / JPX market holidays, London Stock Exchange on-exchange trading services and NYSE cash markets.

This is not a global foreign-exchange holiday calendar. FX spot is decentralised and its liquidity/holiday conventions are not identical to the local cash-equity exchange calendars. The exchange overlay is therefore **disabled by default** and is labelled CASH EXCHANGE HOLIDAYS / EARLY CLOSES. Use it only when your selected session hours are intended to represent those exchange venues.

The JPX holiday-trading programme for Osaka Exchange / Tokyo Commodity Exchange derivatives is separate and is not included. The ASX cash calendar is not the ASX 24 derivatives calendar. NYSE pre-market, late trading and product-specific calendars are not modelled. The LSE source covers its on-exchange trading services; OTC/SI off-book reporting availability can differ.

## Coverage limitations

- LSE's current business-day table begins the bundled period on 31 August 2026. Earlier LSE dates in 2026 are not treated as verified by this dataset.
- Dates beyond each venue's published coverage are shown as **OUT OF PUBLISHED RANGE**, not assumed to be confirmed normal trading days.
- Exchange notices may amend calendars. The source pages explicitly reserve the right to update published dates/hours; refresh this bundled file when a new annual calendar is published.
- This is an offline bundled snapshot, not a live exchange calendar API or an automatic update service.
- Official holidays do not represent emergency halts, unscheduled outages, security-specific suspensions, broker holidays or instrument-specific session hours.

Before trading, verify exceptional dates and special sessions against the exchange's latest notices and your broker.
