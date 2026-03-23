"""
Action Logement (al-in.fr) Housing Scraper
Fetches new housing offers from the al-in.fr public API (and optionally from the
authenticated eligible_offers API for company-reserved offers) and sends email alerts via Resend.
"""

import json
import os
from datetime import date
from pathlib import Path

import requests
import resend

# --- Configuration ---
FILTER_DEPARTMENTS = [
    d.strip()
    for d in os.getenv("FILTER_DEPARTMENTS", "75,92,93,94").split(",")
    if d.strip()
]
FILTER_MAX_RENT = int(os.getenv("FILTER_MAX_RENT") or "0")
FILTER_MIN_ROOMS = int(os.getenv("FILTER_MIN_ROOMS") or "0")
FILTER_MAX_ROOMS = int(os.getenv("FILTER_MAX_ROOMS") or "0")
FILTER_MIN_SURFACE = float(os.getenv("FILTER_MIN_SURFACE") or "0")
FILTER_TYPOLOGIES = [
    t.strip()
    for t in os.getenv("FILTER_TYPOLOGIES", "").split(",")
    if t.strip()
]

RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
EMAIL_TO = os.getenv("EMAIL_TO", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", "onboarding@resend.dev")

SEEN_OFFERS_FILE = Path("seen_offers.json")
API_BASE = "https://api.al-in.fr"
SITE_BASE = "https://al-in.fr"

# --- Authenticated API (company-reserved offers) ---
ALIN_EMAIL = os.getenv("ALIN_EMAIL", "")
ALIN_PASSWORD = os.getenv("ALIN_PASSWORD", "")
ALIN_NUR = os.getenv("ALIN_NUR", "")

BEYS_AUTH_URL = "https://api.be-ys.com/als-back/v1/accounts/authenticate"
BEYS_API_KEY = "7d6bfa55-4632-41ed-bddd-597866ebbfb5"
TOKEN_EXCHANGE_URL = f"{API_BASE}/api/token_exchange/als_hermes_salarie"
PER_PAGE = 100

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ALin-Scraper/1.0)",
    "Accept": "application/json",
}

DEPARTMENT_NAMES = {
    "06": "Alpes-Maritimes", "13": "Bouches-du-Rhone", "31": "Haute-Garonne",
    "33": "Gironde", "34": "Herault", "35": "Ille-et-Vilaine",
    "44": "Loire-Atlantique", "59": "Nord", "67": "Bas-Rhin",
    "69": "Rhone", "75": "Paris", "77": "Seine-et-Marne",
    "78": "Yvelines", "91": "Essonne", "92": "Hauts-de-Seine",
    "93": "Seine-Saint-Denis", "94": "Val-de-Marne", "95": "Val-d'Oise",
}


def load_seen_offers() -> set:
    if SEEN_OFFERS_FILE.exists():
        data = json.loads(SEEN_OFFERS_FILE.read_text(encoding="utf-8"))
        return set(data)
    return set()


def save_seen_offers(seen: set):
    SEEN_OFFERS_FILE.write_text(
        json.dumps(sorted(seen, key=str), ensure_ascii=False),
        encoding="utf-8",
    )


def _parse_offer(offer_id: str, attrs: dict, source: str = "public") -> dict:
    raw_rwc = attrs.get("rent_with_charges")
    rent_with_charges_is_set = raw_rwc is not None
    rent_with_charges = raw_rwc if raw_rwc else 0
    rent_amount = attrs.get("rent_amount", 0) or 0
    effective_rent = rent_with_charges if rent_with_charges else rent_amount

    photo_url = ""
    main_pic = attrs.get("main_picture")
    if main_pic and isinstance(main_pic, dict):
        photo_url = main_pic.get("thumb240_absolute", main_pic.get("full_size_absolute", ""))

    availability = attrs.get("availability_date", "") or ""
    if availability and "T" in availability:
        availability = availability.split("T")[0]

    return {
        "id": offer_id,
        "address": attrs.get("address", ""),
        "district": attrs.get("district", ""),
        "postal_code": attrs.get("postal_code", ""),
        "department": attrs.get("department", ""),
        "residence_title": attrs.get("residence_title", ""),
        "rent_amount": rent_amount,
        "rent_with_charges": rent_with_charges,
        "rent_with_charges_is_set": rent_with_charges_is_set,
        "effective_rent": effective_rent,
        "rental_charges": attrs.get("rental_charges", 0) or 0,
        "guarantee_deposit": attrs.get("guarantee_deposit", 0) or 0,
        "surface": attrs.get("surface", 0) or 0,
        "rooms": attrs.get("rooms", 0) or 0,
        "bedrooms": attrs.get("bedrooms") or 0,
        "typology": attrs.get("typology", ""),
        "kind": attrs.get("kind", ""),
        "floor": attrs.get("floor", ""),
        "has_elevator": attrs.get("has_elevator", False),
        "description": attrs.get("description", ""),
        "availability_date": availability,
        "dpe_conso": attrs.get("dpe_conso", ""),
        "applicants": attrs.get("appicated_nb", 0) or 0,
        "photo_url": photo_url,
        "link": f"{SITE_BASE}/#/home-logements",
        "link_map": f"https://www.google.com/maps/search/?api=1&query={attrs.get('address', '')}+{attrs.get('postal_code', '')}+{attrs.get('district', '')}".replace(" ", "+"),
        "source": source,
    }


def _passes_filters(offer: dict) -> bool:
    if not offer["rent_with_charges_is_set"]:
        return False
    if FILTER_MAX_RENT and offer["effective_rent"] > FILTER_MAX_RENT:
        return False
    if FILTER_MIN_ROOMS and offer["rooms"] < FILTER_MIN_ROOMS:
        return False
    if FILTER_MAX_ROOMS and offer["rooms"] > FILTER_MAX_ROOMS:
        return False
    if FILTER_MIN_SURFACE and offer["surface"] < FILTER_MIN_SURFACE:
        return False
    if FILTER_TYPOLOGIES and offer["typology"] not in FILTER_TYPOLOGIES:
        return False
    return True


def fetch_offers() -> list[dict]:
    """Fetch all matching offers from the al-in.fr API."""
    all_offers = []
    page = 1
    today = date.today().isoformat()

    while True:
        param_tuples = []
        for dept in FILTER_DEPARTMENTS:
            param_tuples.append(("department[$in][]", dept))
        param_tuples.extend([
            ("per_page", PER_PAGE),
            ("page", page),
            ("sort[rent_with_charges]", 1),
            ("publication_end_date[$gte]", today),
            ("date_publication_start[$lte]", today),
        ])

        r = requests.get(
            f"{API_BASE}/api/dmo/public_housing_offers",
            params=param_tuples,
            headers=HEADERS,
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()

        results = data.get("data", [])
        meta = data.get("meta", {}).get("pagination", {})
        total_pages = meta.get("total_pages", 1)

        for item in results:
            attrs = item.get("attributes", {})
            offer = _parse_offer(item["id"], attrs)
            if _passes_filters(offer):
                all_offers.append(offer)

        if page >= total_pages or not results:
            break
        page += 1

    return all_offers


def _authenticate() -> str | None:
    """Authenticate via be-ys and exchange token for al-in.fr Bearer JWT.
    Returns the Bearer token or None if credentials are missing or auth fails."""
    if not ALIN_EMAIL or not ALIN_PASSWORD or not ALIN_NUR:
        return None

    try:
        # Step 1: be-ys authentication
        r = requests.post(
            BEYS_AUTH_URL,
            json={"login": ALIN_EMAIL, "password": ALIN_PASSWORD},
            headers={"X-Gexrt-Api-Key": BEYS_API_KEY, "Content-Type": "application/json"},
            timeout=30,
        )
        r.raise_for_status()
        beys_token = r.json().get("access_token")
        if not beys_token:
            print("[WARN] be-ys auth returned no access_token")
            return None

        # Step 2: exchange be-ys token for al-in.fr JWT
        r = requests.post(
            TOKEN_EXCHANGE_URL,
            json={"access_token": beys_token},
            headers={"Content-Type": "application/json"},
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        if not data.get("success"):
            print(f"[WARN] Token exchange failed: {data.get('info', 'unknown error')}")
            return None

        print("[INFO] Authenticated successfully for reserved offers")
        return data["jwt_token"]

    except requests.RequestException as e:
        print(f"[WARN] Authentication failed: {e}")
        return None


def fetch_eligible_offers(token: str) -> list[dict]:
    """Fetch company-reserved offers from the authenticated eligible_offers API."""
    all_offers = []
    page = 1

    while True:
        params = {
            "per_page": PER_PAGE,
            "page": page,
            "sort[$publication_end_date]": 1,
            "eligibility_type": "seeked",
        }
        r = requests.get(
            f"{API_BASE}/api/dmo/housing_requests/{ALIN_NUR}/eligible_offers",
            params=params,
            headers={**HEADERS, "Authorization": f"Bearer {token}"},
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()

        results = data.get("data", [])
        meta = data.get("meta", {}).get("pagination", {})
        total_pages = meta.get("total_pages", 1)

        for item in results:
            attrs = item.get("attributes", {})
            offer = _parse_offer(item["id"], attrs, source="reserved")
            if _passes_filters(offer):
                all_offers.append(offer)

        if page >= total_pages or not results:
            break
        page += 1

    return all_offers


def send_email(new_offers: list[dict]):
    """Send an email alert with the new offers via Resend."""
    if not RESEND_API_KEY or not EMAIL_TO:
        print("[INFO] Email not configured, printing offers instead:")
        for o in new_offers:
            rent_str = f"{o['effective_rent']:.0f}EUR CC" if o["rent_with_charges"] else f"{o['rent_amount']:.0f}EUR HC"
            tag = " [RESERVE]" if o.get("source") == "reserved" else ""
            print(f"  - {o['typology']} {o['surface']}m2 | {rent_str} | "
                  f"{o['postal_code']} {o['district']} | {o['rooms']}p | "
                  f"{o['applicants']} candidat(s){tag}")
        return

    resend.api_key = RESEND_API_KEY

    count = len(new_offers)
    subject = f"\U0001f3e0 {count} nouveau(x) logement(s) Action Logement"

    items_html = ""
    for o in new_offers:
        if o["rent_with_charges"]:
            rent_display = f"{o['effective_rent']:.0f}\u20ac CC"
        else:
            rent_display = f"{o['rent_amount']:.0f}\u20ac (hors charges)"

        elevator_str = " | Ascenseur" if o["has_elevator"] else ""
        floor_str = f"Etage {o['floor']}" if o["floor"] else "RDC"

        photo_block = ""
        if o["photo_url"]:
            photo_block = (
                f'<img src="{o["photo_url"]}" '
                f'style="width:100%;max-height:180px;object-fit:cover;border-radius:6px 6px 0 0;" '
                f'alt="Photo du logement" />'
            )

        reserved_badge = ""
        if o.get("source") == "reserved":
            reserved_badge = (
                ' <span style="background:#2ecc71;color:#fff;font-size:11px;'
                'padding:2px 6px;border-radius:3px;vertical-align:middle;">'
                'R\u00e9serv\u00e9</span>'
            )

        items_html += f"""
        <div style="margin-bottom:20px; border:1px solid #e0e0e0; border-radius:6px; overflow:hidden; background:#fff;">
            {photo_block}
            <div style="padding:12px;">
                <strong style="font-size:16px;">
                    <a href="{o['link']}" style="color:#1a4d8f; text-decoration:none;">
                        {o['typology']} - {o['surface']}m\u00b2 - {o['rooms']} pi\u00e8ce(s)
                    </a>{reserved_badge}
                </strong><br>
                <span style="font-size:20px; font-weight:bold; color:#e63946;">{rent_display}</span><br>
                <span>\U0001f4cd <a href="{o['link_map']}" style="color:#1a4d8f; text-decoration:none;">{o['postal_code']} {o['district']} - {o['address']}</a></span><br>
                <span>\U0001f3e2 {floor_str}{elevator_str}</span><br>
                <span>\U0001f6cf\ufe0f {o['bedrooms']} chambre(s)</span><br>
                <span>\U0001f4c5 Disponible : {o['availability_date'] or 'N/C'}</span><br>
                <span>\u26a1 DPE : {o['dpe_conso'] or 'N/C'}</span><br>
                <span>\U0001f465 {o['applicants']} candidat(s)</span><br>
                <span style="color:#888; font-size:12px;">
                    D\u00e9p\u00f4t de garantie : {o['guarantee_deposit']:.0f}\u20ac | Charges : {o['rental_charges']:.0f}\u20ac
                </span>
            </div>
        </div>
        """

    depts_display = ", ".join(
        DEPARTMENT_NAMES.get(d, d) for d in FILTER_DEPARTMENTS
    ) if FILTER_DEPARTMENTS else "Tous"

    filters_summary = f"D\u00e9partements : {depts_display}"
    if FILTER_MAX_RENT:
        filters_summary += f"<br>Loyer max : {FILTER_MAX_RENT}\u20ac CC"
    if FILTER_MIN_ROOMS or FILTER_MAX_ROOMS:
        rooms_parts = []
        if FILTER_MIN_ROOMS:
            rooms_parts.append(f"min {FILTER_MIN_ROOMS}")
        if FILTER_MAX_ROOMS:
            rooms_parts.append(f"max {FILTER_MAX_ROOMS}")
        filters_summary += f"<br>Pi\u00e8ces : {' / '.join(rooms_parts)}"
    if FILTER_MIN_SURFACE:
        filters_summary += f"<br>Surface min : {FILTER_MIN_SURFACE}m\u00b2"
    if FILTER_TYPOLOGIES:
        filters_summary += f"<br>Typologie : {', '.join(FILTER_TYPOLOGIES)}"

    html_body = f"""
    <html>
    <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; background: #f5f5f5; padding: 20px;">
        <h2 style="color: #1a4d8f;">\U0001f3e0 {count} nouveau(x) logement(s) Action Logement</h2>
        <p style="color: #666; font-size: 13px;">{filters_summary}</p>
        <hr style="border: 1px solid #ddd;">
        {items_html}
        <hr style="border: 1px solid #ddd;">
        <p style="color: #888; font-size: 12px;">
            G\u00e9n\u00e9r\u00e9 automatiquement par Action Logement Scraper
        </p>
    </body>
    </html>
    """

    resend.Emails.send({
        "from": EMAIL_FROM,
        "to": [EMAIL_TO],
        "subject": subject,
        "html": html_body,
    })

    print(f"[OK] Email sent to {EMAIL_TO} with {count} new offer(s)")


def main():
    seen = load_seen_offers()

    depts_display = ", ".join(DEPARTMENT_NAMES.get(d, d) for d in FILTER_DEPARTMENTS)
    print(f"[INFO] Loaded {len(seen)} previously seen offers")
    print(f"[INFO] Departments: {depts_display or 'All'}")
    if FILTER_MAX_RENT:
        print(f"[INFO] Max rent: {FILTER_MAX_RENT}EUR")
    if FILTER_MIN_ROOMS:
        print(f"[INFO] Min rooms: {FILTER_MIN_ROOMS}")
    if FILTER_MAX_ROOMS:
        print(f"[INFO] Max rooms: {FILTER_MAX_ROOMS}")
    if FILTER_MIN_SURFACE:
        print(f"[INFO] Min surface: {FILTER_MIN_SURFACE}m2")
    if FILTER_TYPOLOGIES:
        print(f"[INFO] Typologies: {', '.join(FILTER_TYPOLOGIES)}")

    print("[INFO] Fetching public offers from API...")
    offers = fetch_offers()
    print(f"[INFO] Found {len(offers)} public offers matching filters")

    # Fetch company-reserved offers if credentials are configured
    token = _authenticate()
    if token:
        print("[INFO] Fetching reserved/eligible offers...")
        eligible = fetch_eligible_offers(token)
        print(f"[INFO] Found {len(eligible)} reserved offers matching filters")
        seen_ids = {o["id"] for o in offers}
        added = 0
        for o in eligible:
            if o["id"] not in seen_ids:
                offers.append(o)
                seen_ids.add(o["id"])
                added += 1
        print(f"[INFO] Added {added} new reserved offers (deduplicated)")
    else:
        if ALIN_EMAIL:
            print("[WARN] Authentication failed, skipping reserved offers")
        else:
            print("[INFO] No ALIN credentials configured, skipping reserved offers")

    print(f"[INFO] Total: {len(offers)} offers (public + reserved)")

    new_offers = [o for o in offers if o["id"] not in seen]
    print(f"[INFO] {len(new_offers)} new offer(s) detected")

    if new_offers:
        send_email(new_offers)
        for o in new_offers:
            seen.add(o["id"])

    save_seen_offers(seen)
    print(f"[INFO] Saved {len(seen)} seen offers to cache")


if __name__ == "__main__":
    main()
