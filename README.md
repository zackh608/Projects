# Projects

## Collectible Deal Scanner

This repository includes a lightweight Python CLI that scans RSS feeds from saved searches and flags likely deals.

### Files
- `deal_scanner.py` — scanner and scoring logic.
- `scanner_config.example.json` — example config with coin/card/vinyl searches.

### Quick start
```bash
python3 deal_scanner.py --config scanner_config.example.json --limit 20
```

### Config format
```json
{
  "searches": [
    {
      "name": "Any label",
      "rss_url": "https://...",
      "max_price": 100.0,
      "required_terms": ["term1", "term2"],
      "exclude_terms": ["badterm"]
    }
  ]
}
```

### Notes
- Use saved-search RSS URLs from marketplaces where available.
- This script ranks leads; it does not auto-buy.
- Always verify authenticity, condition, shipping costs, and sold comparables before purchase.
