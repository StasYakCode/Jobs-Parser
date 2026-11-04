"""Чистые функции разбора HTML/JSON-LD. Не обращаются ни к сети, ни к БД."""
import json
import re
from datetime import date
from urllib.parse import unquote

from bs4 import BeautifulSoup, Comment


def _text(el):
    return el.get_text(" ", strip=True) if el else ""


def _int(s):
    digits = re.sub(r"[^\d]", "", s or "")
    return int(digits) if digits else None


def _date(s):
    try:
        return date.fromisoformat((s or "")[:10])
    except ValueError:
        return None


def company_slug(url):
    m = re.search(r"linkedin\.com/(?:company|school)/([^/?#]+)", url or "")
    return unquote(m.group(1)) if m else ""


def job_id_from_url(url):
    m = re.search(r"/jobs/view/(?:[^/?#]*-)?(\d+)", url or "")
    return m.group(1) if m else ""


def parse_search_page(html):
    """Список карточек вакансий из ответа jobs-guest/seeMoreJobPostings/search."""
    soup = BeautifulSoup(html, "html.parser")
    cards, seen = [], set()
    for li in soup.find_all("li"):
        card = li.select_one("div.base-card, div.job-search-card")
        if not card:
            continue
        link = card.select_one("a.base-card__full-link")
        href = link.get("href", "") if link else ""
        m = re.search(r"(\d+)$", card.get("data-entity-urn", ""))
        job_id = m.group(1) if m else job_id_from_url(href)
        if not job_id or job_id in seen:
            continue
        seen.add(job_id)

        comp_link = card.select_one("h4.base-search-card__subtitle a")
        comp_url = (comp_link.get("href", "") if comp_link else "").split("?")[0]
        time_el = card.select_one("time[datetime]")
        cards.append({
            "job_id": job_id,
            "title": _text(card.select_one(".base-search-card__title")),
            "company_name": _text(card.select_one(".base-search-card__subtitle")),
            "company_url": comp_url,
            "company_slug": company_slug(comp_url),
            "location": _text(card.select_one(".job-search-card__location")),
            "url": href.split("?")[0],
            "listed_at": _date(time_el.get("datetime")) if time_el else None,
        })
    return cards


def _jsonld(soup, wanted):
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except (ValueError, TypeError):
            continue
        items = data.get("@graph", [data]) if isinstance(data, dict) else data
        for item in items if isinstance(items, list) else [items]:
            if isinstance(item, dict) and item.get("@type") == wanted:
                return item
    return {}


def _apply_url(soup):
    tag = soup.find(id="applyUrl")
    if tag:
        comment = tag.find(string=lambda s: isinstance(s, Comment))
        raw = (comment or tag.get_text()).strip().strip('"')
        m = re.search(r"https?://[^\s\"'<>]+", raw)
        if m:
            return m.group(0).replace("&amp;", "&")
    btn = soup.select_one("a.apply-button, a.top-card-layout__cta")
    return btn.get("href", "") if btn else ""


def parse_job_detail(html):
    soup = BeautifulSoup(html, "html.parser")
    data = {}

    title = _text(soup.select_one("h2.top-card-layout__title, h1.top-card-layout__title"))
    if title:
        data["title"] = title
    org = soup.select_one("a.topcard__org-name-link")
    if org:
        data["company_name"] = _text(org)
        data["company_url"] = org.get("href", "").split("?")[0]
        data["company_slug"] = company_slug(data["company_url"])
    loc = soup.select_one("span.topcard__flavor.topcard__flavor--bullet")
    if loc:
        data["location"] = _text(loc)
    data["posted_text"] = _text(soup.select_one(".posted-time-ago__text"))
    applicants = _text(soup.select_one(".num-applicants__caption, figcaption.num-applicants__caption"))
    data["applicants_text"] = applicants
    data["applicants_count"] = _int(applicants)
    data["salary"] = _text(soup.select_one(".compensation__salary, .salary.compensation__salary"))
    data["apply_url"] = _apply_url(soup)

    desc = soup.select_one("div.show-more-less-html__markup, div.description__text")
    if desc:
        data["description_html"] = desc.decode_contents().strip()
        data["description_text"] = desc.get_text("\n", strip=True)

    for item in soup.select("li.description__job-criteria-item"):
        head = _text(item.select_one(".description__job-criteria-subheader")).lower()
        value = _text(item.select_one(".description__job-criteria-text"))
        key = {"seniority level": "seniority_level", "employment type": "employment_type",
               "job function": "job_function", "industries": "industries"}.get(head)
        if key:
            data[key] = value

    ld = _jsonld(soup, "JobPosting")
    if ld:
        data["valid_through"] = _date(ld.get("validThrough"))
        if not data.get("listed_at") and ld.get("datePosted"):
            data["listed_at"] = _date(ld["datePosted"])
        data["raw"] = {"json_ld": ld}
    return data


def parse_company(html):
    soup = BeautifulSoup(html, "html.parser")
    data = {}
    ld = _jsonld(soup, "Organization")
    if ld:
        data["name"] = ld.get("name", "")
        data["description"] = ld.get("description", "")
        data["website"] = ld.get("sameAs") or ld.get("url") or ""
        logo = ld.get("logo")
        data["logo_url"] = logo.get("contentUrl", "") if isinstance(logo, dict) else (logo or "")
        addr = ld.get("address")
        if isinstance(addr, dict):
            data["address"] = ", ".join(str(addr[k]) for k in
                                        ("streetAddress", "addressLocality", "addressRegion", "postalCode", "addressCountry")
                                        if addr.get(k))
        emp = ld.get("numberOfEmployees")
        if isinstance(emp, dict):
            data["employees_count"] = _int(str(emp.get("value", "")))
        data["raw"] = {"json_ld": ld}

    def about(test_id):
        return _text(soup.select_one(f'[data-test-id="about-us__{test_id}"] dd'))

    for key, test_id in (("website", "website"), ("industry", "industry"), ("company_size", "size"),
                         ("headquarters", "headquarters"), ("founded", "foundedOn"),
                         ("specialties", "specialties")):
        value = about(test_id)
        if value:
            data[key] = value
    if not data.get("name"):
        data["name"] = _text(soup.select_one("h1.top-card-layout__title, h1"))
    followers = re.search(r"([\d,\.]+)\s+followers", soup.get_text(" ", strip=True))
    if followers:
        data["followers"] = _int(followers.group(1))
    return {k: v for k, v in data.items() if v not in (None, "")}
