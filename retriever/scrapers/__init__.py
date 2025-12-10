"""
Scrapers package - imports all available scrapers.

Add new scrapers here as they are implemented.
"""

from .base import BaseScraper
from .WFA import WFAScraper
from .WFA_causeway import WFACausewayScraper

# Add new scrapers to this list
ALL_SCRAPERS = {
    "WFAScraper": WFAScraper,
    "WFACausewayScraper": WFACausewayScraper,
}

__all__ = [
    'BaseScraper',
    'WFAScraper',
    'WFACausewayScraper',
    'ALL_SCRAPERS',
]
