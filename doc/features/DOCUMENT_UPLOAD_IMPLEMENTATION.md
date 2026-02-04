# Document Upload Feature - Implementation Plan

## Overview

This document outlines the implementation plan for enabling users to upload documents to add to the Aurora knowledge graph. Currently, content is only scraped from web sources. This feature provides two avenues for document upload:

1. **General Document Upload Page** - A dedicated page for uploading and managing documents
2. **Event-Specific Upload** - Upload documents directly from an event's detail page

### Key Requirements
- **Documents are uploaded from personal devices** - No existing URLs; files must be stored
- **AWS S3 Storage** - All uploaded documents will be stored in S3 for future reference and sharing
- **Aurora-Only Access** - Documents are only accessible to authenticated Aurora application users
- **Content Extraction** - Text content extracted and stored in Neo4j for search/RAG capabilities

---

## Current System Architecture

### Pipeline Flow (Existing)
```
Retriever (Scrapers) → RabbitMQ → Digester → Neo4j Knowledge Graph
```

### Relevant Components
- **Retriever Service** (`/retriever/retriever.py`): Handles scraping and has stub endpoints for document submission
- **Digester Service** (`/digester/digester.py`): Consumes messages from RabbitMQ, extracts metadata via LLM, inserts into Neo4j
- **Backend Service** (`/backend/`): API gateway for frontend, events management
- **Frontend** (`/frontend/`): React application with events pages already implemented
- **Neo4j Models** (`/neo4j-client/`): Includes `Resource`, `Event`, `ResourceRelatesToEvent` relationship

### Existing Message Structure
```python
# Resource message (from retriever/scrapers/base.py)
{
    "message_type": "resource",
    "resource_data": {
        "title": str,
        "url": str,
        "category": str,
        "content": str,
        "publish_date": str  # ISO 8601
    },
    "datasource_id": str,
    "batch_id": str,
    "scraped_at": str
}
```

---

## Implementation Plan

### Phase 1: Backend - Retriever Service Endpoints

#### 1.1 New Message Structure for User Uploads
Extend the existing message format to support user uploads and event associations:

```python
# Extended message structure for user uploads
{
    "message_type": "resource",
    "resource_data": {
        "title": str,
        "url": str,  # S3 path (e.g., "s3://bucket/uploads/{user_uuid}/{filename}")
        "category": str,
        "content": str,  # Extracted text content
        "publish_date": str
    },
    "datasource_id": "user_upload",  # Special datasource for user uploads
    "batch_id": str,
    "scraped_at": str,
    "uploaded_by": str,  # User UUID who uploaded
    "related_events": [str],  # List of event url_hash values (optional)
    "s3_bucket": str,  # S3 bucket name for download URL generation
    "s3_key": str,  # S3 object key for download URL generation
    "content_hash": str  # SHA256 hash stored on Resource node
}
```

**Note**: The `url` field (S3 path) is used to generate the `url_hash` which serves as the Resource node's unique ID. The `s3_bucket`, `s3_key`, and `content_hash` fields are stored on the Resource node. Duplicate detection is performed in the retriever *before* this message is created - if a duplicate is detected, the upload is rejected and no message is sent.

#### 1.2 Implement Retriever Upload Endpoint
**File**: `/retriever/retriever.py`

Update the existing stub endpoints to handle file uploads:

```python
@app.post("/submit/documents", response_model=DocumentBatchSubmitResponse)
@require_role(["user", "admin", "superadmin"])
async def submit_documents(
    files: List[UploadFile] = File(...),
    titles: List[str] = Form(...),  # JSON array of titles
    categories: List[str] = Form(...),  # JSON array of categories
    related_events: Optional[str] = Form(None),  # JSON array of event url_hashes
    user: dict = Depends(get_user_context)
):
    """
    Submit multiple documents for processing.
    
    - Extracts content from uploaded files (PDF, DOCX, PPTX, XLSX, TXT)
    - Creates resource messages
    - Publishes to RabbitMQ for digester processing
    - Links to specified events via ResourceRelatesToEvent relationship
    """
```

**Key implementation details**:
- Use existing `DocumentParser` from digester for content extraction
- Upload original file to S3 with path: `uploads/{user_uuid}/{original_filename}`
- Store S3 URL as the `url` field in resource_data
- Create batch for tracking
- Publish messages to RabbitMQ
- Return batch ID and individual document IDs for tracking

#### 1.3 New Pydantic Models (API Request/Response Only)
These are FastAPI request/response models for the upload endpoint, **not** Neo4j graph models:

```python
class DocumentBatchSubmitResponse(BaseModel):
    """Response model for batch document submission"""
    status: str
    batch_id: str
    documents: List[DocumentSubmitResult]
    
class DocumentSubmitResult(BaseModel):
    """Result for each uploaded document"""
    original_filename: str
    resource_id: str
    s3_key: str
    status: str  # "queued", "error"
    error: Optional[str] = None
```

**Note**: No new Neo4j graph models are needed. The existing `ResourceUploadedByPerson` relationship (already in `models.py`) handles linking uploaded documents to the user who uploaded them.

---

### Phase 2: AWS S3 Storage Layer

#### 2.1 S3 Bucket Configuration
**Bucket Name**: `aurora-document-uploads-{environment}` (e.g., `aurora-document-uploads-prod`)

**Bucket Structure**:
```
aurora-document-uploads-prod/
├── uploads/
│   └── {user_uuid}/
│       └── {original_filename}
```

**Bucket Policy** (Private - No Public Access):
```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "DenyPublicAccess",
            "Effect": "Deny",
            "Principal": "*",
            "Action": "s3:GetObject",
            "Resource": "arn:aws:s3:::aurora-document-uploads-*/*",
            "Condition": {
                "Bool": {
                    "aws:SecureTransport": "false"
                }
            }
        }
    ]
}
```

#### 2.2 IAM Policy for Retriever Service
```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "s3:PutObject",
                "s3:GetObject",
                "s3:DeleteObject"
            ],
            "Resource": "arn:aws:s3:::aurora-document-uploads-*/*"
        },
        {
            "Effect": "Allow",
            "Action": [
                "s3:ListBucket"
            ],
            "Resource": "arn:aws:s3:::aurora-document-uploads-*"
        }
    ]
}
```

#### 2.3 S3 Client Service
**File**: `/retriever/utils/s3_client.py` (new)

```python
import boto3
from botocore.exceptions import ClientError
import uuid
from datetime import datetime, timedelta
from settings import settings

class S3DocumentStorage:
    """Handle document storage in AWS S3."""
    
    def __init__(self):
        self.s3_client = boto3.client(
            's3',
            region_name=settings.aws_region,
            # Credentials from environment or IAM role
        )
        self.bucket_name = settings.s3_document_bucket
    
    async def upload_document(
        self, 
        file_content: bytes, 
        original_filename: str, 
        user_uuid: str,
        content_type: str
    ) -> dict:
        """
        Upload a document to S3.
        
        Returns:
            dict with s3_key, s3_bucket, file_size_bytes
        """
        s3_key = f"uploads/{user_uuid}/{original_filename}"
        
        self.s3_client.put_object(
            Bucket=self.bucket_name,
            Key=s3_key,
            Body=file_content,
            ContentType=content_type,
            Metadata={
                'uploaded-by': user_uuid,
                'original-filename': original_filename,
                'upload-timestamp': datetime.utcnow().isoformat()
            }
        )
        
        return {
            's3_bucket': self.bucket_name,
            's3_key': s3_key,
            'file_size_bytes': len(file_content)
        }
    
    def generate_presigned_url(self, s3_key: str, expiration: int = 3600) -> str:
        """
        Generate a presigned URL for secure document download.
        
        Args:
            s3_key: The S3 object key
            expiration: URL expiration time in seconds (default 1 hour)
            
        Returns:
            Presigned URL string
        """
        return self.s3_client.generate_presigned_url(
            'get_object',
            Params={
                'Bucket': self.bucket_name,
                'Key': s3_key
            },
            ExpiresIn=expiration
        )
    
    async def delete_document(self, s3_key: str) -> bool:
        """Delete a document from S3."""
        try:
            self.s3_client.delete_object(
                Bucket=self.bucket_name,
                Key=s3_key
            )
            return True
        except ClientError:
            return False
```

#### 2.4 Settings Updates
**File**: `/retriever/settings.py`

```python
# AWS S3 Configuration
aws_region: str = os.getenv("AWS_REGION", "us-east-1")
s3_document_bucket: str = os.getenv("S3_DOCUMENT_BUCKET", "aurora-document-uploads")
max_upload_size_mb: int = int(os.getenv("MAX_UPLOAD_SIZE_MB", "50"))
```

#### 2.5 Duplicate Document Detection
S3 does not prevent duplicate uploads - it will simply overwrite if the same key is used. We implement duplicate detection in the retriever before uploading to S3 or sending any messages.

**Two Types of Duplicates to Detect:**
1. **Duplicate content** - Same file uploaded twice (by same or different users)
2. **Duplicate filename** - Same user uploading a file with a name they've already used

**Strategy: Content Hash + Path-Based Deduplication (in Retriever)**

1. **Generate content hash** for duplicate content detection:
   ```python
   import hashlib
   
   def get_content_hash(file_content: bytes) -> str:
       """Generate SHA256 hash of file content."""
       return hashlib.sha256(file_content).hexdigest()
   ```

2. **Use S3 path as URL** for Resource node ID:
   ```python
   s3_key = f"uploads/{user_uuid}/{original_filename}"
   url = f"s3://{bucket_name}/{s3_key}"  # This becomes url_hash after hashing
   ```

3. **Check Neo4j before upload** (in retriever endpoint):
   ```python
   # Query to check for duplicate content OR duplicate path
   query = """
   MATCH (r:Resource)
   WHERE r.content_hash = $content_hash OR r.s3_key = $s3_key
   RETURN r.url_hash as existing_id, 
          r.title as existing_title,
          r.content_hash as existing_hash,
          r.s3_key as existing_key
   """
   ```

4. **Upload flow** (all in retriever):
   ```
   User uploads file
        ↓
   Calculate content hash
   Build s3_key: uploads/{user_uuid}/{original_filename}
        ↓
   Check Neo4j for:
     - Existing resource with same content_hash (duplicate file)
     - Existing resource with same s3_key (duplicate filename for this user)
        ↓
   If duplicate content: Return error "This file has already been uploaded as '{title}'"
   If duplicate filename: Return error "You already have a file named '{filename}'. Please rename and try again."
   If neither: Upload to S3, then send RabbitMQ message
   ```

**S3 Key Structure** (simple path per user):
```
uploads/{user_uuid}/{original_filename}
```

**Benefits**:
- Same file uploaded twice = same hash = rejected as duplicate content
- Same filename from same user = same s3_key = rejected as duplicate name
- Different users can upload files with the same name (different s3_key)
- Content hash stored on Resource node for future duplicate checks

---

### Phase 3: Backend - Digester Service Updates

#### 3.1 Handle Event Associations
**File**: `/digester/digester.py`

Extend `process_message()` to create `ResourceRelatesToEvent` relationships when `related_events` is present:

```python
async def _create_event_associations(self, resource_url_hash: str, related_events: List[str]):
    """
    Create RELATES_TO relationships between uploaded resource and specified events.
    
    Uses high confidence (0.9) for user-specified associations.
    """
    for event_url_hash in related_events:
        relationship = ResourceRelatesToEvent(
            source_id=resource_url_hash,
            target_id=event_url_hash,
            confidence=0.9,  # High confidence for user-specified
            evidence="User uploaded document for this event",
            context_type="material"
        )
        self.graph_repository.create_relationship(relationship)
```

#### 3.2 Track Upload Source
Add `uploaded_by` field handling to link resources to the uploading user via `ResourceUploadedByPerson` relationship (already exists in models).

---

### Phase 4: Backend API - Events & Documents

#### 4.1 New Backend Endpoints
**File**: `/backend/src/routes/events.py` (extend)

```python
@router.get("/{url_hash}/documents")
async def get_event_documents(url_hash: str):
    """Get documents related to an event."""
    
@router.get("/{url_hash}/document-count")
async def get_event_document_count(url_hash: str):
    """Get count of documents related to an event (for card display)."""
```

**File**: `/backend/src/routes/documents.py` (new)

```python
@router.get("/user-uploads")
async def get_user_uploads(x_user_id: str = Header(...)):
    """Get documents uploaded by the current user."""

@router.get("/categories")
async def get_document_categories():
    """Get available document categories."""

@router.get("/{url_hash}/download")
async def get_document_download_url(url_hash: str, x_user_id: str = Header(...)):
    """Get a presigned S3 URL for document download (authenticated users only)."""
```

#### 4.2 Events Service Updates
**File**: `/backend/src/services/events_service.py`

```python
def get_event_document_count(url_hash: str) -> int:
    """Get count of documents related to an event."""
    query = """
    MATCH (e:Event {url_hash: $url_hash})<-[:RELATES_TO]-(r:Resource)
    RETURN count(r) as doc_count
    """

def get_event_documents(url_hash: str) -> List[Dict]:
    """Get documents related to an event with metadata."""
    query = """
    MATCH (e:Event {url_hash: $url_hash})<-[rel:RELATES_TO]-(r:Resource)
    RETURN r.url_hash as url_hash,
           r.title as title,
           r.url as url,
           r.category as category,
           r.doc_type as doc_type,
           rel.confidence as confidence,
           rel.context_type as context_type
    ORDER BY rel.confidence DESC, r.scraped_at DESC
    """
```

#### 4.3 Modify Existing Events Query
Update `get_events()` to include document count:

```python
query = """
MATCH (e:Event)
{where_clause}
OPTIONAL MATCH (p:Person)-[a:ATTENDING]->(e)
OPTIONAL MATCH (r:Resource)-[:RELATES_TO]->(e)
WITH e, 
     count(DISTINCT p) as attendee_count,
     count(DISTINCT CASE WHEN a.is_presenting = true THEN p END) as presenter_count,
     count(DISTINCT r) as document_count
RETURN e.url_hash as url_hash,
       ...
       document_count
"""
```

---

### Phase 5: Frontend - Document Upload Page

#### 5.1 New Page Component
**File**: `/frontend/src/pages/DocumentUpload.jsx` (new)

Features:
- Drag-and-drop file upload zone
- File list with editable titles
- Category dropdown per document
- Event selector (multi-select, searchable)
- Submit button with progress tracking
- View previously uploaded documents

```jsx
// Key state structure
const [files, setFiles] = useState([]);
// Each file: { file: File, title: string, category: string, relatedEvents: [] }
const [availableEvents, setAvailableEvents] = useState([]);
const [availableCategories, setAvailableCategories] = useState([]);
const [uploadProgress, setUploadProgress] = useState(null);
```

#### 5.2 Supported File Types
- PDF (`.pdf`)
- Word (`.docx`)
- PowerPoint (`.pptx`)
- Excel (`.xlsx`)
- Plain text (`.txt`)
- Markdown (`.md`)

#### 5.3 UI Components Needed
- `FileDropZone` - Drag and drop area
- `DocumentList` - List of staged documents with edit controls
- `EventSelector` - Searchable multi-select for events
- `CategorySelector` - Dropdown with predefined categories
- `UploadProgress` - Progress indicator during upload

#### 5.4 CSS Styling
**File**: `/frontend/src/pages/DocumentUpload.css` (new)

---

### Phase 6: Frontend - Events Page Updates

#### 6.1 Events List Card Update
**File**: `/frontend/src/pages/Events.jsx`

Add document count badge to event cards:

```jsx
<div className="event-footer">
  <div className="attendance-info">
    <CheckIcon size={16} />
    <span>{event.attendee_count || 0} attending</span>
  </div>
  {event.document_count > 0 && (
    <div className="document-info">
      <FileTextIcon size={16} />
      <span>{event.document_count} Docs</span>
    </div>
  )}
</div>
```

#### 6.2 Event Detail Page Update
**File**: `/frontend/src/pages/EventDetail.jsx`

Add document upload button and document list section:

```jsx
{/* Upload Button */}
<button className="upload-button" onClick={() => setShowUploadModal(true)}>
  <UploadIcon size={20} /> Upload Documents
</button>

{/* Related Documents Section */}
{documents.length > 0 && (
  <div className="event-detail-section">
    <h2><FileTextIcon size={24} /> Related Documents</h2>
    <div className="documents-list">
      {documents.map(doc => (
        <div key={doc.url_hash} className="document-item">
          <FileTextIcon size={16} />
          <span>{doc.title}</span>
          <span className="doc-type">{doc.doc_type}</span>
          <button 
            className="download-button"
            onClick={() => handleDownload(doc.url_hash)}
          >
            <DownloadIcon size={16} />
          </button>
        </div>
      ))}
    </div>
  </div>
)}
```

#### 6.3 Event-Specific Upload Modal
Create a simplified upload modal that pre-selects the current event:

```jsx
<DocumentUploadModal 
  isOpen={showUploadModal}
  onClose={() => setShowUploadModal(false)}
  preSelectedEvent={event.url_hash}
  onUploadComplete={refreshDocuments}
/>
```

---

### Phase 7: Navigation & Routing

#### 7.1 Add Route
**File**: `/frontend/src/App.js`

```jsx
<Route path="/upload" element={<DocumentUpload />} />
```

#### 7.2 Add to Sidebar
**File**: `/frontend/src/components/Sidebar.jsx`

```jsx
{/* Document Upload */}
<Link 
  to="/upload" 
  className={`sidebar-item ${isActive('/upload') ? 'active' : ''}`}
  title="Upload Documents"
>
  <span className="sidebar-icon"><UploadIcon /></span>
  {isOpen && <span className="sidebar-label">Upload Documents</span>}
</Link>
```

#### 7.3 Add Upload Icon
**File**: `/frontend/src/components/icons/index.jsx`

Add `UploadIcon` and `DownloadIcon` components.

---

### Phase 8: API Service Layer

#### 8.1 Frontend API Functions
**File**: `/frontend/src/services/api.js`

```javascript
// Document Upload
export const uploadDocuments = async (formData) => {
  const response = await apiClient.post('/retriever/submit/documents', formData, {
    headers: { 'Content-Type': 'multipart/form-data' }
  });
  return response.data;
};

export const getUserUploads = async () => {
  const response = await apiClient.get('/backend/documents/user-uploads');
  return response.data;
};

export const getDocumentCategories = async () => {
  const response = await apiClient.get('/backend/documents/categories');
  return response.data;
};

// Events - Documents
export const getEventDocuments = async (urlHash) => {
  const response = await apiClient.get(`/backend/events/${urlHash}/documents`);
  return response.data;
};

// Document Download (returns presigned S3 URL)
export const getDocumentDownloadUrl = async (urlHash) => {
  const response = await apiClient.get(`/backend/documents/${urlHash}/download`);
  return response.data.download_url;
};
```

---

## Database Schema Updates

### Neo4j - Resource Node Extension
Add S3 fields to the `Resource` model for download URL generation:

**File**: `/neo4j-client/neo4j_client/models.py`

```python
class Resource(Node):
    # ... existing fields ...
    # content_hash already exists on Resource model
    
    # S3 Storage fields (for user uploads - null for scraped resources)
    s3_bucket: Optional[str] = Field(
        None,
        description="S3 bucket name where the original file is stored"
    )
    s3_key: Optional[str] = Field(
        None,
        description="S3 object key path for generating presigned download URLs"
    )
```

### Existing Models (No New Models Required)
All required relationships already exist:
- `Resource` node (exists) - will have S3 fields added
- `Event` node (exists)
- `ResourceRelatesToEvent` relationship (exists) - links documents to events
- **`ResourceUploadedByPerson` relationship (exists)** - links uploaded documents to the user who uploaded them

### New DataSource Entry
Add a datasource entry for user uploads:

```cypher
CREATE (ds:DataSource {
  datasource_id: 'user_upload',
  name: 'User Uploads',
  description: 'Documents uploaded by users',
  scraper_type: null,
  active: true,
  has_resources: true,
  has_events: false
})
```

---

## Document Categories

Predefined categories for user uploads:
- `meeting_minutes` - Meeting notes and minutes
- `presentation` - Slides and presentations
- `specification` - Technical specifications
- `whitepaper` - Whitepapers and research documents
- `report` - Reports and analyses
- `agenda` - Meeting agendas
- `general` - General documents

---

## File Storage Strategy

### AWS S3 Storage (Required)
Since documents are uploaded from personal devices with no existing URLs, all files are stored in S3:

**Architecture**:
```
User Upload → Retriever Service → S3 (original file) + RabbitMQ (content message)
                                      ↓
                                  Digester → Neo4j (metadata + extracted content)
```

**Key Points**:
1. **Original File Storage**: Files stored in S3 at `uploads/{user_uuid}/{filename}`
2. **Content Extraction**: Text extracted and stored in Neo4j for search/RAG
3. **Secure Access**: Presigned URLs generated on-demand (1 hour expiry default)
4. **Aurora-Only Access**: No public URLs; all access requires Aurora authentication

**S3 Lifecycle Policy** (Optional):
```json
{
    "Rules": [
        {
            "ID": "MoveToInfrequentAccess",
            "Status": "Enabled",
            "Transitions": [
                {
                    "Days": 90,
                    "StorageClass": "STANDARD_IA"
                }
            ]
        }
    ]
}
```

---

## Implementation Order

### Sprint 1: Infrastructure & Backend Foundation
1. Create S3 bucket with proper policies
2. Implement S3 client service in retriever
3. Implement retriever upload endpoint
4. Update digester for event associations and S3 metadata

### Sprint 2: Backend API & Document Management
1. Add backend API endpoints for documents
2. Implement presigned URL generation for downloads
3. Add document-related queries to events service

### Sprint 3: Frontend Upload Page
1. Create DocumentUpload page component
2. Implement file handling and form logic
3. Add API integration
4. Add navigation

### Sprint 4: Events Integration
1. Update Events list with document counts
2. Add documents section to EventDetail
3. Implement event-specific upload modal
4. Add download functionality

### Sprint 5: Polish & Testing
1. Error handling and validation
2. Upload progress indicators
3. User feedback and notifications
4. End-to-end testing

---

## Security Considerations

1. **File Validation**: Validate file types and sizes before processing
2. **Content Scanning**: Consider antivirus scanning for uploaded files
3. **Rate Limiting**: Limit uploads per user/time period
4. **Authentication**: All upload/download endpoints require Aurora authentication
5. **Authorization**: Users can only view/manage their own uploads (unless admin)
6. **S3 Security**: 
   - No public bucket access
   - Presigned URLs with short expiry (1 hour)
   - Server-side encryption (SSE-S3 or SSE-KMS)
   - Access logging enabled
7. **CORS Configuration**: Restrict to Aurora application domains only

---

## API Endpoint Summary

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/retriever/submit/documents` | Upload documents (stores to S3 + queues for processing) |
| GET | `/api/backend/documents/user-uploads` | Get user's uploaded documents |
| GET | `/api/backend/documents/categories` | Get available categories |
| GET | `/api/backend/documents/{hash}/download` | Get presigned S3 URL for download |
| GET | `/api/backend/events/{hash}/documents` | Get event's related documents |
| GET | `/api/backend/events/{hash}/document-count` | Get document count for event |

---

## Success Metrics

- Documents successfully uploaded and processed
- Documents correctly linked to events
- Document counts displayed on events
- User can find their uploaded documents

---

## Open Questions

1. Should we support bulk upload (zip files)?
2. Maximum file size limit? (Suggested: 50MB)
3. Should users be able to delete their uploads?
4. Do we need document versioning?
5. S3 bucket naming convention for different environments?
6. Presigned URL expiry time? (Suggested: 1 hour)
7. Should we implement S3 lifecycle policies to move old documents to cheaper storage?

---

## Appendix: File References

### Files to Create
- `/frontend/src/pages/DocumentUpload.jsx`
- `/frontend/src/pages/DocumentUpload.css`
- `/frontend/src/components/DocumentUploadModal.jsx`
- `/backend/src/routes/documents.py`
- `/backend/src/services/documents_service.py`
- `/retriever/utils/s3_client.py` - S3 storage service

### Files to Modify
- `/retriever/retriever.py` - Implement upload endpoints with S3 storage
- `/retriever/settings.py` - Add S3 configuration
- `/digester/digester.py` - Handle event associations and uploaded_by relationship
- `/backend/src/routes/events.py` - Add document endpoints
- `/backend/src/services/events_service.py` - Add document queries
- `/frontend/src/pages/Events.jsx` - Add document count
- `/frontend/src/pages/EventDetail.jsx` - Add documents section with download
- `/frontend/src/components/Sidebar.jsx` - Add upload link
- `/frontend/src/components/icons/index.jsx` - Add upload and download icons
- `/frontend/src/App.js` - Add upload route
- `/frontend/src/services/api.js` - Add API functions including download

### Infrastructure Setup
- AWS S3 bucket creation and configuration
- IAM policies for service access
- Environment variables for S3 configuration
