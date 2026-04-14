#!/usr/bin/env python3
"""Collectible deal scanner using RSS feeds.

This script scans configurable RSS feeds (e.g., saved searches from marketplaces),
extracts listing price/title/link/date, applies per-search filters, and prints a
ranked deal list.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import re
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from typing import Any


PRICE_RE = re.compile(r"\$\s*([0-9]+(?:\.[0-9]{1,2})?)")


@dataclasses.dataclass
class SearchConfig:
    name: str
    rss_url: str
    max_price: float | None = None
    required_terms: list[str] = dataclasses.field(default_factory=list)
    exclude_terms: list[str] = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class Listing:
    source: str
    title: str
    link: str
    price: float | None
    published: dt.datetime | None
    score: float
    reason: str


def load_config(path: str) -> list[SearchConfig]:
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    searches = []
    for item in raw.get("searches", []):
        searches.append(
            SearchConfig(
                name=item["name"],
                rss_url=item["rss_url"],
                max_price=item.get("max_price"),
                required_terms=item.get("required_terms", []),
                exclude_terms=item.get("exclude_terms", []),
            )
        )

    if not searches:
        raise ValueError("No searches found in config. Add at least one entry in searches[].")

    return searches


def fetch_xml(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "collectible-deal-scanner/1.0 (+https://example.local)",
            "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def parse_price(text: str) -> float | None:
    if not text:
        return None
    m = PRICE_RE.search(text)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def parse_date(text: str | None) -> dt.datetime | None:
    if not text:
        return None
    try:
        d = parsedate_to_datetime(text)
        if d.tzinfo is None:
            return d.replace(tzinfo=dt.timezone.utc)
        return d.astimezone(dt.timezone.utc)
    except Exception:
        return None


def text_of(el: ET.Element | None, tag: str) -> str:
    if el is None:
        return ""
    child = el.find(tag)
    if child is not None and child.text:
        return child.text.strip()
    return ""


def score_listing(cfg: SearchConfig, title: str, price: float | None) -> tuple[float, str] | None:
    lowered = title.lower()

    for blocked in cfg.exclude_terms:
        if blocked.lower() in lowered:
            return None

    missing_required = [t for t in cfg.required_terms if t.lower() not in lowered]
    if missing_required:
        return None

    score = 50.0
    reasons = []

    if cfg.max_price is not None:
        if price is None:
            reasons.append("price unknown")
        elif price <= cfg.max_price:
            discount = max(0.0, (cfg.max_price - price) / max(cfg.max_price, 1e-9))
            score += 40.0 * discount
            reasons.append(f"under max by {discount * 100:.0f}%")
        else:
            return None

    if cfg.required_terms:
        score += 5.0
        reasons.append("all required terms matched")

    if not reasons:
        reasons.append("matched filter")

    return score, "; ".join(reasons)


def parse_rss(cfg: SearchConfig, xml_text: str) -> list[Listing]:
    root = ET.fromstring(xml_text)
    items = root.findall(".//item")
    listings: list[Listing] = []

    for item in items:
        title = text_of(item, "title")
        link = text_of(item, "link")
        desc = text_of(item, "description")
        pub_raw = text_of(item, "pubDate")
        price = parse_price(title) or parse_price(desc)

        scored = score_listing(cfg, title=title, price=price)
        if scored is None:
            continue

        score, reason = scored
        listings.append(
            Listing(
                source=cfg.name,
                title=title,
                link=link,
                price=price,
                published=parse_date(pub_raw),
                score=score,
                reason=reason,
            )
        )

    return listings


def format_money(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"${value:,.2f}"


def print_listings(rows: list[Listing], limit: int) -> None:
    print(f"Found {len(rows)} matching listings")
    print("-" * 110)
    print(f"{'Score':>6}  {'Price':>10}  {'Source':<18}  {'Published (UTC)':<22}  Title")
    print("-" * 110)

    for row in rows[:limit]:
        published = row.published.isoformat(timespec="seconds") if row.published else "unknown"
        print(f"{row.score:6.1f}  {format_money(row.price):>10}  {row.source:<18}  {published:<22}  {row.title}")
        print(f"{'':>6}  {'':>10}  {'':<18}  {'':<22}  -> {row.link}")
        print(f"{'':>6}  {'':>10}  {'':<18}  {'':<22}  -> {row.reason}")


def run(config_path: str, limit: int) -> int:
    try:
        searches = load_config(config_path)
    except Exception as e:
        print(f"Config error: {e}", file=sys.stderr)
        return 2

    all_rows: list[Listing] = []
    for cfg in searches:
        try:
            xml_text = fetch_xml(cfg.rss_url)
            rows = parse_rss(cfg, xml_text)
            all_rows.extend(rows)
        except urllib.error.URLError as e:
            print(f"Warning: could not fetch {cfg.name}: {e}", file=sys.stderr)
        except ET.ParseError as e:
            print(f"Warning: invalid XML from {cfg.name}: {e}", file=sys.stderr)

    all_rows.sort(key=lambda r: (r.score, r.published or dt.datetime.min.replace(tzinfo=dt.timezone.utc)), reverse=True)
    print_listings(all_rows, limit=limit)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Scan collectible RSS feeds and rank potential deals.")
    p.add_argument("--config", default="scanner_config.example.json", help="Path to JSON config file.")
    p.add_argument("--limit", type=int, default=25, help="Max rows to print.")
    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return run(config_path=args.config, limit=args.limit)


if __name__ == "__main__":
    raise SystemExit(main())
