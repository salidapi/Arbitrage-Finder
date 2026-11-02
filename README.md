# Arbitrage Finder

A private Windows 11 friendly web workbench for **manual pre-match scans**. No hosting subscription, paid service, bookmaker login, betting automation, alerts, or scheduler is required. Open-source dependencies run on your own computer.

## Current status — read before using real money

The dashboard, Decimal-based calculation engine, encrypted local API-key storage, imports, and configurable public HTML/JSON/browser scrapers are implemented and tested. **None of the five bookmaker page mappings has been live-verified.** These are source profiles and scraper tools, not five turnkey feeds. Until public odds pages are reachable and their mappings and settlement rules verified, a live scan cannot obtain usable bookmaker odds. Demo mode uses entirely fictional prices.

During initial development, the cloud proxy denied the Bet365 probe and live source mappings were not verified. Network settings have since changed; real source access and coverage still need validation. A region-specific site may additionally restrict automation or require login. The software stops at denials and challenges. A subscription-free feed covering all five sites is **not established**. The optional The Odds API connector needs your own free-plan key, verified coverage, and sufficient remaining quota; no key or plan is provided.

## Downloads

On GitHub, open the [`downloads/`](downloads/) folder to download `arbitrage-finder-windows.zip` (source code and all guides) or `arbitrage-finder-guides.zip` (seven English PDFs only). Open an archive's file page and choose **Download raw file**. Individual PDFs are also in [`docs/pdf/`](docs/pdf/). The repository's **Code → Download ZIP** option downloads the complete checkout.

Extract the Windows source archive before running the commands below. It is a source distribution, not a compiled Windows installer. The implementation was tested in the Linux cloud environment; Windows 11 setup steps are documented in the operating guide.

| Source | Requested site | Integration status |
|---|---|---|
| Bet365 | `https://bet365.com` | Configurable anonymous scraper; live mapping unverified |
| Stake | `https://stake.com` | Configurable anonymous scraper; live mapping unverified |
| 1XBet | `https://al-1xbet.com/en` | Configurable anonymous scraper; live mapping unverified |
| Marathonbet | `https://marathonbet.com/en` | Configurable anonymous scraper; live mapping unverified |
| Bet105 | `https://bet105.ag` | Configurable anonymous scraper; live mapping unverified |
| Custom source | Your approved public HTTPS source | Generic HTML, JSON, or browser configuration |
| The Odds API | Optional provider key | Parser/request logic tested with synthetic fixtures; live coverage unverified |

## Windows 11 quick start

Install Python 3.12 or newer from python.org, then open PowerShell in this checkout:

```powershell
py -3.12 -m pip install uv
py -3.12 -m uv sync --frozen
py -3.12 -m uv run arbscanner
```

Open `http://127.0.0.1:8000` in your browser. Keep the terminal running. Stop with Ctrl+C. If that port is occupied, use `py -3.12 -m uv run arbscanner --port 8001`. There is deliberately no public bind-address option.

On macOS/Linux, use `uv sync --frozen` and `uv run arbscanner` after installing Python 3.12+ and uv. In this managed cloud environment, use `UV_CACHE_DIR=/workspace/.cache/uv` if the default cache is read-only. Network/socket operations may require the execution tool's permission scope.

### First useful check

1. Select **Demo** in the dashboard, set minimum profit to **0.5%**, and click **Scan for arbitrage**. The result should explicitly show sample data and one fictional three-way opportunity.
2. Switch back to **Live**. An unconfigured source must show its configuration problem; it must never fall back to demo prices.
3. In **Data sources**, configure public page mappings and verify quotes manually using each source's PDF. Enable only working, checked sources. Settlement rules and active/suspended state must be confirmed.
4. If using The Odds API, enter the key in its dedicated masked dashboard field, then configure exact provider sport/bookmaker keys and request limits in the source JSON. Keys are never needed in chat, committed files, or browser storage.
5. Set the minimum return, stake budget, freshness and filters. Click Scan whenever you want. Scans use only quotes obtained by that scan; history is never reused as current odds.

## What the scanner checks

- Two-way winners, three-way winners, half-line totals and half-line handicaps, for any sport/league whose source supplies a complete canonical contract.
- Exact event start times, sport, league, home/away orientation, period, settlement rules, line and currency. Matching normalizes case and whitespace only. No fuzzy name matching. This favours missed matches over incorrectly pairing different events.
- Future events, fresh observations/source updates, compatible quote timestamps and complete outcomes from at least two bookmakers.
- Stakes rounded to cents, payouts rounded down to cents, total stake within the configured **per-opportunity budget**, and the **worst outcome's net return** above your threshold.

`minimum_profit` is a percentage return on total stake, not reciprocal-odds margin. With reciprocal sum `S`, ideal return is `(1/S - 1) * 100%`; the displayed return is recalculated from rounded stakes and payouts.

Integer and Asian quarter lines, props needing special settlement, pushes, dead heats, partial wins, fees/taxes, stake limits, account balances, FX conversion, bet placement and guaranteed acceptance are not modelled. Currency labels must agree; changing the label does not convert money. No scanner can ensure that displayed odds will still be accepted. Verify all legs and rules before betting.

Source timestamps are required by default. Disable that safeguard only when you consciously accept that a recently fetched page can contain old odds; affected opportunities show an explicit warning. Reading the page is not proof of odds freshness.

## Guides

English Markdown sources and **seven PDFs** are in [`docs/`](docs/): a detailed setup/operating guide, a code guide, and one setup guide per bookmaker scraper. Download them from the dashboard's Guides tab. The scraper guides describe how to establish a real mapping; they do not claim unverified selectors work.

## Development

```powershell
py -3.12 -m uv sync --frozen --group docs
py -3.12 -m uv run pytest
py -3.12 -m uv run --group docs python tools/build_docs.py
```

Optional JavaScript-rendered page support:

```powershell
py -3.12 -m uv sync --frozen --extra browser
py -3.12 -m uv run playwright install chromium
```

Browser mode starts a new anonymous browser context and supports no login/session import. Headless browser availability does not establish that a bookmaker permits or serves usable public odds.

## Local data and keys

Settings, source configs and up to 100 scans live in `.data/scanner.sqlite3`; API credentials are encrypted using `.data/secret.key`. The dashboard returns key presence only. Keep both files private. Encryption protects the database alone; anyone who can read the database and key can decrypt it. Windows users should keep the checkout in a private user directory and restrict its ACL. Do not commit `.data` or sync it to public/shared storage. Use `--data-dir` or `ARBSCANNER_DATA_DIR` for a different location. Back up both files to retain keys, or re-enter the key after recovery. This is a single-user localhost application, with no accounts or Internet-facing deployment support.

## Extension points

- `arbscanner/models.py`: validated canonical Quote/Settings models.
- `arbscanner/engine.py`: event/market grouping and stake math.
- `arbscanner/connectors/`: profiles, parsers, bounded public retrieval and optional API.
- `arbscanner/app.py`, `storage.py`: local HTTP endpoints and persistence.
- `static/`: framework-free dashboard; no external CDNs.
- `tests/`: deterministic math, parser, security and HTTP integration checks.
- `tools/build_docs.py`: repeatable English PDF generation.

All network sources are explicit and opt-in. Do not paste passwords, account cookies, or credentials into scraper JSON. Respect source rate limits, access restrictions and applicable terms. “Zero cost” means the software requires no subscription; your computer and Internet access remain prerequisites, and free APIs can change quotas or availability.
