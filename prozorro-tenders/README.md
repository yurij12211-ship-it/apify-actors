# Prozorro Tenders Scraper

Extract public procurement tenders from **Prozorro**, Ukraine's national e-procurement system, through its official open API. Filter by modification date, keywords, CPV (ДК 021:2015) codes, buyer region, status and budget, and get clean JSON, CSV or Excel with the buyer, expected value, deadlines, items and document links.

Ukraine publishes every public tender above the reporting threshold on Prozorro: roughly 1–2 million procedures a year across central government, municipalities, hospitals, schools, utilities and state companies. This Actor turns that feed into a filtered, structured dataset you can schedule, export or pipe into Google Sheets, a CRM or a Slack alert.

## What you get

One record per matching tender:

| Field | Example |
|---|---|
| `tenderID` | `UA-2026-11-09-001234-a` |
| `title` | Закупівля ноутбуків для закладів освіти |
| `status` | `active.tendering` |
| `procurementMethodType` | `belowThreshold`, `aboveThreshold`, `reporting`, … |
| `valueAmount`, `valueCurrency` | `1250000`, `UAH` |
| `buyerName`, `buyerEDRPOU`, `buyerRegion`, `buyerLocality` | buyer organisation, tax ID, region, city |
| `contactName`, `contactEmail`, `contactPhone` | the buyer's published contact point |
| `tenderStartDate`, `tenderEndDate`, `enquiryEnd` | key deadlines |
| `cpvCodes`, `cpvDescriptions` | all ДК 021 codes on the tender |
| `items[]` | description, CPV, quantity, unit, delivery region |
| `documents[]` (optional) | title, URL, format of each attached document |
| `url` | link to the tender on prozorro.gov.ua |

## Input

| Input | Meaning |
|---|---|
| **Modified since / until** | The feed is ordered by modification time; this bounds how much is scanned. Default: last 24 hours. |
| **Keywords** | Any keyword in the title, description or item descriptions keeps the tender (case-insensitive, Ukrainian or English). |
| **CPV prefixes** | e.g. `30` computers, `33` medical, `45` construction, `72` IT services, `09` fuel. |
| **Buyer regions** | Substring match on the buyer's region, e.g. `Київ`, `Львівська`. |
| **Statuses** | Default: `active.enquiries`, `active.tendering` (open for bids). |
| **Min / max value** | Expected value in UAH. |
| **Max tenders / max scanned** | Output cap and request cap. |
| **Include document links** | Adds the `documents[]` array. |

### Example: open IT tenders in Kyiv above 500k UAH, last 3 days

```json
{
  "dateFrom": "2026-11-06",
  "cpvPrefixes": ["30", "48", "72"],
  "regions": ["Київ"],
  "statuses": ["active.enquiries", "active.tendering"],
  "minValue": 500000,
  "maxItems": 500
}
```

### Example: daily alert for medical supplies nationwide

Schedule the Actor daily with `keywords: ["рукавички", "шприц", "маск"]` and `cpvPrefixes: ["33"]`, then connect an Apify integration (Google Sheets, Slack, email or webhook) to the dataset.

## How it works

1. Reads the public tender feed `/api/2.5/tenders` from the given date forward (100 tenders per page).
2. Fetches each tender's full record in parallel (default 8 concurrent requests, polite retries with backoff).
3. Applies your filters and pushes normalized records to the dataset.
4. Stops at `maxItems`, `maxScanned` or the end of the feed, and writes a `SUMMARY` record to the key-value store.

Only public data from the official API is used. No login, no scraping of the website UI, no bypassing of any protection.

## Pricing

Pay per event: a small fee per tender saved to the dataset plus a start fee per run. You only pay for matching tenders, not for everything scanned. Typical daily alert runs (a few dozen matches) cost cents. The free Apify plan covers hundreds of tenders a month.

## Tips

- Narrow **Modified since** first. A week of the full feed is tens of thousands of tenders; a keyword or CPV filter does not reduce scanning, only output.
- Statuses: use `active.enquiries` + `active.tendering` to see what you can still bid on; add `complete` and `active.awarded` for market analysis of who won what.
- CPV codes are hierarchical. `3321` matches `33210000-9` and everything under it.
- For historical analysis across months, raise `maxScanned` and run with a larger memory setting, or split the period into several scheduled runs.

## Related data

Looking for Polish, Romanian or EU-wide tenders (BZP, SEAP, TED), or for supplier/company registries? Check the other Actors by this author or contact me through Apify for a custom source.

## Changelog

- 0.1: initial release — feed walking, filters, normalized output, optional document links, pay-per-event.
