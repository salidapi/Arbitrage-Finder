# Data Source Evidence and Release Limits

Evidence updated: 5 November 2026 for release 0.1.1. This record distinguishes original development observations, offline inspection of a supplied 3 November page snapshot, and the current live-fetch attempt. It is not a claim that any bookmaker is accessible from every Albanian connection or that a provider's free plan has specific permanent terms.

## Confirmed requirements

- Personal, local Windows 11 dashboard with no required hosting subscription.
- Pre-match prices; manual Scan button; no scheduler, alerts, or automated betting.
- Minimum profit editable in the dashboard.
- Optional provider API key entered through a dedicated masked dashboard field.
- English setup and code manuals, plus a separate English scraper manual for each requested bookmaker.
- User-confirmed sites: bet365.com, stake.com, al-1xbet.com/en, marathonbet.com/en, and bet105.ag.

## Environment evidence

Network observations below describe the original development session. After environment publication, the bookmaker/API hostnames were present in the enforced allowlist. Their live page mappings and API coverage have not been validated since that change. GitHub delivery is a separate operation, and its success must be confirmed by a remote Git check.

The managed development environment has a restricted, enforced outbound policy. The selected bookmaker/API destinations were not in its initial package-manager preset. One actual public connectivity probe, an HTTPS HEAD request to `https://www.bet365.com/`, received a platform-proxy CONNECT denial (HTTP 403). The other requested bookmaker and API domains were absent from the initial allowed list and were not live-tested; their real responses remain unknown. A draft update for required domains was saved by the main agent; saving that draft does not apply it to the current machine or publish a new environment.

This is evidence of a development-environment access restriction. It is not evidence that the bookmakers themselves returned the same denial, that their robots files prohibit these paths, that they provide no free API, or that they cannot be accessed from the user's own computer.

On 5 November, a normal `fetch_public_page` attempt for `https://al-1xbet.com/en` failed public-host DNS validation with `SourceBlocked: Source hostname could not be resolved`. No target HTML was retrieved in that attempt. This is a cloud-machine resolution observation, not a denial returned by 1XBet and not a test of the user's Windows connection. It does not verify current live adapter coverage.

Separately, the reported zero-quote symptom could be reproduced without a network operation: a partial generic configuration lacked required canonical fields and retained `rules_confirmed: false`. The 0.1.1 preflight now reports these exact setup issues and explicitly marks when no source request was made. That configuration failure and the later DNS failure are independent observations.

## Bookmaker evidence

### Bet365

Requested site: https://bet365.com. Profile ID: `bet365`. Default public URL: https://www.bet365.com/. Implemented modes: configured public HTML, JSON, and anonymous browser extraction. Current site-specific selectors, public payload paths, active-status behavior, settlement interpretation, source timestamp availability, and real odds access are not live-validated.

### Stake

Requested site: https://stake.com. Profile ID: `stake`. Implemented modes: configured public HTML, JSON, and anonymous browser extraction. Current sportsbook page structure and anonymous data route are not live-validated. The browser mode permits GET operations only; a frontend requiring a POST data request may not work through that route. No official free Stake sportsbook API availability is established here.

### 1XBet

Requested site: https://al-1xbet.com/en. Profile ID: `1xbet`. Release 0.1.1 adds `adapter: 1xbet_dashboard` for the inspected English public dashboard, alongside generic HTML/JSON/browser modes. It joins offered ordinary football W1/X/W2 DOM prices to exact permanent fixture identity and full dates from matching SportsEvent JSON-LD or safely decoded known schedule JSON. It does not execute the embedded application scripts or invent a date.

Offline analysis of the user-supplied 3 November snapshot produced 27 prices across nine ordinary football fixtures at the relevant historic observation time. Those same fixtures are rejected as already started at a later observation time. This verifies the represented snapshot's parsing and identity/date checks, not present live access, current price acceptance, or every sport and market. The private original PDF, full HTML, and raw reports are not release artifacts; only implementation logic and sanitized tests are published.

The inspected metadata contains fixture dates but no authoritative odds-update timestamp. The adapter therefore leaves `source_updated_at` unknown. The scanner's default strict source-timestamp requirement excludes these prices as `unknown_source_age`. Retrieval-only use requires an explicit user choice and carries a warning. Settlement rules also require independent confirmation; the shipped recipe leaves its rule label empty and `rules_confirmed` false. No guessed LineFeed endpoint, hidden date constant, or free complete regional feed is asserted to work.

### Marathonbet

Requested site: https://marathonbet.com/en. Profile ID: `marathonbet`. Default URL includes the English path and www hostname. Configurable HTML, JSON, and browser modes are implemented. Current page selectors, disabled-selection handling, timestamps, and supported regional coverage remain unverified.

### Bet105

Requested site: https://bet105.ag. Profile ID: `bet105`. The .ag domain is the confirmed site; a .com host is not substituted. Configurable HTML, JSON, and browser modes are implemented. The actual sportsbook renderer, public odds payloads, price display format, vendor hosts, and settlement rules remain unverified.

## Optional provider evidence

The Odds API connector implements the v4 sports catalog and bounded standard odds requests using a user-supplied key. Controlled tests cover payload parsing, selected-bookmaker filtering, market classification, handicap normalization, request limits, and safe errors. No live account key was supplied during development, so live credential authorization, free allowance, regional bookmaker coverage, and real update frequency were not established.

Reference for the user's own current plan and API documentation: https://the-odds-api.com/. This is a reference link, not a statement that its current website or pricing was successfully retrieved and reviewed in this restricted environment. Verify the provider's present documentation and account settings before using it. Do not assume all five requested bookmakers appear in its feed.

## What controlled validation demonstrates

The implementation is tested using synthetic quote sets, HTML pages, JSON payloads, mock network behavior, temporary databases, local HTTP integration checks, and browser interactions with the local dashboard. These checks establish behavior of the implemented software under those conditions.

They do not establish current bookmaker availability, permission to scrape, live consistency of a snapshot-derived source layout, real betting opportunity frequency, bookmaker bet acceptance, or five-site free live coverage. The 1XBet adapter has offline snapshot evidence; the other site-specific mappings remain independent work. Demo quotes remain explicitly fictional and imports remain explicitly supplied data.

## Conditions for upgrading a source to verified

Record the exact public domain and page, verification date, retrieval mode, relevant source rules, actual mapping, sport/league/market coverage, active/suspended test, timezone interpretation, genuine source-update availability, and a direct comparison of canonical quote samples with the public display. Retain a sanitized fixture and parser regression tests. Record any unsupported routes or market types. A later site change can invalidate that verification and should return the source to an unverified state until rechecked.

## Scope that remains outside this release

The application does not supply verified turnkey scrapers for all five sites, a guaranteed free complete odds feed, every possible market contract, automatic fuzzy event joins, account balance synchronization, fees/taxes/FX optimization, bet placement, or Internet-facing multi-user hosting. These are distinct implementation or access requirements, not capabilities implied by a working local dashboard.
