"""
Scrapers package - imports all available scrapers.

Add new scrapers here as they are implemented.
"""

from .base import BaseScraper
from .WFA import WFAScraper
from .WFA_causeway import WFACausewayScraper
from .WBA import WBAScraper
from .WBA_extranet import WBAExtranetScraper
from .IETF_blog import IETFBlogScraper
from .IETF_datatracker import IETFDatatrackerScraper
from .IEEE802 import IEEE802Scraper
from .IEEE_80211_tg import IEEE80211TGScraper
from .MEF import MEFScraper
from .NIST import NISTScraper
from .ONF import ONFScraper
from .DMTF import DMTFScraper

# Add new scrapers to this list
ALL_SCRAPERS = {
    "WFAScraper": WFAScraper,
    "WFACausewayScraper": WFACausewayScraper,
    "WBAScraper": WBAScraper,
    "WBAExtranetScraper": WBAExtranetScraper,
    "IETFBlogScraper": IETFBlogScraper,
    "IETFDatatrackerScraper": IETFDatatrackerScraper,
    "IEEE802Scraper": IEEE802Scraper,
    "IEEE80211TGScraper": IEEE80211TGScraper,
    "MEFScraper": MEFScraper,
    "NISTScraper": NISTScraper,
    "ONFScraper": ONFScraper,
    "DMTFScraper": DMTFScraper,
}

__all__ = [
    'BaseScraper',
    'WFAScraper',
    'WFACausewayScraper',
    'WBAScraper',
    'WBAExtranetScraper',
    'IETFBlogScraper',
    'IETFDatatrackerScraper',
    'IEEE802Scraper',
    'IEEE80211TGScraper',
    'MEF Scraper',
    'NISTScraper',
    'ONFScraper',
    'DMTFScraper',
    'ALL_SCRAPERS',
]
