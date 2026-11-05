# 1XBet Scraper Setup

## 1. What changed in release 0.1.1

The recommended setup for the observed public English dashboard at `https://al-1xbet.com/en` is now the dedicated `1xbet_dashboard` adapter. It reads ordinary football full-time 1X2 selections from the actual dashboard structure and joins them to dated fixture metadata. This replaces a partial generic CSS recipe that could find price elements without supplying enough information to construct a valid quote.

A price and a team name alone are insufficient. The scanner must also know the fixture's permanent identity, ordered participants, sport, league, full scheduled date and timezone, market, outcome, and verified settlement rules. Release 0.1.1 checks incomplete configuration before making a public request and displays the source's actual reason near the top of a zero-quote result.

The adapter was checked offline against a user-supplied 3 November 2026 page snapshot. At the appropriate historic observation time, nine ordinary football fixtures yielded 27 offered 1X2 quotes. The same historic fixtures are correctly rejected as no longer pre-match when checked after their starts. That is evidence about parsing and date handling, not proof that a fresh live page is accessible now or that a bet can be accepted.

The snapshot contains full fixture dates. It does not establish when the odds themselves were last updated. The adapter therefore leaves `source_updated_at` unknown. Keep that distinction in mind before choosing the scanner's source-age settings.

No bookmaker login, session cookies, CAPTCHA solver, or paid proxy service is used. No official free 1XBet API or complete multi-sport feed is bundled. See `docs/source-evidence.md` for current access observations; they are separate from offline adapter tests.

## 2. Install and start on Windows 11

Download the supplied release, extract it to a private directory, and open PowerShell in the directory containing `pyproject.toml` and `uv.lock`. Install the optional browser dependency and Chromium, then start the local application.

```powershell
uv sync --frozen --extra browser
uv run playwright install chromium
uv run arbscanner
```

If uv is installed as a Python module rather than a command on PATH, replace `uv` with `py -3.12 -m uv`. Open `http://127.0.0.1:8000` and keep the terminal running. Stop the server with Ctrl+C.

HTML mode is possible when a normal public response already contains the complete dashboard and fixture metadata. Browser mode is the supplied starting point because the public frontend may render prices dynamically. Chromium availability is a local prerequisite; it does not establish access permission or bypass a challenge.

## 3. Load the complete adapter configuration

1. Open `examples/1xbet-dashboard.json` from this release in a text editor.
2. Open Data sources in the dashboard and locate 1XBet.
3. Replace the old partial source JSON with the complete example.
4. Keep unrelated incomplete sources disabled while checking this adapter.
5. Review the rule confirmation and source-age choices in the next sections before enabling it.

Software updates preserve existing source settings in your local database. Replacing application files with release 0.1.1 does not automatically migrate an old partial CSS configuration. Paste and save the complete adapter example explicitly for the existing 1XBet source.

The example selects these essential settings. Consult the actual example file for the authoritative complete configuration shipped with the version you downloaded.

```json
{
  "adapter": "1xbet_dashboard",
  "mode": "browser",
  "url": "https://al-1xbet.com/en",
  "allowed_hosts": ["al-1xbet.com", "v3.traincdn.com"],
  "wait_selector": ".dashboard-game:has(.dashboard-game-action-bar[islive='false'])",
  "min_interval_seconds": 10,
  "max_pages": 1,
  "pages": [],
  "rules_confirmed": false,
  "constants": {
    "period": "full_time",
    "rules": "",
    "currency": "EUR"
  }
}
```

`allowed_hosts` covers the profile and an explicit public resource host used by the observed frontend. It does not permit fixture identity to move to another bookmaker or regional mirror. In a restricted cloud machine, the outbound network policy must independently permit the actual needed destinations.

The adapter does not require a generic `event_selector`, `quote_selector`, or field `mapping`. Those fields belong to the generic extraction mode, not the adapter's evidence-backed DOM/metadata join. Do not add a guessed `starts_at` constant to make the old partial mapping pass.

The example is deliberately incomplete in one important respect: it leaves the settlement rules unconfirmed. With the empty rule string and false confirmation flag, preflight must report an unconfigured source and make no source request. That is the expected initial behavior until you perform the next step.

## 4. Verify and confirm the settlement contract

The adapter recognizes one unambiguous W1 / X / W2 group for an ordinary full-time football match. Those labels identify home, draw, and away selections. They do not, by themselves, prove whether a site's settlement includes extra time or a different product.

1. Open the exact public market in a private browser window without logging in.
2. Read the displayed market name and applicable rules.
3. Confirm that the market is the regulation-time full-match result, if that is the contract you intend to compare.
4. If confirmed, set `constants.rules` to `regulation`.
5. Only after verifying the market and active-state semantics, set `rules_confirmed` to true.
6. Save the source and enable it for one narrow scan.

If the contract differs, use an accurate compatible label only after checking that the adapter's scope still applies. Do not label qualification, first-half, aggregate, or overtime-inclusive outcomes as regulation-time match result. The current adapter is not intended for those products.

A nonempty `constants.league`, when supplied, acts as an exact normalized league filter. It does not overwrite every event's real competition name. Leave it absent to accept the supported dashboard's ordinary football fixtures across their actual leagues. A supplied sport constant must mean association football; the output canonical sport is `soccer`.

## 5. How the adapter establishes a fixture

### 5.1 Dashboard rows and offered prices

The adapter inspects `.dashboard-game` containers. A supported row has one pre-match action bar with `islive` exactly false, one fixture link on the profile's ordinary pre-match football route, ordered participant names in the known dashboard fields, and exactly one W1/X/W2 market group.

It checks offered-state markup before reading a price. Locked, empty, disabled, aria-disabled, and lock-marked selections are rejected. Prices must be valid decimal odds. The adapter does not collect every number on a dashboard row, infer outcomes from button positions, or guess American or fractional price formats.

### 5.2 Full dates from structured metadata

Fixture metadata comes from one of two observed representations: SportsEvent JSON-LD, or a known dashboard schedule array inside the page's embedded application state. JSON-LD supplies a full offset-bearing `startDate`, named participants and organizer, association-football identity, and a canonical fixture URL.

The known schedule representation supplies a permanent fixture ID, participants, competition, pre-match status, and explicit Unix start fields. When both seconds and milliseconds are present, they must agree. Conflicting metadata for one fixture invalidates that join instead of letting another representation silently rescue it.

Nested application strings are decoded as JSON data. The adapter does not evaluate embedded JavaScript. It accepts a narrow known schedule shape rather than searching every arbitrary object for a date-like number.

### 5.3 Identity and status must agree

The fixture route's permanent ID, ordered participant names, full scheduled instant, canonical URL when supplied, and pre-match state must agree. Metadata for a different event cannot be attached by a similar name or a nearby time. Special-bet groups, dummy entries, subgames, already-started fixtures, and ambiguous market groups are excluded.

A future fixture start must be later than the observation time. A saved historic page can still demonstrate the parser's structure while correctly producing no current pre-match data. Never move a historic date into the future just to get nonzero quote counts.

## 6. Choose how to handle unknown price age

`starts_at` answers when the match begins. `observed_at` answers when this program read the page. `source_updated_at` would answer when the source last updated the price. They are separate facts.

The inspected dashboard establishes the first two, but not the third. The adapter therefore sets `source_updated_at` to null. It never substitutes the match date, the current clock, a page-build timestamp, or retrieval time as an odds-update claim.

By default, Require source update timestamps is checked in Advanced matching & filters. Under that strict setting, extracted adapter quotes are rejected from arbitrage calculations with `unknown_source_age`. The source may have a positive quote count and the opportunity list may still be empty; inspect both counts before diagnosing a parsing failure.

If you consciously accept retrieval-only uncertainty, uncheck Require source update timestamps and save preferences. The scanner then applies the observation-age and quote-time-spread controls, and affected opportunities warn that an old bookmaker price can look recently fetched. This changes a stated freshness assumption; it does not make the price objectively fresh.

Keeping the strict default is a valid choice. A source without a genuine price-update timestamp is not compatible with that requirement. No configuration flag can manufacture the missing source fact.

## 7. Run one useful verification scan

1. Select live mode and enable only the prepared 1XBet source.
2. Save its complete adapter config with your verified rule label and confirmation.
3. Press Scan once and wait for completion.
4. Read the named source diagnostic near the top and the Source health card.
5. Open Extracted quote preview, which can show up to 100 canonical quotes even if no opportunity passes.
6. Compare event ID, home/away names, sport, league, full start, market, outcome, rules, price, observation time, and null source-update time with the actual public page.
7. Review rejected counts and metadata messages before adding another source.

One bookmaker is normally insufficient for a cross-bookmaker arbitrage opportunity. A successful extraction is the first verification stage, not an expectation that a profitable result must appear. Configure another genuinely supported source for the exact same future event and settlement contract before expecting cross-book comparisons.

A cooldown prevents rapid repeated scans. Browser and HTTP collection retain request delays, robots checks, destination restrictions, timeouts, and no-login behavior. Changing the minimum-profit filter cannot repair a blocked request, missing fixture metadata, or an incomplete source mapping.

## 8. Diagnose the actual named error

### 8.1 Setup incomplete; no request made

A false `rules_confirmed` flag or an empty verified rule label is intentionally unconfigured. Confirm the real rules as described above. An old generic configuration may also list missing required fields such as starts_at or outcome. Replace that partial recipe with the complete adapter example rather than setting random constants.

### 8.2 No usable fixture metadata

The adapter needs matching full dated schedule metadata, not just the visible HH:MM clock. Check that the current public response contains SportsEvent JSON-LD or the supported embedded dashboard schedule data and that the DOM has rendered. If the site changed its schema, the adapter needs a code update and fresh tests. Do not hardcode a date or pair prices with an unrelated JSON object.

### 8.3 No valid odds extracted

Inspect whether the page contains supported ordinary pre-match football rows, exact offered W1/X/W2 groups, correct profile routes, consistent metadata, and future starts. If all fixtures in a saved snapshot are already historic, zero current quotes is correct. Unsupported sports or alternative market layouts are outside this adapter.

### 8.4 Blocked, challenge, or login

Read the precise source message. A robots restriction, HTTP denial, challenge, regional limit, or visible login requirement is an access problem. A generic browser install does not bypass it. Do not import cookies, credentials, or evasion services. Confirm public access on your own Windows 11 machine and record the observed limitation.

### 8.5 Quotes exist; unknown_source_age rejects them

This is the default freshness policy working. Keep the strict setting, choose another source with real price-update timestamps, or explicitly accept retrieval-only mode as explained above. Altering the match's start date is unrelated and incorrect.

### 8.6 Bet365 is still unconfigured

The 1XBet adapter belongs only to the 1XBet source. Bet365 still needs its own complete public route and field mapping or a separately implemented adapter. Setting its confirmation flag true cannot supply missing starts_at, participant, market, or outcome fields. Do not copy the 1XBet adapter ID into Bet365's settings.

## 9. Generic extraction for another verified layout

Use the dedicated adapter for the supported dashboard. If you later identify a different public 1XBet layout, generic HTML or JSON mapping remains available by removing the adapter field and supplying every required canonical value. The following excerpt illustrates the mapping language on a controlled structure. It is not a claim that these classes exist on the current bookmaker page.

```json
{
  "mode": "html",
  "event_selector": ".verified-fixture",
  "quote_selector": ".offered-selection",
  "inactive_selector": ".suspended",
  "mapping": {
    "home": {"selector": ".home", "scope": "event"},
    "away": {"selector": ".away", "scope": "event"},
    "starts_at": {
      "selector": "time", "scope": "event", "attr": "datetime"
    },
    "outcome": {
      "attr": "data-side",
      "values": {"1": "home", "X": "draw", "2": "away"}
    },
    "odds": ".decimal-price"
  }
}
```

A complete generic configuration also needs a public URL, verified allowed hosts, sport, league, market, period, rules, currency, active-state interpretation, and rule confirmation. A constant is appropriate only if it applies to every selected row. For nested JSON use `events_path`, `markets_path`, `outcomes_path`, and context paths such as `$event.start` or `$quote.price`; consult Code Explained for the field language and explicit transforms.

The original bug arose because a partial extraction recipe could find prices but did not define a complete canonical quote. The new preflight makes those omissions visible before network access. That check validates configuration completeness; live page shape and field correctness still need inspection.

## 10. Tests, evidence, and privacy

Run the project tests from the checkout root. The adapter tests use sanitized controlled fixtures and explicit observation times for past snapshots. They cover identity mismatches, metadata conflicts, invalid starts, inactive prices, unsupported groups, and source-time honesty as well as accepted rows.

```powershell
uv run pytest
```

A passing test verifies the represented structure and constraints. It does not establish current site accessibility, authorization to scrape, exact live market rules, arbitrage frequency, or bookmaker acceptance. The release's evidence ledger records live observations separately from offline checks.

The user's original supplied PDF, complete HTML, and raw reports are private investigation materials. They are not bundled in the public source archive or these PDFs. Only the adapter logic, sanitized fixtures, and aggregate verification results belong in the release.

## 11. Extend or maintain the adapter

The present scope is ordinary association-football full-time 1X2. Adding tennis, basketball, esports, totals, handicaps, periods, or special products requires a separately verified market interpretation and tests. Broadening a CSS selector alone does not add settlement support.

When the site changes, capture only the public structural facts needed for a sanitized regression fixture. Verify identity, dated start, pre-match state, offered price markers, market labels, and price-update availability. Update the parser and tests before re-enabling a source that became uncertain. Keep a dated record of the exact domain, mode, covered market, live-access result, timestamp limitation, and direct comparison with the public page.
