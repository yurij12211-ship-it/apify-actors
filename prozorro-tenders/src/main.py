"""Prozorro Tenders Scraper.

Pricing: pay-per-event via the platform's built-in events (apify-actor-start,
apify-default-dataset-item), so every record pushed to the default dataset is charged
automatically. No custom charge calls are needed.

Walks the public Prozorro feed (ordered by dateModified), fetches each tender,
applies the user's filters and pushes normalized records to the default dataset.

API reference (OpenProcurement): https://public-api.prozorro.gov.ua/api/2.5/tenders
Only public data is accessed; no authentication, no anti-bot bypass.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from apify import Actor

API_BASE = "https://public-api.prozorro.gov.ua/api/2.5"
PAGE_LIMIT = 100
KYIV_TZ = timezone(timedelta(hours=2))


def _parse_date(value: str | None, *, end_of_day: bool = False) -> datetime | None:
    if not value:
        return None
    dt = datetime.fromisoformat(value[:10])
    if end_of_day:
        dt = dt + timedelta(days=1) - timedelta(microseconds=1)
    return dt.replace(tzinfo=KYIV_TZ)


def _norm(s: Any) -> str:
    return str(s or "").strip().lower()


def _matches(tender: dict, f: dict) -> bool:
    """Apply all filters to a full tender record."""
    status = tender.get("status")
    if f["statuses"] and status not in f["statuses"]:
        return False

    pmt = tender.get("procurementMethodType")
    if f["pmts"] and pmt not in f["pmts"]:
        return False

    value = (tender.get("value") or {}).get("amount")
    if f["min_value"] is not None and (value is None or value < f["min_value"]):
        return False
    if f["max_value"] is not None and value is not None and value > f["max_value"]:
        return False

    region = _norm(((tender.get("procuringEntity") or {}).get("address") or {}).get("region"))
    if f["regions"] and not any(r in region for r in f["regions"]):
        return False

    items = tender.get("items") or []
    cpv_codes = [str((it.get("classification") or {}).get("id") or "") for it in items]
    if f["cpv"] and not any(code.startswith(p) for code in cpv_codes for p in f["cpv"]):
        return False

    if f["keywords"]:
        haystack = " ".join(
            [_norm(tender.get("title")), _norm(tender.get("description"))]
            + [_norm(it.get("description")) for it in items]
            + [_norm((it.get("classification") or {}).get("description")) for it in items]
        )
        if not any(k in haystack for k in f["keywords"]):
            return False

    return True


def _normalize(tender: dict, include_documents: bool) -> dict:
    pe = tender.get("procuringEntity") or {}
    addr = pe.get("address") or {}
    contact = pe.get("contactPoint") or {}
    ident = pe.get("identifier") or {}
    value = tender.get("value") or {}
    tp = tender.get("tenderPeriod") or {}
    ep = tender.get("enquiryPeriod") or {}
    items = tender.get("items") or []
    lots = tender.get("lots") or []

    cpv_codes = sorted({str((it.get("classification") or {}).get("id") or "") for it in items} - {""})
    cpv_descriptions = sorted({str((it.get("classification") or {}).get("description") or "") for it in items} - {""})

    record = {
        "tenderID": tender.get("tenderID"),
        "id": tender.get("id"),
        "title": tender.get("title"),
        "description": tender.get("description"),
        "status": tender.get("status"),
        "procurementMethodType": tender.get("procurementMethodType"),
        "mainProcurementCategory": tender.get("mainProcurementCategory"),
        "valueAmount": value.get("amount"),
        "valueCurrency": value.get("currency"),
        "valueAddedTaxIncluded": value.get("valueAddedTaxIncluded"),
        "buyerName": pe.get("name"),
        "buyerEDRPOU": ident.get("id"),
        "buyerLegalName": ident.get("legalName"),
        "buyerRegion": addr.get("region"),
        "buyerLocality": addr.get("locality"),
        "buyerAddress": addr.get("streetAddress"),
        "contactName": contact.get("name"),
        "contactEmail": contact.get("email"),
        "contactPhone": contact.get("telephone"),
        "enquiryStart": ep.get("startDate"),
        "enquiryEnd": ep.get("endDate"),
        "tenderStartDate": tp.get("startDate"),
        "tenderEndDate": tp.get("endDate"),
        "dateModified": tender.get("dateModified"),
        "dateCreated": tender.get("dateCreated") or tender.get("date"),
        "cpvCodes": cpv_codes,
        "cpvDescriptions": cpv_descriptions,
        "itemsCount": len(items),
        "lotsCount": len(lots),
        "items": [
            {
                "description": it.get("description"),
                "cpv": (it.get("classification") or {}).get("id"),
                "cpvDescription": (it.get("classification") or {}).get("description"),
                "quantity": it.get("quantity"),
                "unit": (it.get("unit") or {}).get("name"),
                "deliveryRegion": (it.get("deliveryAddress") or {}).get("region"),
                "deliveryEndDate": (it.get("deliveryDate") or {}).get("endDate"),
            }
            for it in items
        ],
        "url": f"https://prozorro.gov.ua/tender/{tender.get('tenderID')}" if tender.get("tenderID") else None,
        "apiUrl": f"{API_BASE}/tenders/{tender.get('id')}",
    }

    if include_documents:
        record["documents"] = [
            {
                "title": d.get("title"),
                "url": d.get("url"),
                "format": d.get("format"),
                "documentType": d.get("documentType"),
                "dateModified": d.get("dateModified"),
            }
            for d in (tender.get("documents") or [])
        ]
    return record


async def _fetch_json(client: httpx.AsyncClient, url: str, params: dict | None = None, retries: int = 4) -> dict | None:
    delay = 1.0
    for attempt in range(retries):
        try:
            resp = await client.get(url, params=params)
            if resp.status_code == 404:
                return None
            if resp.status_code in (429, 500, 502, 503, 504):
                raise httpx.HTTPStatusError("retryable", request=resp.request, response=resp)
            resp.raise_for_status()
            return resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            if attempt == retries - 1:
                Actor.log.warning(f"Giving up on {url}: {exc}")
                return None
            await asyncio.sleep(delay)
            delay *= 2
    return None



async def main() -> None:
    async with Actor:
        inp = await Actor.get_input() or {}

        date_from = _parse_date(inp.get("dateFrom")) or (datetime.now(KYIV_TZ) - timedelta(days=1))
        date_to = _parse_date(inp.get("dateTo"), end_of_day=True)
        filters = {
            "keywords": [_norm(k) for k in (inp.get("keywords") or []) if _norm(k)],
            "cpv": [str(c).strip() for c in (inp.get("cpvPrefixes") or []) if str(c).strip()],
            "regions": [_norm(r) for r in (inp.get("regions") or []) if _norm(r)],
            "statuses": set(inp.get("statuses") or []),
            "pmts": set(inp.get("procurementMethodTypes") or []),
            "min_value": inp.get("minValue"),
            "max_value": inp.get("maxValue"),
        }
        max_items = int(inp.get("maxItems") or 200)
        max_scanned = int(inp.get("maxScanned") or 5000)
        include_docs = bool(inp.get("includeDocuments"))
        concurrency = max(1, min(int(inp.get("concurrency") or 8), 20))

        Actor.log.info(
            f"Scanning Prozorro feed from {date_from.isoformat()} "
            f"to {date_to.isoformat() if date_to else 'now'}; filters={ {k: (sorted(v) if isinstance(v, set) else v) for k, v in filters.items()} }"
        )

        headers = {"User-Agent": "prozorro-tenders-scraper/0.1 (Apify Actor; public data only)"}
        limits = httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency)
        timeout = httpx.Timeout(30.0)
        sem = asyncio.Semaphore(concurrency)

        saved = 0
        scanned = 0
        # The feed accepts a unix timestamp (API 2.5) as the initial offset; ISO date is the legacy fallback.
        offset: str | None = f"{date_from.timestamp():.3f}"
        offset_candidates = [offset, date_from.isoformat()]
        seen: set[str] = set()
        stop = False

        async with httpx.AsyncClient(headers=headers, limits=limits, timeout=timeout) as client:

            async def handle(entry: dict) -> dict | None:
                async with sem:
                    data = await _fetch_json(client, f"{API_BASE}/tenders/{entry['id']}")
                tender = (data or {}).get("data")
                if not tender:
                    return None
                if _matches(tender, filters):
                    return _normalize(tender, include_docs)
                return None

            first_page = True
            while not stop:
                page = await _fetch_json(client, f"{API_BASE}/tenders", params={"offset": offset, "limit": PAGE_LIMIT})
                if not page and first_page and len(offset_candidates) > 1:
                    # retry the initial request with the legacy ISO-date offset format
                    offset = offset_candidates[1]
                    page = await _fetch_json(client, f"{API_BASE}/tenders", params={"offset": offset, "limit": PAGE_LIMIT})
                first_page = False
                if not page:
                    Actor.log.warning("Feed page could not be fetched; stopping.")
                    break
                entries = page.get("data") or []
                if not entries:
                    Actor.log.info("Reached the end of the feed.")
                    break

                batch: list[dict] = []
                for e in entries:
                    if e["id"] in seen:
                        continue
                    seen.add(e["id"])
                    modified = datetime.fromisoformat(e["dateModified"])
                    if date_to and modified > date_to:
                        stop = True
                        break
                    batch.append(e)

                scanned += len(batch)
                results = await asyncio.gather(*(handle(e) for e in batch))
                matched = [r for r in results if r]
                if matched:
                    room = max_items - saved
                    matched = matched[:room]
                    await Actor.push_data(matched)
                    saved += len(matched)

                Actor.log.info(f"scanned={scanned} saved={saved} last_modified={entries[-1]['dateModified']}")

                if saved >= max_items:
                    Actor.log.info("maxItems reached.")
                    break
                if scanned >= max_scanned:
                    Actor.log.info("maxScanned reached.")
                    break

                next_page = page.get("next_page") or {}
                new_offset = next_page.get("offset")
                if not new_offset or new_offset == offset:
                    break
                offset = new_offset

        await Actor.set_value("SUMMARY", {"scanned": scanned, "saved": saved, "dateFrom": date_from.isoformat(), "dateTo": date_to.isoformat() if date_to else None})
        Actor.log.info(f"Done. Scanned {scanned} tenders, saved {saved}.")
