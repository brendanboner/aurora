#!/usr/bin/env python3
"""
Aurora Parse CLI - Upload local documents to the knowledge graph

This CLI tool allows users to upload local documents (PDF, Word, text files, etc.)
to the Aurora knowledge graph. It provides:
- Interactive prompts for metadata (organization, event, location, date, source, category)
- LLM-powered metadata enrichment for missing fields
- Intelligent organization name matching
- Content hash checking to avoid re-uploading unchanged files
- Test-run mode to check if files are already uploaded
- Non-interactive mode with command-line flags
"""

import argparse
import hashlib
import json
import os
import sys
import base64
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from urllib.parse import quote
import getpass
from dotenv import load_dotenv

# Load environment variables from .env file in parent directory
env_path = Path(__file__).parent.parent / '.env'
if env_path.exists():
    load_dotenv(env_path)

# Use requests library for HTTP API calls
try:
    import requests
except ImportError:
    print("Error: requests library not found. Install with: uv add requests", file=sys.stderr)
    sys.exit(1)


# Supported file extensions
SUPPORTED_EXTENSIONS = {
    '.pdf', '.doc', '.docx', '.txt', '.md', 
    '.html', '.htm', '.ppt', '.pptx', '.xls', '.xlsx'
}

# Organization aliases for intelligent matching
ORGANIZATION_ALIASES = {
    'wfa': 'Wi-Fi Alliance',
    'wi-fi alliance': 'Wi-Fi Alliance',
    'wifi alliance': 'Wi-Fi Alliance',
    'wba': 'Wireless Broadband Alliance',
    'wireless broadband alliance': 'Wireless Broadband Alliance',
    'ieee': 'IEEE',
    'ietf': 'IETF',
    '3gpp': '3GPP',
    'extreme': 'Extreme Networks',
    'extreme networks': 'Extreme Networks',
    'csa': 'Connectivity Standards Alliance',
    'connectivity standards alliance': 'Connectivity Standards Alliance',
    'dsa': 'Dynamic Spectrum Alliance',
    'dynamic spectrum alliance': 'Dynamic Spectrum Alliance',
    'fcc': 'FCC',
}

# Category options
CATEGORY_OPTIONS = [
    'whitepaper',
    'technical specification',
    'standard',
    'press release',
    'article',
    'blog',
    'presentation',
    'report',
    'manual',
    'guide',
    'podcast',
    'video',
    'other'
]


class DocumentUploader:
    """Handles document upload to backend API with metadata extraction."""
    
    def __init__(
        self,
        backend_url: str = "http://localhost:8000",
        user_id: Optional[str] = None,
        user_email: Optional[str] = None,
        enrich_metadata: bool = True
    ):
        """
        Initialize the document uploader.
        
        Args:
            backend_url: Backend API URL
            user_id: User UUID for tracking uploads
            user_email: Email address for tracking uploads
            enrich_metadata: Use LLM to fill missing metadata fields
        """
        # Validate email format
        if user_email and '@' not in user_email:
            raise ValueError(f"Invalid email address: {user_email}")
        
        self.backend_url = backend_url.rstrip('/')
        self.user_id = user_id or os.getenv('TEST_USER_ID', 'dev-user-123')
        self.user_email = user_email or os.getenv('TEST_USER_EMAIL', 'dev@example.com')
        self.user_role = os.getenv('AURORA_ROLE', 'user')
        self.enrich_metadata = enrich_metadata
        
        # Auth headers for dev/testing (bypasses Cognito)
        self.auth_headers = {
            "X-User-Id": self.user_id,
            "X-User-Email": self.user_email,
            "X-User-Role": self.user_role
        }
        
        # LLM client lazy-loaded on first use
        self.llm_client = None
        self.llm_deployment = os.getenv('AZURE_OPENAI_DEPLOYMENT', 'gpt-4o')
    
    def calculate_content_hash(self, content: bytes) -> str:
        """Calculate SHA256 hash of file content."""
        return hashlib.sha256(content).hexdigest()
    
    def read_file_content(self, file_path: Path) -> bytes:
        """Read file content as bytes."""
        with open(file_path, 'rb') as f:
            return f.read()
    
    def normalize_organization_name(self, org_input: str) -> str:
        """
        Normalize organization name using aliases.
        
        Args:
            org_input: User input for organization name
            
        Returns:
            Normalized organization name
        """
        org_lower = org_input.lower().strip()
        if org_lower in ORGANIZATION_ALIASES:
            return ORGANIZATION_ALIASES[org_lower]
        return org_input.strip()
    
    def get_file_extension(self, file_path: Path) -> str:
        """Get file extension (without dot)."""
        return file_path.suffix.lstrip('.').lower()
    
    def is_supported_file(self, file_path: Path) -> bool:
        """Check if file extension is supported."""
        return file_path.suffix.lower() in SUPPORTED_EXTENSIONS
    
    def collect_files(self, path: Path, recursive: bool = False) -> List[Path]:
        """
        Collect supported files from path.
        
        Args:
            path: File or directory path
            recursive: If True, search directories recursively
            
        Returns:
            List of file paths
        """
        files = []
        
        if path.is_file():
            if self.is_supported_file(path):
                files.append(path)
            else:
                print(f"⚠️  Skipping unsupported file: {path}")
        elif path.is_dir():
            if recursive:
                pattern = '**/*'
            else:
                pattern = '*'
            
            for file_path in path.glob(pattern):
                if file_path.is_file() and self.is_supported_file(file_path):
                    files.append(file_path)
        
        return sorted(files)
    
    def prompt_metadata_interactive(self, initial: Dict[str, Any]) -> Dict[str, Any]:
        """Interactive metadata editing.

        Shows current/default values (from env vars / CLI flags) and allows user to
        confirm or modify each before upload. Pressing ENTER keeps the current value.
        Returns updated metadata dict.
        """
        print("\n" + "=" * 60)
        print("📝 Interactive Metadata Editor (ENTER to keep current value)")
        print("=" * 60)

        def prompt(field_label: str, key: str) -> Optional[str]:
            current = initial.get(key)
            display_current = current if current is not None else "(none)"
            raw = input(f"{field_label} [current: {display_current}]: ").strip()
            if raw == "":
                return current
            return raw

        # Editable fields
        organization_in = prompt("Organization (aliases accepted, e.g. WFA)", 'organization')
        organization = self.normalize_organization_name(organization_in) if organization_in else None
        event = prompt("Event (e.g. Wi-Fi NOW 2024)", 'event') or None
        location = prompt("Location (e.g. London, UK)", 'location') or None
        publish_date = prompt("Publication Date (YYYY-MM-DD)", 'publish_date') or None
        source = prompt("Source (website/email/internal)", 'source') or None

        # Category selection (show list with default)
        current_cat = initial.get('category', 'other')
        print("\nCategory options:")
        for i, cat in enumerate(CATEGORY_OPTIONS, 1):
            marker = "*" if cat == current_cat else " "
            print(f"  {i:2}. {cat}{'  <- current' if marker == '*' else ''}")
        category_input = input(f"Category (number or text) [current: {current_cat}]: ").strip()
        if category_input == "":
            category = current_cat
        elif category_input.isdigit():
            idx = int(category_input) - 1
            category = CATEGORY_OPTIONS[idx] if 0 <= idx < len(CATEGORY_OPTIONS) else current_cat
        else:
            category = category_input

        # Allow user email editing
        print("\nUploader Email (for uploaded_by tracking)")
        raw_email = input(f"Email [current: {self.user_email}]: ").strip()
        if raw_email:
            if '@' not in raw_email:
                print("⚠️  Invalid email entered; keeping previous value.")
            else:
                self.user_email = raw_email

        updated = {
            'organization': organization,
            'event': event,
            'location': location,
            'publish_date': publish_date,
            'source': source,
            'category': category
        }

        # Confirmation loop
        while True:
            print("\n" + "-" * 60)
            print("Proposed Metadata:")
            for k, v in updated.items():
                if v:
                    print(f"  {k}: {v}")
            print(f"  user_email: {self.user_email}")
            confirm = input("Proceed with upload? [Y/n/edit]: ").strip().lower()
            if confirm in ('', 'y', 'yes'):  # proceed
                return updated
            if confirm in ('edit', 'e'):
                # Re-enter metadata recursively with current updated values
                return self.prompt_metadata_interactive(updated)
            if confirm in ('n', 'no'):
                print("Upload aborted by user.")
                sys.exit(1)
            print("Please answer Y, N, or edit.")
    
    def enrich_metadata_with_llm(
        self,
        file_path: Path,
        content: bytes,
        metadata: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Use LLM to extract missing metadata fields from document content.
        
        Args:
            file_path: Path to file
            content: File content as bytes
            metadata: Current metadata dictionary
            
        Returns:
            Enriched metadata dictionary
        """
        # Lazy-load LLM client on first use
        if not self.llm_client:
            try:
                from openai import AzureOpenAI
                api_key = os.getenv('AZURE_OPENAI_API_KEY')
                endpoint = os.getenv('AZURE_OPENAI_ENDPOINT')
                if not api_key or not endpoint:
                    print("  ⚠️  LLM enrichment skipped: AZURE_OPENAI_API_KEY or ENDPOINT not set")
                    self.enrich_metadata = False
                    return metadata
                
                self.llm_client = AzureOpenAI(
                    api_key=api_key,
                    api_version=os.getenv('AZURE_OPENAI_API_VERSION', '2024-02-15-preview'),
                    azure_endpoint=endpoint
                )
            except Exception as e:
                print(f"  ⚠️  LLM enrichment disabled: {e}")
                self.enrich_metadata = False
                return metadata
        
        # Check which fields need enrichment
        needs_enrichment = not all([
            metadata.get('organization'),
            metadata.get('event'),
            metadata.get('category')
        ])
        
        if not needs_enrichment:
            return metadata
        
        # Extract text snippet for LLM analysis (first 4000 chars)
        file_ext = self.get_file_extension(file_path)
        text_snippet = ""
        if file_ext in ['txt', 'md', 'html', 'htm']:
            try:
                text_snippet = content.decode('utf-8', errors='ignore')[:4000]
            except Exception:
                text_snippet = f"[Binary file: {file_path.name}]"
        else:
            text_snippet = f"[Binary file type: {file_ext}, name: {file_path.name}]"
        
        prompt = f"""Analyze this document and extract metadata. Only fill in fields that are explicitly missing or empty.

Document: {file_path.name}
Current metadata:
- Organization: {metadata.get('organization') or '(not set)'}
- Event: {metadata.get('event') or '(not set)'}
- Category: {metadata.get('category') or '(not set)'}
- Location: {metadata.get('location') or '(not set)'}
- Source: {metadata.get('source') or '(not set)'}

Content snippet:
{text_snippet}

Extract ONLY the missing fields from the document. Return valid JSON:
{{
  "organization": "string or null",
  "event": "string or null",
  "category": "whitepaper|technical specification|standard|press release|article|blog|presentation|report|manual|guide|podcast|video|other",
  "location": "string or null",
  "source": "string or null"
}}

Guidelines:
- If current metadata already has a value, return null for that field
- Only extract information explicitly stated in the document
- For category, choose the best fit from the allowed values
- Be conservative - return null if uncertain"""
        
        try:
            response = self.llm_client.chat.completions.create(
                model=self.llm_deployment,
                messages=[
                    {"role": "system", "content": "You are a metadata extraction assistant. Return only valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                max_tokens=500
            )
            
            llm_text = response.choices[0].message.content or "{}"
            if "```json" in llm_text:
                llm_text = llm_text.split("```json")[1].split("```")[0].strip()
            elif "```" in llm_text:
                llm_text = llm_text.split("```")[1].split("```")[0].strip()
            
            enriched = json.loads(llm_text)
            
            # Merge LLM results with existing metadata (only fill missing fields)
            for key in ['organization', 'event', 'category', 'location', 'source']:
                if not metadata.get(key) and enriched.get(key):
                    metadata[key] = enriched[key]
                    print(f"  ✨ LLM enriched {key}: {enriched[key]}")
            
        except Exception as e:
            print(f"  ⚠️  LLM enrichment failed: {e}")
        
        return metadata
    
    def build_message(
        self,
        file_path: Path,
        content: bytes,
        metadata: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Build RabbitMQ message for document.
        
        Args:
            file_path: Path to file
            content: File content as bytes
            metadata: Metadata dictionary
            
        Returns:
            Message dictionary
        """
        content_hash = self.calculate_content_hash(content)
        file_ext = self.get_file_extension(file_path)
        
        # Create file:// URL with user email and percent-encoded filename
        # Format: file:///{email}/{filename}
        user_part = self.user_email.split('@')[0] if '@' in self.user_email else self.user_email
        encoded_filename = quote(file_path.name, safe='')
        file_url = f"file:///{user_part}/{encoded_filename}"
        
        # Extract text content for text-based files; encode binary files
        text_content = ""
        binary_content = None
        
        if file_ext in ['txt', 'md', 'html', 'htm']:
            try:
                text_content = content.decode('utf-8', errors='ignore')
            except Exception:
                text_content = "[Binary content - text extraction not available]"
        else:
            # Binary files (PDF, DOCX, PPTX, etc.) - encode as base64 for caching
            text_content = f"[Binary {file_ext.upper()} file - content cached for processing]"
            binary_content = base64.b64encode(content).decode('ascii')
        
        # Build message following the existing format
        message = {
            # Standard fields
            'title': file_path.stem.replace('_', ' ').replace('-', ' ').title(),
            'url': file_url,
            'category': metadata.get('category', 'other'),
            'content': text_content,
            'publish_date': metadata.get('publish_date'),
            'datasource_id': 'local_upload',
            'scraped_at': datetime.now().timestamp(),
            
            # New field for uploader tracking
            'uploaded_by': self.user_email,
            
            # Binary content for caching (base64-encoded)
            'binary_content': binary_content,
            
            # Nested metadata object
            'metadata': {
                'organization': metadata.get('organization'),
                'event': metadata.get('event'),
                'location': metadata.get('location'),
                'source': metadata.get('source'),
                'original_filename': file_path.name,
                'original_path': str(file_path.absolute()),
                'content_hash': content_hash,
                'file_type': file_ext
            }
        }
        
        return message
    
    def check_duplicate(self, content_hash: str) -> bool:
        """
        Check if document with this content hash already exists.
        
        Note: This relies on the digester's duplicate detection.
        For now, returns False (always upload, digester will handle duplicates)
        
        Args:
            content_hash: SHA256 hash of content
            
        Returns:
            True if duplicate exists, False otherwise
        """
        # The digester will handle duplicate detection using content_hash
        return False
    
    def upload_file(
        self,
        file_path: Path,
        metadata: Dict[str, Any],
        test_run: bool = False
    ) -> Tuple[bool, str]:
        """
        Upload a single file.
        
        Args:
            file_path: Path to file
            metadata: Metadata dictionary
            test_run: If True, only check for duplicates without uploading
            
        Returns:
            Tuple of (success, message)
        """
        try:
            # Read file content
            content = self.read_file_content(file_path)
            content_hash = self.calculate_content_hash(content)
            
            # Check for duplicates in test mode
            if test_run:
                is_duplicate = self.check_duplicate(content_hash)
                if is_duplicate:
                    return True, f"Already uploaded (hash: {content_hash[:8]}...)"
                else:
                    return True, f"Would upload (hash: {content_hash[:8]}...)"
            
            # Enrich metadata with LLM if enabled
            if self.enrich_metadata:
                metadata = self.enrich_metadata_with_llm(file_path, content, metadata)
            
            # Build message
            message = self.build_message(file_path, content, metadata)
            
            # Upload via backend API
            import requests
            headers = {
                "Content-Type": "application/json",
                **self.auth_headers  # Add auth headers for dev/testing
            }
            response = requests.post(
                f"{self.backend_url}/upload",
                json=message,
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 200:
                return True, f"Uploaded (hash: {content_hash[:8]}...)"
            else:
                return False, f"Upload failed: {response.text}"
            
        except Exception as e:
            return False, f"Error: {str(e)}"
    
    def upload_files(
        self,
        files: List[Path],
        metadata: Dict[str, Any],
        test_run: bool = False
    ):
        """
        Upload multiple files with progress reporting.
        
        Args:
            files: List of file paths
            metadata: Metadata dictionary
            test_run: If True, only check for duplicates without uploading
        """
        total = len(files)
        success_count = 0
        fail_count = 0
        
        print(f"\n{'🧪 Test run' if test_run else '📤 Uploading'} {total} file(s)...\n")
        
        for i, file_path in enumerate(files, 1):
            print(f"[{i}/{total}] {file_path.name}... ", end='', flush=True)
            
            success, message = self.upload_file(file_path, metadata, test_run)
            
            if success:
                print(f"✓ {message}")
                success_count += 1
            else:
                print(f"✗ {message}")
                fail_count += 1
        
        # Summary
        print("\n" + "=" * 60)
        if test_run:
            print(f"Test run complete: {success_count} file(s) checked, {fail_count} error(s)")
        else:
            print(f"Upload complete: {success_count} file(s) uploaded, {fail_count} error(s)")
            if success_count > 0:
                print(f"\n💡 Documents are being processed by the digester pipeline")
                print(f"   Monitor progress: make logs-digester")
        print("=" * 60 + "\n")


def main():
    """Main entry point for aurora parse CLI."""
    parser = argparse.ArgumentParser(
        prog="aurora parse",
        description="Upload local documents to the Aurora knowledge graph",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Interactive mode - upload a single file
  aurora parse document.pdf
  
  # Interactive mode - upload directory
  aurora parse ./documents/
  
  # Test run - check if files would be uploaded
  aurora parse --test-run ./documents/
  
  # Non-interactive mode with metadata flags
  aurora parse document.pdf \\
    --organization "Wi-Fi Alliance" \\
    --event "Wi-Fi NOW 2024" \\
    --category whitepaper \\
    --date 2024-03-15
  
  # Recursive directory upload
  aurora parse --recursive ./all-documents/
        """
    )
    
    # Positional arguments
    parser.add_argument(
        'path',
        type=Path,
        help='File or directory to upload'
    )
    
    # Upload options
    parser.add_argument(
        '--recursive', '-r',
        action='store_true',
        help='Search directories recursively'
    )
    
    parser.add_argument(
        '--test-run',
        action='store_true',
        help='Check if files already uploaded without uploading'
    )
    
    parser.add_argument(
        '--interactive', '-i',
        action='store_true',
        help='Prompt for metadata interactively (overrides env vars and flags)'
    )
    
    # Metadata options (can use AURORA_* environment variables)
    parser.add_argument(
        '--organization', '--org',
        default=os.getenv('AURORA_ORG'),
        help='Organization name (default: AURORA_ORG env var, e.g., "Wi-Fi Alliance", "WFA", "IEEE")'
    )
    
    parser.add_argument(
        '--event',
        default=os.getenv('AURORA_EVENT'),
        help='Event name (default: AURORA_EVENT env var, e.g., "Wi-Fi NOW 2024")'
    )
    
    parser.add_argument(
        '--location',
        default=os.getenv('AURORA_LOCATION'),
        help='Location (default: AURORA_LOCATION env var, e.g., "London, UK")'
    )
    
    parser.add_argument(
        '--date',
        default=os.getenv('AURORA_DATE'),
        help='Publication date (default: AURORA_DATE env var, YYYY-MM-DD)'
    )
    
    parser.add_argument(
        '--source',
        default=os.getenv('AURORA_SOURCE'),
        help='Source (default: AURORA_SOURCE env var, e.g., "website", "email", "internal")'
    )
    
    parser.add_argument(
        '--category',
        default=os.getenv('AURORA_CATEGORY', 'other'),
        choices=CATEGORY_OPTIONS,
        help='Document category (default: AURORA_CATEGORY env var or "other")'
    )
    
    # Backend API options
    parser.add_argument(
        '--backend-url',
        default=os.getenv('BACKEND_URL', 'http://localhost:8000'),
        help='Backend API URL (default: http://localhost:8000 or BACKEND_URL env var)'
    )
    
    parser.add_argument(
        '--user',
        default=os.getenv('TEST_USER_EMAIL', 'dev@example.com'),
        help='Email address for tracking uploads (default: TEST_USER_EMAIL env var or dev@example.com)'
    )
    
    parser.add_argument(
        '--user-id',
        default=os.getenv('TEST_USER_ID', 'dev-user-123'),
        help='User UUID for tracking uploads (default: TEST_USER_ID env var or dev-user-123)'
    )
    
    parser.add_argument(
        '--no-enrich',
        action='store_true',
        help='Disable LLM metadata enrichment (use only provided/env var metadata)'
    )
    
    args = parser.parse_args()
    
    # Validate path (attempt resolution relative to ORIGINAL_CWD if missing)
    if not args.path.exists():
        original_cwd = os.environ.get('ORIGINAL_CWD')
        if original_cwd:
            alt_path = Path(original_cwd) / str(args.path)
            if alt_path.exists():
                args.path = alt_path
        if not args.path.exists():
            print(f"❌ Error: Path does not exist: {args.path}", file=sys.stderr)
            sys.exit(1)
    
    # Initialize uploader
    uploader = DocumentUploader(
        backend_url=args.backend_url,
        user_id=args.user_id,
        user_email=args.user,
        enrich_metadata=not args.no_enrich
    )
    
    try:
        # Collect files
        print(f"\n🔍 Scanning {'recursively' if args.recursive else 'directory'}...")
        files = uploader.collect_files(args.path, recursive=args.recursive)
        
        if not files:
            print(f"❌ No supported files found in {args.path}")
            print(f"   Supported extensions: {', '.join(sorted(SUPPORTED_EXTENSIONS))}")
            sys.exit(0)
        
        print(f"✓ Found {len(files)} file(s)")
        
        # Build initial metadata from args/env vars
        initial_metadata = {
            'organization': uploader.normalize_organization_name(args.organization) if args.organization else None,
            'event': args.event,
            'location': args.location,
            'publish_date': args.date,
            'source': args.source,
            'category': args.category
        }

        # Interactive editing if requested
        if args.interactive:
            metadata = uploader.prompt_metadata_interactive(initial_metadata)
        else:
            metadata = initial_metadata
        
        # Display metadata summary
        print("\n" + "=" * 60)
        print("📋 Metadata Summary")
        print("=" * 60)
        for key, value in metadata.items():
            if value:
                print(f"  {key.capitalize().replace('_', ' ')}: {value}")
        print(f"  User: {uploader.user_email} ({uploader.user_id})")
        print("=" * 60)
        
        # Upload files
        uploader.upload_files(files, metadata, test_run=args.test_run)
        
    except KeyboardInterrupt:
        print("\n\n⚠️  Upload cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
