"""YouTube video processing service for Oracle."""

import re
import logging
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass
import aiohttp
import json
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.formatters import TextFormatter
from youtube_transcript_api._errors import (
    TranscriptsDisabled,
    NoTranscriptFound,
    VideoUnavailable,
)
from youtube_transcript_api.proxies import GenericProxyConfig
from src.services.rate_limiter import get_youtube_rate_limiter
from src.settings import settings

logger = logging.getLogger(__name__)


@dataclass
class VideoMetadata:
    """YouTube video metadata."""
    video_id: str
    url: str
    title: str
    description: str
    channel_name: str
    channel_id: str
    duration_seconds: int
    thumbnail_url: str
    publish_date: str
    view_count: Optional[int] = None
    has_transcript: bool = False
    transcript_language: Optional[str] = None


@dataclass
class VideoSegment:
    """A segment of a video (for long videos with agendas)."""
    title: str
    timestamp_start: int  # seconds
    timestamp_end: Optional[int]  # seconds, None for last segment
    transcript: str
    segment_number: int
    total_segments: int


@dataclass
class VideoTranscript:
    """Complete video transcript with timestamps."""
    text: str
    formatted_with_timestamps: str
    language: str
    entries: List[Dict[str, Any]]  # Original transcript entries


class YouTubeService:
    """Service for extracting and processing YouTube video content."""
    
    # Regex patterns for agenda detection
    TIMESTAMP_PATTERNS = [
        r'(\d{1,2}):(\d{2})\s*[-–]\s*(.+)',  # 5:30 - Topic
        r'(\d{1,2}):(\d{2})\s+(.+)',  # 5:30 Topic
        r'\[(\d{1,2}):(\d{2})\]\s*(.+)',  # [5:30] Topic
        r'(\d{1,2}):(\d{2}):(\d{2})\s*[-–]\s*(.+)',  # 1:05:30 - Topic
    ]
    
    # Event name patterns for extraction from video titles
    EVENT_PATTERNS = [
        # "EventName YYYY" - e.g., "Cisco AI Summit 2026"
        r'([A-Z][A-Za-z0-9\s&-]+?)\s+(20\d{2})(?:\s|$|\||-)' ,
        # "EventName - Month YYYY" - e.g., "Tech Conference - January 2025"
        r'([A-Z][A-Za-z0-9\s&-]+?)\s+-\s+([A-Z][a-z]+)\s+(20\d{2})',
        # "Location YYYY: EventName" - e.g., "Dubai 2025: Wi-Fi Summit"
        r'([A-Z][A-Za-z\s]+)\s+(20\d{2}):\s*([A-Z][A-Za-z0-9\s&-]+)',
        # "EventName (YYYY)" - e.g., "AI Conference (2026)"
        r'([A-Z][A-Za-z0-9\s&-]+?)\s*\((20\d{2})\)',
    ]
    
    # Common event type keywords
    EVENT_TYPE_KEYWORDS = {
        'summit': 'summit',
        'conference': 'conference',
        'congress': 'conference',
        'symposium': 'conference',
        'expo': 'conference',
        'forum': 'conference',
        'meeting': 'meeting',
        'webinar': 'webinar',
        'workshop': 'workshop',
        'seminar': 'seminar',
        'keynote': 'conference',
        'presentation': 'conference',
        'live': 'conference',
    }
    
    def __init__(self):
        """Initialize YouTube service."""
        self.oembed_url = "https://www.youtube.com/oembed"
        # Headers to bypass GDPR consent requirements
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept': 'application/json',
            'Cookie': 'CONSENT=YES+cb.20260203-00-p0.en+FX+111',  # Bypass GDPR consent
        }
    
    @staticmethod
    def extract_video_id(url: str) -> Optional[str]:
        """
        Extract video ID from various YouTube URL formats.
        
        Supports:
        - https://www.youtube.com/watch?v=VIDEO_ID
        - https://youtu.be/VIDEO_ID
        - https://www.youtube.com/embed/VIDEO_ID
        - https://www.youtube.com/v/VIDEO_ID
        
        Args:
            url: YouTube URL
            
        Returns:
            Video ID or None if invalid
        """
        patterns = [
            r'(?:youtube\.com/watch\?v=|youtu\.be/)([a-zA-Z0-9_-]{11})',
            r'youtube\.com/embed/([a-zA-Z0-9_-]{11})',
            r'youtube\.com/v/([a-zA-Z0-9_-]{11})',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        
        return None
    
    @staticmethod
    def extract_playlist_id(url: str) -> Optional[str]:
        """
        Extract playlist ID from YouTube URL.
        
        Supports:
        - https://www.youtube.com/playlist?list=PLAYLIST_ID
        - https://www.youtube.com/watch?v=VIDEO_ID&list=PLAYLIST_ID
        
        Args:
            url: YouTube URL
            
        Returns:
            Playlist ID or None if not a playlist URL
        """
        pattern = r'[?&]list=([a-zA-Z0-9_-]+)'
        match = re.search(pattern, url)
        if match:
            playlist_id = match.group(1)
            # Filter out special playlist IDs that aren't real playlists
            if not playlist_id.startswith(('WL', 'LL', 'RD')):
                return playlist_id
        return None
    
    async def get_playlist_videos(self, playlist_id: str, max_videos: int = 50) -> List[str]:
        """
        Get all video IDs from a YouTube playlist.
        
        Args:
            playlist_id: YouTube playlist ID
            max_videos: Maximum number of videos to retrieve (default: 50)
            
        Returns:
            List of video IDs
            
        Raises:
            ValueError: If playlist cannot be accessed or is invalid
        """
        try:
            # Use yt-dlp approach: scrape playlist page
            playlist_url = f"https://www.youtube.com/playlist?list={playlist_id}"
            
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    playlist_url,
                    headers=self.headers,
                    timeout=aiohttp.ClientTimeout(total=15)
                ) as response:
                    if response.status != 200:
                        raise ValueError(f"Could not access playlist: HTTP {response.status}")
                    
                    html = await response.text()
                    
                    # Extract video IDs from ytInitialData
                    video_ids = []
                    
                    # Look for ytInitialData in the page
                    initial_data_match = re.search(
                        r'var ytInitialData = ({.+?});',
                        html,
                        re.DOTALL
                    )
                    
                    if initial_data_match:
                        try:
                            initial_data = json.loads(initial_data_match.group(1))
                            
                            # Navigate through the JSON structure to find video IDs
                            contents = initial_data.get('contents', {})
                            tab_renderer = contents.get('twoColumnBrowseResultsRenderer', {}).get('tabs', [])
                            
                            for tab in tab_renderer:
                                tab_content = tab.get('tabRenderer', {}).get('content', {})
                                section_contents = tab_content.get('sectionListRenderer', {}).get('contents', [])
                                
                                for section in section_contents:
                                    item_section = section.get('itemSectionRenderer', {}).get('contents', [])
                                    
                                    for item in item_section:
                                        playlist_renderer = item.get('playlistVideoListRenderer', {})
                                        videos = playlist_renderer.get('contents', [])
                                        
                                        for video in videos:
                                            video_renderer = video.get('playlistVideoRenderer', {})
                                            video_id = video_renderer.get('videoId')
                                            
                                            if video_id and video_id not in video_ids:
                                                video_ids.append(video_id)
                                                
                                                if len(video_ids) >= max_videos:
                                                    break
                                        
                                        if len(video_ids) >= max_videos:
                                            break
                            
                        except (json.JSONDecodeError, KeyError, AttributeError) as e:
                            logger.warning(f"Could not parse playlist data: {e}")
                    
                    # Fallback: regex search for video IDs
                    if not video_ids:
                        video_id_pattern = r'"videoId":"([a-zA-Z0-9_-]{11})"'
                        matches = re.findall(video_id_pattern, html)
                        video_ids = list(dict.fromkeys(matches))[:max_videos]  # Remove duplicates, limit
                    
                    if not video_ids:
                        raise ValueError("No videos found in playlist or playlist is empty")
                    
                    logger.info(f"Found {len(video_ids)} videos in playlist {playlist_id}")
                    return video_ids
                    
        except aiohttp.ClientError as e:
            logger.error(f"Network error accessing playlist: {e}")
            raise ValueError(f"Could not access playlist: {str(e)}")
        except Exception as e:
            logger.error(f"Error getting playlist videos: {e}", exc_info=True)
            raise ValueError(f"Failed to get playlist videos: {str(e)}")
    
    def extract_event_from_title(self, title: str, publish_date: str = None) -> Optional[Dict[str, Any]]:
        """
        Extract event information from video title.
        
        Args:
            title: Video title
            publish_date: Video publish date (ISO format) for validation
            
        Returns:
            Dict with event_name, event_year, event_type, confidence or None
        """
        if not title:
            return None
        
        logger.debug(f"Attempting to extract event from title: {title}")
        
        # Try each pattern
        for pattern in self.EVENT_PATTERNS:
            match = re.search(pattern, title, re.IGNORECASE)
            if match:
                groups = match.groups()
                event_name = None
                event_year = None
                
                # Parse based on pattern structure
                if len(groups) == 2:  # Pattern 1 or 4: name + year
                    event_name = groups[0].strip()
                    event_year = groups[1]
                    # Include the year in the event name
                    event_name = f"{event_name} {event_year}"
                elif len(groups) == 3 and groups[1].isalpha():  # Pattern 2: name + month + year
                    event_name = f"{groups[0].strip()} - {groups[1]} {groups[2]}"
                    event_year = groups[2]
                elif len(groups) == 3:  # Pattern 3: location + year + name
                    event_name = f"{groups[2].strip()} ({groups[0].strip()})"
                    event_year = groups[1]
                
                if event_name and event_year:
                    # Validate year is reasonable (2020-2030)
                    try:
                        year_int = int(event_year)
                        if year_int < 2020 or year_int > 2030:
                            continue
                    except ValueError:
                        continue
                    
                    # Determine event type from name
                    event_type = "conference"  # default
                    name_lower = event_name.lower()
                    for keyword, etype in self.EVENT_TYPE_KEYWORDS.items():
                        if keyword in name_lower:
                            event_type = etype
                            break
                    
                    # Calculate confidence based on year match with publish date
                    confidence = 0.8  # base confidence
                    if publish_date:
                        try:
                            from dateutil.parser import parse as date_parse
                            pub_date = date_parse(publish_date)
                            if pub_date.year == year_int or pub_date.year == year_int - 1:
                                confidence = 0.95  # High confidence if years match
                        except:
                            pass
                    
                    logger.info(f"Extracted event: {event_name} ({event_year}) - Type: {event_type}, Confidence: {confidence}")
                    
                    return {
                        "event_name": event_name,
                        "event_year": event_year,
                        "event_type": event_type,
                        "confidence": confidence
                    }
        
        # No pattern match found
        logger.debug(f"No event pattern matched for title: {title}")
        return None
    
    def extract_event_date_from_description(self, description: str, title: str = None) -> Optional[Dict[str, Any]]:
        """
        Extract event date from video description (e.g., "Streamed live on Feb 4, 2026").
        
        This captures the actual event date for livestreams/premieres, which is more
        accurate than the video upload date.
        
        Args:
            description: Video description text
            title: Optional video title for additional context
            
        Returns:
            Dict with event_date (ISO format), date_type, and confidence or None
        """
        if not description:
            return None
        
        # Patterns for livestream/premiere dates
        # Examples:
        # - "Streamed live on Feb 4, 2026"
        # - "Premiered Feb 4, 2026" 
        # - "Live on February 4, 2026"
        # - "Streamed live on 4 Feb 2026"
        date_patterns = [
            r'Streamed live on ([A-Za-z]+\s+\d{1,2},?\s+\d{4})',
            r'Premiered on ([A-Za-z]+\s+\d{1,2},?\s+\d{4})',
            r'Live on ([A-Za-z]+\s+\d{1,2},?\s+\d{4})',
            r'Streamed live on (\d{1,2}\s+[A-Za-z]+\s+\d{4})',
            r'Premiered (\d{1,2}\s+[A-Za-z]+\s+\d{4})',
        ]
        
        for pattern in date_patterns:
            match = re.search(pattern, description, re.IGNORECASE)
            if match:
                date_str = match.group(1)
                
                try:
                    from dateutil.parser import parse as date_parse
                    event_date = date_parse(date_str)
                    
                    # Validate year is reasonable (2020-2030)
                    if event_date.year < 2020 or event_date.year > 2030:
                        continue
                    
                    # Determine date type from pattern
                    date_type = "livestream" if "stream" in pattern.lower() else "premiere"
                    
                    logger.info(
                        f"Extracted {date_type} date from description: {event_date.date()} "
                        f"(pattern: {pattern})"
                    )
                    
                    return {
                        "event_date": event_date.isoformat(),
                        "date_type": date_type,
                        "confidence": 0.95  # High confidence for explicit date mentions
                    }
                except Exception as e:
                    logger.debug(f"Failed to parse date '{date_str}': {e}")
                    continue
        
        logger.debug("No event date pattern found in description")
        return None
    
    def _extract_fallback_event(self, title: str, publish_date: str = None) -> Optional[Dict[str, Any]]:
        """
        Fallback event extraction: Check for event keywords without year, use publish_date year.
        
        Args:
            title: Video title
            publish_date: Video publish date for year inference
            
        Returns:
            Dict with event info or None
        """
        logger.debug(f"Trying fallback event extraction with publish_date: {publish_date}")
        if publish_date:
            try:
                from dateutil.parser import parse as date_parse
                pub_date = date_parse(publish_date)
                pub_year = str(pub_date.year)
                
                logger.debug(f"Trying fallback event extraction with publish year: {pub_year}")
                
                # Check if title contains event keywords
                title_lower = title.lower()
                for keyword, etype in self.EVENT_TYPE_KEYWORDS.items():
                    if keyword in title_lower:
                        # Extract event name before first delimiter (|, :, -)
                        event_name = re.split(r'\s*[|:\-]\s*', title)[0].strip()
                        # Add year to event name
                        event_name_with_year = f"{event_name} {pub_year}"
                        
                        logger.info(f"Extracted event from keywords: {event_name_with_year} ({pub_year}) - Type: {etype}, Confidence: 0.7 (inferred from publish date)")
                        
                        return {
                            "event_name": event_name_with_year,
                            "event_year": pub_year,
                            "event_type": etype,
                            "confidence": 0.7  # Lower confidence for inferred events
                        }
                logger.debug(f"No event keywords found in title: {title_lower}")
            except Exception as e:
                logger.warning(f"Error in fallback event extraction: {e}")
        else:
            logger.debug("No publish_date provided for fallback extraction")
        
        logger.debug(f"No event pattern matched for title: {title}")
        return None
    
    async def get_video_metadata(self, video_url: str) -> VideoMetadata:
        """
        Get video metadata using YouTube oEmbed API.
        
        Args:
            video_url: YouTube video URL
            
        Returns:
            VideoMetadata object
            
        Raises:
            ValueError: If video ID cannot be extracted or video unavailable
        """
        video_id = self.extract_video_id(video_url)
        if not video_id:
            raise ValueError(f"Could not extract video ID from URL: {video_url}")
        
        # Use oEmbed API to get basic metadata
        async with aiohttp.ClientSession(headers=self.headers) as session:
            try:
                params = {"url": video_url, "format": "json"}
                async with session.get(self.oembed_url, params=params) as response:
                    if response.status == 401 or response.status == 403:
                        logger.warning(f"oEmbed returned {response.status}, trying direct page scraping")
                        return await self._get_metadata_from_page(video_id, video_url, session)
                    elif response.status == 404:
                        raise ValueError(f"Video not found. It may have been deleted or made private: {video_url}")
                    elif response.status != 200:
                        error_text = await response.text()
                        logger.warning(f"oEmbed failed with status {response.status}, trying fallback: {error_text}")
                        return await self._get_metadata_from_page(video_id, video_url, session)
                    
                    data = await response.json()
                    
                    # Extract metadata
                    title = data.get("title", "Untitled Video")
                    channel_name = data.get("author_name", "Unknown Channel")
                    channel_url = data.get("author_url", "")
                    thumbnail_url = data.get("thumbnail_url", "")
                    
                    # Extract channel ID from author_url
                    channel_id = ""
                    if channel_url:
                        channel_match = re.search(r'/channel/([^/]+)', channel_url)
                        if channel_match:
                            channel_id = channel_match.group(1)
                    
                    # Create metadata object (we'll get transcript info separately)
                    from datetime import datetime
                    metadata = VideoMetadata(
                        video_id=video_id,
                        url=f"https://www.youtube.com/watch?v={video_id}",
                        title=title,
                        description="",  # oEmbed doesn't provide description
                        channel_name=channel_name,
                        channel_id=channel_id,
                        duration_seconds=0,  # oEmbed doesn't provide duration
                        thumbnail_url=thumbnail_url,
                        publish_date=datetime.utcnow().isoformat(),  # Use current date as fallback
                    )
                    
                    logger.info(f"Retrieved metadata for video: {title}")
                    return metadata
                    
            except aiohttp.ClientError as e:
                logger.warning(f"oEmbed API failed, trying direct page scraping: {e}")
                # Fallback: try to scrape metadata from the page directly
                return await self._get_metadata_from_page(video_id, video_url, session)
    
    async def _get_metadata_from_page(
        self, 
        video_id: str, 
        video_url: str,
        session: aiohttp.ClientSession
    ) -> VideoMetadata:
        """
        Fallback method to scrape metadata directly from YouTube page.
        Used when oEmbed API fails (e.g., GDPR restrictions).
        """
        try:
            async with session.get(video_url) as response:
                if response.status != 200:
                    raise ValueError(f"Could not access video page: {video_url}")
                
                html = await response.text()
                
                # Extract title from <title> tag or JSON-LD
                title_match = re.search(r'<title>(.+?)</title>', html)
                title = title_match.group(1) if title_match else "Untitled Video"
                # Remove " - YouTube" suffix
                title = re.sub(r'\s*-\s*YouTube\s*$', '', title)
                
                # Try to extract from ytInitialPlayerResponse JSON
                player_response_match = re.search(
                    r'var ytInitialPlayerResponse = ({.+?});', 
                    html
                )
                
                channel_name = "Unknown Channel"
                thumbnail_url = f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg"
                
                if player_response_match:
                    try:
                        player_data = json.loads(player_response_match.group(1))
                        video_details = player_data.get('videoDetails', {})
                        title = video_details.get('title', title)
                        channel_name = video_details.get('author', channel_name)
                        thumbnail_url = video_details.get('thumbnail', {}).get('thumbnails', [{}])[-1].get('url', thumbnail_url)
                    except:
                        pass
                
                logger.info(f"Retrieved metadata from page scraping: {title}")
                
                return VideoMetadata(
                    video_id=video_id,
                    url=video_url,
                    title=title,
                    description="",
                    channel_name=channel_name,
                    channel_id="",
                    duration_seconds=0,
                    thumbnail_url=thumbnail_url,
                    publish_date="",
                )
        except Exception as e:
            raise ValueError(f"Failed to fetch video metadata from page: {e}")
    
    async def get_video_transcript(
        self, 
        video_id: str,
        languages: List[str] = ['en', 'en-US', 'en-GB']
    ) -> Optional[VideoTranscript]:
        """
        Get video transcript using youtube-transcript-api.
        
        Args:
            video_id: YouTube video ID
            languages: List of language codes to try (in order of preference)
            
        Returns:
            VideoTranscript object or None if transcript not available
        """
        try:
            # Rate limit transcript fetching to avoid overwhelming the API
            rate_limiter = get_youtube_rate_limiter()
            await rate_limiter.acquire_transcript()
            
            # Configure proxy if provided (for bypassing YouTube IP blocks on cloud providers)
            proxy_config = None
            if settings.youtube_proxy_http or settings.youtube_proxy_https:
                proxy_config = GenericProxyConfig(
                    http_url=settings.youtube_proxy_http if settings.youtube_proxy_http else None,
                    https_url=settings.youtube_proxy_https if settings.youtube_proxy_https else None
                )
                logger.info(f"Using YouTube transcript proxy: {settings.youtube_proxy_https or settings.youtube_proxy_http}")
            
            # Instantiate the API with optional proxy
            ytt_api = YouTubeTranscriptApi(proxy_config=proxy_config)
            
            # Try to fetch transcript with language preferences
            fetched_transcript = None
            language_used = None
            
            # Try with language preferences first
            try:
                fetched_transcript = ytt_api.fetch(video_id, languages=languages)
                language_used = fetched_transcript.language_code
                logger.info(f"Found transcript in language: {language_used} ({'generated' if fetched_transcript.is_generated else 'manual'})")
            except Exception as e:
                logger.debug(f"Failed to fetch with specific languages: {e}")
                # Fallback: try without language specification
                try:
                    fetched_transcript = ytt_api.fetch(video_id)
                    language_used = fetched_transcript.language_code
                    logger.info(f"Found transcript in default language: {language_used}")
                except Exception as e2:
                    logger.warning(f"Failed to fetch transcript: {e2}")
                    return None
            
            if not fetched_transcript or not fetched_transcript.snippets:
                logger.warning(f"No transcript found for video {video_id}")
                return None
            
            # Convert to raw data format for processing
            transcript_data = fetched_transcript.to_raw_data()
            
            # Format transcript
            plain_text = []
            formatted_with_timestamps = []
            
            for entry in transcript_data:
                text = entry['text'].strip()
                plain_text.append(text)
                
                # Format timestamp as HH:MM:SS or MM:SS
                seconds = int(entry['start'])
                timestamp = self._format_timestamp(seconds)
                formatted_with_timestamps.append(f"[{timestamp}] {text}")
            
            logger.info(f"Successfully fetched transcript with {len(transcript_data)} entries")
            
            return VideoTranscript(
                text=" ".join(plain_text),
                formatted_with_timestamps="\n".join(formatted_with_timestamps),
                language=language_used or 'en',
                entries=transcript_data
            )
            
        except TranscriptsDisabled:
            logger.warning(f"Transcripts are disabled for video {video_id}")
            return None
        except NoTranscriptFound:
            logger.warning(f"No transcript found for video {video_id}")
            return None
        except VideoUnavailable:
            logger.error(f"Video {video_id} is unavailable")
            return None
        except Exception as e:
            logger.error(f"Error fetching transcript for video {video_id}: {e}")
            return None
    
    @staticmethod
    def _format_timestamp(seconds: int) -> str:
        """Format seconds as HH:MM:SS or MM:SS."""
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        
        if hours > 0:
            return f"{hours}:{minutes:02d}:{secs:02d}"
        else:
            return f"{minutes}:{secs:02d}"
    
    def parse_agenda_from_description(self, description: str) -> List[Tuple[int, str]]:
        """
        Parse agenda/timestamps from video description.
        
        Args:
            description: Video description text
            
        Returns:
            List of (timestamp_seconds, title) tuples, sorted by timestamp
        """
        agenda_items = []
        
        for line in description.split('\n'):
            line = line.strip()
            if not line:
                continue
            
            # Try each timestamp pattern
            for pattern in self.TIMESTAMP_PATTERNS:
                match = re.match(pattern, line)
                if match:
                    groups = match.groups()
                    
                    # Handle different timestamp formats
                    if len(groups) == 3:
                        # MM:SS format
                        hours = 0
                        minutes = int(groups[0])
                        seconds = int(groups[1])
                        title = groups[2].strip()
                    elif len(groups) == 4:
                        # HH:MM:SS format
                        hours = int(groups[0])
                        minutes = int(groups[1])
                        seconds = int(groups[2])
                        title = groups[3].strip()
                    else:
                        continue
                    
                    total_seconds = hours * 3600 + minutes * 60 + seconds
                    agenda_items.append((total_seconds, title))
                    break
        
        # Sort by timestamp
        agenda_items.sort(key=lambda x: x[0])
        
        if agenda_items:
            logger.info(f"Found {len(agenda_items)} agenda items in description")
        
        return agenda_items
    
    async def create_video_segments(
        self,
        video_id: str,
        transcript: VideoTranscript,
        agenda: List[Tuple[int, str]],
        min_segment_duration: int = 120  # 2 minutes minimum
    ) -> List[VideoSegment]:
        """
        Create video segments based on agenda timestamps.
        
        Args:
            video_id: YouTube video ID
            transcript: Full video transcript
            agenda: List of (timestamp_seconds, title) tuples
            min_segment_duration: Minimum duration for a segment (seconds)
            
        Returns:
            List of VideoSegment objects
        """
        if not agenda or len(agenda) < 2:
            # Not enough agenda items to segment
            return []
        
        segments = []
        
        for i, (start_time, title) in enumerate(agenda):
            # Determine end time (next segment start or video end)
            end_time = agenda[i + 1][0] if i + 1 < len(agenda) else None
            
            # Skip very short segments
            if end_time and (end_time - start_time) < min_segment_duration:
                logger.debug(f"Skipping short segment: {title} ({end_time - start_time}s)")
                continue
            
            # Extract transcript for this time range
            segment_transcript = self._extract_transcript_segment(
                transcript.entries,
                start_time,
                end_time
            )
            
            if not segment_transcript:
                logger.warning(f"No transcript found for segment: {title}")
                continue
            
            segment = VideoSegment(
                title=title,
                timestamp_start=start_time,
                timestamp_end=end_time,
                transcript=segment_transcript,
                segment_number=len(segments) + 1,
                total_segments=len([a for j, a in enumerate(agenda) 
                                   if j == len(agenda) - 1 or 
                                   (j + 1 < len(agenda) and agenda[j + 1][0] - a[0] >= min_segment_duration)])
            )
            
            segments.append(segment)
            logger.debug(f"Created segment {segment.segment_number}: {title}")
        
        return segments
    
    async def create_time_based_segments(
        self,
        transcript: VideoTranscript,
        chunk_duration: int = 600  # 10 minutes per chunk
    ) -> List[VideoSegment]:
        """
        Create video segments based on time intervals when no agenda is available.
        
        Args:
            transcript: Full video transcript
            chunk_duration: Duration of each segment in seconds (default 10 minutes)
            
        Returns:
            List of VideoSegment objects
        """
        if not transcript or not transcript.entries:
            return []
        
        # Get total duration
        last_entry = transcript.entries[-1]
        total_duration = int(last_entry['start'] + last_entry.get('duration', 0))
        
        # Don't chunk videos shorter than 2x chunk duration
        if total_duration < chunk_duration * 2:
            return []
        
        segments = []
        num_segments = (total_duration + chunk_duration - 1) // chunk_duration  # Ceiling division
        
        for i in range(num_segments):
            start_time = i * chunk_duration
            end_time = min((i + 1) * chunk_duration, total_duration)
            
            # Extract transcript for this time range
            segment_transcript = self._extract_transcript_segment(
                transcript.entries,
                start_time,
                end_time
            )
            
            if not segment_transcript:
                continue
            
            # Create segment with time-based title
            start_formatted = self._format_timestamp(start_time)
            end_formatted = self._format_timestamp(end_time)
            title = f"Segment {i + 1} ({start_formatted} - {end_formatted})"
            
            segment = VideoSegment(
                title=title,
                timestamp_start=start_time,
                timestamp_end=end_time,
                transcript=segment_transcript,
                segment_number=i + 1,
                total_segments=num_segments
            )
            
            segments.append(segment)
        
        logger.info(f"Created {len(segments)} time-based segments ({chunk_duration}s each)")
        return segments
    
    @staticmethod
    def _extract_transcript_segment(
        entries: List[Dict[str, Any]],
        start_time: int,
        end_time: Optional[int]
    ) -> str:
        """Extract transcript text for a specific time range."""
        segment_text = []
        
        for entry in entries:
            entry_start = entry['start']
            entry_end = entry_start + entry.get('duration', 0)
            
            # Check if this entry falls within our time range
            if entry_start >= start_time:
                if end_time is None or entry_start < end_time:
                    segment_text.append(entry['text'].strip())
                else:
                    break
        
        return " ".join(segment_text)
    
    async def process_video(
        self,
        video_url: str,
        segment_long_videos: bool = True,
        long_video_threshold: int = 1800  # 30 minutes
    ) -> Tuple[VideoMetadata, Optional[VideoTranscript], List[VideoSegment]]:
        """
        Complete video processing: metadata, transcript, and optional segmentation.
        
        Args:
            video_url: YouTube video URL
            segment_long_videos: Whether to segment long videos with agendas
            long_video_threshold: Duration threshold (seconds) for segmentation
            
        Returns:
            Tuple of (metadata, transcript, segments)
            
        Raises:
            ValueError: If video cannot be processed
        """
        # Get metadata
        metadata = await self.get_video_metadata(video_url)
        
        # Get transcript
        transcript = await self.get_video_transcript(metadata.video_id)
        
        if transcript:
            metadata.has_transcript = True
            metadata.transcript_language = transcript.language
            
            # Estimate duration from transcript if not available
            if metadata.duration_seconds == 0 and transcript.entries:
                last_entry = transcript.entries[-1]
                metadata.duration_seconds = int(
                    last_entry['start'] + last_entry.get('duration', 0)
                )
        
        # Check if we should segment
        segments = []
        if (segment_long_videos and 
            transcript and 
            metadata.duration_seconds >= long_video_threshold):
            
            logger.info(f"Video is long ({metadata.duration_seconds}s), creating time-based segments")
            
            # Create time-based segments (10-minute chunks)
            segments = await self.create_time_based_segments(
                transcript,
                chunk_duration=600  # 10 minutes
            )
            
            logger.info(f"Created {len(segments)} segments for long video")
        
        return metadata, transcript, segments
