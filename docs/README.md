# English manuals

The release contains seven PDFs, 69 pages in total, generated from the Markdown in this directory. GitHub downloads are in `downloads/arbitrage-finder-windows.zip` (software and guides) and `downloads/arbitrage-finder-guides.zip` (PDFs only). Open the ZIP's GitHub file page and choose Download raw file. Local build copies also live in `dist/`.

- [Setup and Operations Guide, 14 pages](pdf/01-setup-and-operations.pdf)
- [Code Explained, 15 pages](pdf/02-code-explained.pdf)
- [Bet365 Scraper Setup, 8 pages](pdf/03-bet365-scraper-setup.pdf)
- [Stake Scraper Setup, 8 pages](pdf/04-stake-scraper-setup.pdf)
- [1XBet Scraper Setup, 8 pages](pdf/05-1xbet-scraper-setup.pdf)
- [Marathonbet Scraper Setup, 8 pages](pdf/06-marathonbet-scraper-setup.pdf)
- [Bet105 Scraper Setup, 8 pages](pdf/07-bet105-scraper-setup.pdf)

Read the [source evidence and release limits](source-evidence.md) before treating a bookmaker as a verified feed. The generic scraper engine is implemented; the five live bookmaker mappings are not established. Synthetic tests and demo quotes do not verify live source access.

Rebuild from the checkout root:

```bash
uv sync --frozen --group docs
uv run --group docs python tools/build_docs.py
```

The PDFs contain linked contents pages and navigation bookmarks. The generator works locally without a paid service.
