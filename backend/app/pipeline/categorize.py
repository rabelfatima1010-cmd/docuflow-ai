"""Expense category: learned vendor default wins, otherwise the model's suggestion,
nudged by keyword rules when the model says "Other"."""

from sqlalchemy.orm import Session

from app.models import Vendor
from app.schemas import CATEGORIES, InvoiceExtraction

KEYWORDS = {
    "Software & SaaS": ["subscription", "saas", "license", "software", "cloud", "hosting", "aws", "github", "slack"],
    "Office Supplies": ["paper", "stationery", "toner", "pens", "office supplies"],
    "Travel": ["flight", "airline", "hotel", "uber", "taxi", "lodging", "airbnb", "train"],
    "Meals & Entertainment": ["restaurant", "cafe", "coffee", "catering", "meal", "dinner", "lunch"],
    "Utilities": ["electricity", "water", "gas bill", "internet", "telecom", "phone"],
    "Rent & Facilities": ["rent", "lease", "cleaning", "maintenance"],
    "Professional Services": ["consulting", "legal", "accounting", "audit", "advisory"],
    "Marketing & Advertising": ["ads", "advertising", "marketing", "campaign", "seo"],
    "Shipping & Logistics": ["shipping", "freight", "courier", "delivery", "dhl", "fedex", "ups"],
    "Hardware & Equipment": ["laptop", "monitor", "hardware", "equipment", "printer"],
}


def keyword_category(data: InvoiceExtraction) -> str | None:
    haystack = " ".join([data.vendor_name, *[li.description for li in data.line_items]]).lower()
    best, hits = None, 0
    for category, words in KEYWORDS.items():
        n = sum(1 for w in words if w in haystack)
        if n > hits:
            best, hits = category, n
    return best


def choose_category(db: Session, vendor_key: str | None, data: InvoiceExtraction) -> str:
    if vendor_key:
        vendor = db.query(Vendor).filter_by(key=vendor_key).one_or_none()
        if vendor and vendor.default_category in CATEGORIES:
            return vendor.default_category
    if data.category != "Other":
        return data.category
    return keyword_category(data) or "Other"


def learn_vendor_category(db: Session, vendor_key: str | None, display_name: str, category: str) -> None:
    if not vendor_key:
        return
    vendor = db.query(Vendor).filter_by(key=vendor_key).one_or_none()
    if vendor is None:
        db.add(Vendor(key=vendor_key, display_name=display_name, default_category=category))
    else:
        vendor.default_category = category
        vendor.display_name = display_name
