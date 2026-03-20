"""
Scrapers package - imports all available scrapers.

Add new scrapers here as they are implemented.
"""

from .base import BaseScraper
from .WFA import WFAScraper
from .WFA_causeway import WFACausewayScraper
from .WBA import WBAScraper
from .IETF_blog import IETFBlogScraper
from .IETF_datatracker import IETFDatatrackerScraper

# Add new scrapers to this list
ALL_SCRAPERS = {
    "WFAScraper": WFAScraper,
    "WFACausewayScraper": WFACausewayScraper,
    "WBAScraper": WBAScraper,
    "IETFBlogScraper": IETFBlogScraper,
    "IETFDatatrackerScraper": IETFDatatrackerScraper,
}

__all__ = [
    'BaseScraper',
    'WFAScraper',
    'WFACausewayScraper',
    'WBAScraper',
    'IETFBlogScraper',
    'IETFDatatrackerScraper',
    'ALL_SCRAPERS',
]
