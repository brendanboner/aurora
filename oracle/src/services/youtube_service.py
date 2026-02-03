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
                    metadata = VideoMetadata(
                        video_id=video_id,
                        url=f"https://www.youtube.com/watch?v={video_id}",
                        title=title,
                        description="",  # oEmbed doesn't provide description
                        channel_name=channel_name,
                        channel_id=channel_id,
                        duration_seconds=0,  # oEmbed doesn't provide duration
                        thumbnail_url=thumbnail_url,
                        publish_date="",  # oEmbed doesn't provide publish date
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
            # Instantiate the API
            ytt_api = YouTubeTranscriptApi()
            
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
