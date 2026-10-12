"""Document search endpoints for Oracle Service."""

from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional, List
from datetime import datetime
import logging

from pydantic import BaseModel, Field

from common.auth_middleware import get_user_context, require_user_context
from src.services.keyword_retriever import get_repo

router = APIRouter(tags=["documents"])
logger = logging.getLogger(__name__)


# ============== Response Models ==============

class CategoryInfo(BaseModel):
    """Information about a document category."""
    category_id: str = Field(..., description="Category identifier (lowercase)")
    name: str = Field(..., description="Human-readable name")
    document_count: int = Field(default=0, description="Number of documents in this category")


class CategoriesResponse(BaseModel):
    """Response model for /oracle/documents/categories endpoint."""
    categories: List[CategoryInfo] = Field(default_factory=list, description="Available categories")


class DocumentSearchRequest(BaseModel):
    """Request model for document search."""
    keywords: Optional[List[str]] = Field(default=None, description="Keywords to search in title/summary (supports multiple)")
    keyword_match_mode: Optional[str] = Field(default="any", description="How to match keywords: 'any' (OR) or 'all' (AND)")
    datasource_ids: Optional[List[str]] = Field(default=None, description="Filter by datasource IDs")
    categories: Optional[List[str]] = Field(default=None, description="Filter by categories")
    topic_ids: Optional[List[str]] = Field(default=None, description="Filter by related topic IDs")
    organization_ids: Optional[List[str]] = Field(default=None, description="Filter by mentioned organization IDs")
    date_from: Optional[str] = Field(default=None, description="Filter documents from this date (ISO format)")
    date_to: Optional[str] = Field(default=None, description="Filter documents until this date (ISO format)")
    limit: int = Field(default=50, ge=1, le=200, description="Maximum results to return")
    offset: int = Field(default=0, ge=0, description="Offset for pagination")
    sort_by: str = Field(default="publish_date", description="Sort field: 'publish_date', 'title', 'relevance'")
    sort_order: str = Field(default="desc", description="Sort order: 'asc' or 'desc'")


class DocumentResult(BaseModel):
    """A document in search results."""
    url: str = Field(..., description="Document URL")
    url_hash: str = Field(..., description="Document unique identifier")
    title: Optional[str] = Field(default=None, description="Document title")
    summary: Optional[str] = Field(default=None, description="Document summary")
    publish_date: Optional[str] = Field(default=None, description="Publication date (ISO format)")
    category: Optional[str] = Field(default=None, description="Document category")
    datasource_id: Optional[str] = Field(default=None, description="Datasource identifier")
    datasource_name: Optional[str] = Field(default=None, description="Datasource human-readable name")
    topics: List[str] = Field(default_factory=list, description="Related topic names")
    organizations: List[str] = Field(default_factory=list, description="Mentioned organization names")


class DocumentSearchResponse(BaseModel):
    """Response model for document search."""
    documents: List[DocumentResult] = Field(default_factory=list, description="Matching documents")
    total_count: int = Field(default=0, description="Total matching documents (for pagination)")
    limit: int = Field(default=50, description="Limit used")
    offset: int = Field(default=0, description="Offset used")
    filters_applied: dict = Field(default_factory=dict, description="Summary of filters applied")


class DocumentCountResponse(BaseModel):
    """Response model for document count endpoint."""
    count: int = Field(..., description="Number of documents matching the filters")
    filters_applied: dict = Field(default_factory=dict, description="Summary of filters applied")


class TopicInfo(BaseModel):
    """Information about a topic for filtering."""
    topic_id: str = Field(..., description="Topic unique identifier")
    name: str = Field(..., description="Topic name")
    document_count: int = Field(default=0, description="Number of documents with this topic")


class OrganizationInfo(BaseModel):
    """Information about an organization for filtering."""
    org_id: str = Field(..., description="Organization unique identifier")
    name: str = Field(..., description="Organization name")
    document_count: int = Field(default=0, description="Number of documents mentioning this org")


class DataSourceInfo(BaseModel):
    """Information about a datasource for filtering."""
    datasource_id: str = Field(..., description="Unique datasource identifier")
    name: str = Field(..., description="Human-readable name")
    document_count: int = Field(default=0, description="Number of documents from this source")


class FilterOptionsRequest(BaseModel):
    """Request model for getting filter options."""
    datasource_ids: Optional[List[str]] = Field(default=None, description="Filter options by these datasource IDs")
    categories: Optional[List[str]] = Field(default=None, description="Filter options by these categories")
    topic_ids: Optional[List[str]] = Field(default=None, description="Filter options by these topic IDs")
    organization_ids: Optional[List[str]] = Field(default=None, description="Filter options by these organization IDs")


class FilterOptionsResponse(BaseModel):
    """Response model for filter options - supports bidirectional filtering."""
    datasources: List[DataSourceInfo] = Field(default_factory=list, description="Available datasources")
    categories: List[CategoryInfo] = Field(default_factory=list, description="Available categories")
    topics: List[TopicInfo] = Field(default_factory=list, description="Available topics")
    organizations: List[OrganizationInfo] = Field(default_factory=list, description="Available organizations")


# ============== Endpoints ==============

@router.post("/documents/filter-options", response_model=FilterOptionsResponse)
@require_user_context
async def get_filter_options(
    request: FilterOptionsRequest,
    user: Optional[dict] = Depends(get_user_context)
) -> FilterOptionsResponse:
    """
    Get available filter options with bidirectional filtering support.
    
    Supports filtering in any combination:
    - When datasource_ids are provided, returns only categories/topics/orgs from those datasources
    - When categories are provided, returns only datasources/topics/orgs that have those categories
    - When topic_ids are provided, returns only datasources/categories/orgs with those topics
    - When organization_ids are provided, returns only datasources/categories/topics mentioning those orgs
    - Multiple filters can be combined (AND logic)
    """
    try:
        repo = get_repo()
        params = {}
        
        # Build filter clauses based on what's provided
        # We'll use a base Resource match and add constraints for each filter type
        filter_clauses = []
        
        # Datasource filter
        if request.datasource_ids and len(request.datasource_ids) > 0:
            params["datasource_ids"] = request.datasource_ids
            filter_clauses.append("r.datasource_id IN $datasource_ids")
        
        # Category filter
        if request.categories and len(request.categories) > 0:
            params["categories"] = request.categories
            filter_clauses.append("r.category IN $categories")
        
        # Topic filter - needs relationship traversal
        topic_match = ""
        topic_where = ""
        if request.topic_ids and len(request.topic_ids) > 0:
            params["topic_ids"] = request.topic_ids
            topic_match = "MATCH (r)-[:RELATES_TO]->(filter_t:Topic)"
            topic_where = "filter_t.topic_id IN $topic_ids"
        
        # Organization filter - needs relationship traversal
        org_match = ""
        org_where = ""
        if request.organization_ids and len(request.organization_ids) > 0:
            params["org_ids"] = request.organization_ids
            org_match = "MATCH (r)-[:MENTIONS]->(filter_o:Organization)"
            org_where = "filter_o.org_id IN $org_ids"
        
        # Build combined WHERE clause with all conditions
        all_where_conditions = []
        if filter_clauses:
            all_where_conditions.extend(filter_clauses)
        if topic_where:
            all_where_conditions.append(topic_where)
        if org_where:
            all_where_conditions.append(org_where)
        
        where_clause = ""
        if all_where_conditions:
            where_clause = "WHERE " + " AND ".join(all_where_conditions)
        
        # Get datasources - filtered by any selected categories/topics/orgs
        ds_query = f"""
            MATCH (r:Resource)
            {topic_match}
            {org_match}
            {where_clause}
            MATCH (r)-[:INGESTED_FROM]->(ds:DataSource)
            WITH ds, count(DISTINCT r) AS doc_count
            RETURN ds.datasource_id AS datasource_id,
                   ds.name AS name,
                   doc_count
            ORDER BY doc_count DESC
        """
        ds_results = repo.client.execute_query(ds_query, params)
        
        datasources = []
        for record in ds_results:
            datasource_id = record.get("datasource_id")
            name = record.get("name")
            if datasource_id and name:
                datasources.append(DataSourceInfo(
                    datasource_id=datasource_id,
                    name=name,
                    document_count=record.get("doc_count", 0),
                ))
        
        # Get categories - filtered by selected datasources/topics/orgs
        # Build WHERE clause with category requirement plus any other filters
        cat_where_conditions = ["r.category IS NOT NULL", "r.category <> ''"]
        if filter_clauses:
            cat_where_conditions.extend(filter_clauses)
        if topic_where:
            cat_where_conditions.append(topic_where)
        if org_where:
            cat_where_conditions.append(org_where)
        
        cat_query = f"""
            MATCH (r:Resource)
            {topic_match}
            {org_match}
            WHERE {" AND ".join(cat_where_conditions)}
            WITH r.category AS category, count(r) AS doc_count
            RETURN category, doc_count
            ORDER BY doc_count DESC
        """
        cat_results = repo.client.execute_query(cat_query, params)
        
        categories = []
        for record in cat_results:
            category = record.get("category", "")
            if category:
                display_name = category.replace("_", " ").title()
                categories.append(CategoryInfo(
                    category_id=category.lower(),
                    name=display_name,
                    document_count=record.get("doc_count", 0),
                ))
        
        # Get topics - filtered by selected datasources/categories/orgs
        # For topics, we need datasource, category, and org filters (but not topic filter on itself)
        topic_where_conditions = []
        if filter_clauses:
            topic_where_conditions.extend(filter_clauses)
        if org_where:
            topic_where_conditions.append(org_where)
        
        topic_where_clause = ""
        if topic_where_conditions:
            topic_where_clause = "WHERE " + " AND ".join(topic_where_conditions)
        
        topic_query = f"""
            MATCH (r:Resource)
            {org_match}
            {topic_where_clause}
            MATCH (r)-[:RELATES_TO]->(t:Topic)
            WITH t, count(DISTINCT r) AS doc_count
            RETURN t.topic_id AS topic_id, t.name AS name, doc_count
            ORDER BY doc_count DESC
            LIMIT 500
        """
        topic_results = repo.client.execute_query(topic_query, params)
        
        topics = []
        for record in topic_results:
            topic_id = record.get("topic_id")
            name = record.get("name")
            if topic_id and name:
                topics.append(TopicInfo(
                    topic_id=topic_id,
                    name=name,
                    document_count=record.get("doc_count", 0),
                ))
        
        # Get organizations - filtered by selected datasources/categories/topics
        # For orgs, we need datasource, category, and topic filters (but not org filter on itself)
        org_where_conditions = []
        if filter_clauses:
            org_where_conditions.extend(filter_clauses)
        if topic_where:
            org_where_conditions.append(topic_where)
        
        org_where_clause = ""
        if org_where_conditions:
            org_where_clause = "WHERE " + " AND ".join(org_where_conditions)
        
        org_query = f"""
            MATCH (r:Resource)
            {topic_match}
            {org_where_clause}
            MATCH (r)-[:MENTIONS]->(o:Organization)
            WITH o, count(DISTINCT r) AS doc_count
            RETURN o.org_id AS org_id, o.name AS name, doc_count
            ORDER BY doc_count DESC
            LIMIT 500
        """
        org_results = repo.client.execute_query(org_query, params)
        
        organizations = []
        for record in org_results:
            org_id = record.get("org_id")
            name = record.get("name")
            if org_id and name:
                organizations.append(OrganizationInfo(
                    org_id=org_id,
                    name=name,
                    document_count=record.get("doc_count", 0),
                ))
        
        logger.info(f"Retrieved filter options: {len(datasources)} datasources, {len(categories)} categories, {len(topics)} topics, {len(organizations)} orgs")
        
        return FilterOptionsResponse(
            datasources=datasources,
            categories=categories,
            topics=topics,
            organizations=organizations,
        )
        
    except Exception as e:
        logger.exception(f"Failed to get filter options: {e}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "INTERNAL_ERROR",
                "message": str(e),
            }
        )


@router.get("/documents/categories", response_model=CategoriesResponse)
@require_user_context
async def list_categories(
    user: Optional[dict] = Depends(get_user_context)
) -> CategoriesResponse:
    """
    List all document categories with their document counts.
    
    Returns categories found in the graph along with how many documents
    belong to each category.
    """
    try:
        repo = get_repo()
        
        # Query distinct categories from Resource nodes with counts
        query = """
            MATCH (r:Resource)
            WHERE r.category IS NOT NULL AND r.category <> ''
            WITH r.category AS category, count(r) AS doc_count
            RETURN category, doc_count
            ORDER BY doc_count DESC
        """
        
        results = repo.client.execute_query(query)
        
        categories = []
        for record in results:
            category = record.get("category", "")
            if category:
                # Create a clean display name (title case)
                display_name = category.replace("_", " ").title()
                categories.append(CategoryInfo(
                    category_id=category.lower(),
                    name=display_name,
                    document_count=record.get("doc_count", 0),
                ))
        
        logger.info(f"Retrieved {len(categories)} categories")
        return CategoriesResponse(categories=categories)
        
    except Exception as e:
        logger.exception(f"Failed to list categories: {e}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "INTERNAL_ERROR",
                "message": str(e),
            }
        )


@router.post("/documents/count", response_model=DocumentCountResponse)
@require_user_context
async def count_documents(
    request: DocumentSearchRequest,
    user: Optional[dict] = Depends(get_user_context)
) -> DocumentCountResponse:
    """
    Get the count of documents matching the given filters without returning the documents.
    
    This is useful for showing users how many documents will be returned before they search.
    Uses the same filtering logic as the search endpoint.
    """
    try:
        repo = get_repo()
        
        # Build dynamic Cypher query (same logic as search)
        match_clauses = ["MATCH (r:Resource)"]
        where_clauses = []
        params = {}
        
        # Keyword search in title and summary
        if request.keywords and len(request.keywords) > 0:
            keyword_conditions = []
            for i, keyword in enumerate(request.keywords):
                param_name = f"keyword_{i}"
                params[param_name] = f"(?i).*{keyword}.*"
                keyword_conditions.append(
                    f"(r.title =~ ${param_name} OR r.summary =~ ${param_name})"
                )
            
            if request.keyword_match_mode == "all":
                where_clauses.append(f"({' AND '.join(keyword_conditions)})")
            else:
                where_clauses.append(f"({' OR '.join(keyword_conditions)})")
        
        # Datasource filter
        if request.datasource_ids and len(request.datasource_ids) > 0:
            params["datasource_ids"] = request.datasource_ids
            where_clauses.append("r.datasource_id IN $datasource_ids")
        
        # Category filter
        if request.categories and len(request.categories) > 0:
            params["categories"] = [c.lower() for c in request.categories]
            where_clauses.append("toLower(r.category) IN $categories")
        
        # Date range filters
        # Note: publish_date is stored as a string (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS format)
        # We use string comparison which works correctly for ISO format dates
        if request.date_from:
            try:
                date_from = request.date_from.replace('Z', '+00:00')
                if len(date_from) > 10:
                    date_from = date_from[:10]  # Use just the date part
                datetime.fromisoformat(date_from)
                params["date_from"] = date_from
                where_clauses.append("substring(r.publish_date, 0, 10) >= $date_from")
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid date_from format. Use ISO format (YYYY-MM-DD)")
        
        if request.date_to:
            try:
                date_to = request.date_to.replace('Z', '+00:00')
                if len(date_to) > 10:
                    date_to = date_to[:10]  # Use just the date part
                datetime.fromisoformat(date_to)
                params["date_to"] = date_to
                where_clauses.append("substring(r.publish_date, 0, 10) <= $date_to")
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid date_to format. Use ISO format (YYYY-MM-DD)")
        
        # Topic filter
        topic_filter_active = request.topic_ids and len(request.topic_ids) > 0
        if topic_filter_active:
            params["topic_ids"] = request.topic_ids
            match_clauses.append("MATCH (r)-[:RELATES_TO]->(t:Topic)")
            where_clauses.append("t.topic_id IN $topic_ids")
        
        # Organization filter
        org_filter_active = request.organization_ids and len(request.organization_ids) > 0
        if org_filter_active:
            params["org_ids"] = request.organization_ids
            match_clauses.append("MATCH (r)-[:MENTIONS]->(o:Organization)")
            where_clauses.append("o.org_id IN $org_ids")
        
        # Build complete query - just count, no need to return documents
        where_part = ""
        if where_clauses:
            where_part = " WHERE " + " AND ".join(where_clauses)
        
        count_query = f"""
            {' '.join(match_clauses)}
            {where_part}
            RETURN count(DISTINCT r) AS total_count
        """
        
        results = repo.client.execute_query(count_query, params)
        total_count = results[0].get("total_count", 0) if results else 0
        
        # Build filters summary
        filters_applied = {}
        if request.keywords:
            filters_applied["keywords"] = request.keywords
        if request.datasource_ids:
            filters_applied["datasource_ids"] = request.datasource_ids
        if request.categories:
            filters_applied["categories"] = request.categories
        if request.topic_ids:
            filters_applied["topic_ids"] = request.topic_ids
        if request.organization_ids:
            filters_applied["organization_ids"] = request.organization_ids
        if request.date_from:
            filters_applied["date_from"] = request.date_from
        if request.date_to:
            filters_applied["date_to"] = request.date_to
        
        logger.info(f"Document count: {total_count} documents match the filters")
        
        return DocumentCountResponse(
            count=total_count,
            filters_applied=filters_applied,
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to count documents: {e}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "INTERNAL_ERROR",
                "message": str(e),
            }
        )


@router.post("/documents/search", response_model=DocumentSearchResponse)
@require_user_context
async def search_documents(
    request: DocumentSearchRequest,
    user: Optional[dict] = Depends(get_user_context)
) -> DocumentSearchResponse:
    """
    Search and filter documents in the knowledge graph.
    
    Supports filtering by:
    - Multiple keywords (with AND/OR matching)
    - Datasources
    - Categories
    - Related topics
    - Mentioned organizations
    - Date range
    
    Results are paginated and can be sorted by publish_date, title, or relevance.
    """
    try:
        repo = get_repo()
        
        # Build dynamic Cypher query
        match_clauses = ["MATCH (r:Resource)"]
        where_clauses = []
        params = {}
        
        # Optional relationships for topic/org filtering
        optional_matches = []
        
        # Keyword search in title and summary
        if request.keywords and len(request.keywords) > 0:
            keyword_conditions = []
            for i, keyword in enumerate(request.keywords):
                param_name = f"keyword_{i}"
                params[param_name] = f"(?i).*{keyword}.*"
                keyword_conditions.append(
                    f"(r.title =~ ${param_name} OR r.summary =~ ${param_name})"
                )
            
            if request.keyword_match_mode == "all":
                # AND - all keywords must match
                where_clauses.append(f"({' AND '.join(keyword_conditions)})")
            else:
                # OR - any keyword matches (default)
                where_clauses.append(f"({' OR '.join(keyword_conditions)})")
        
        # Datasource filter
        if request.datasource_ids and len(request.datasource_ids) > 0:
            params["datasource_ids"] = request.datasource_ids
            where_clauses.append("r.datasource_id IN $datasource_ids")
        
        # Category filter
        if request.categories and len(request.categories) > 0:
            params["categories"] = [c.lower() for c in request.categories]
            where_clauses.append("toLower(r.category) IN $categories")
        
        # Date range filters
        # Note: publish_date is stored as a string (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS format)
        # We use string comparison which works correctly for ISO format dates
        if request.date_from:
            try:
                date_from = request.date_from.replace('Z', '+00:00')
                if len(date_from) > 10:
                    date_from = date_from[:10]  # Use just the date part
                datetime.fromisoformat(date_from)
                params["date_from"] = date_from
                where_clauses.append("substring(r.publish_date, 0, 10) >= $date_from")
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid date_from format. Use ISO format (YYYY-MM-DD)")
        
        if request.date_to:
            try:
                date_to = request.date_to.replace('Z', '+00:00')
                if len(date_to) > 10:
                    date_to = date_to[:10]  # Use just the date part
                datetime.fromisoformat(date_to)
                params["date_to"] = date_to
                where_clauses.append("substring(r.publish_date, 0, 10) <= $date_to")
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid date_to format. Use ISO format (YYYY-MM-DD)")
        
        # Topic filter - requires relationship traversal
        topic_filter_active = request.topic_ids and len(request.topic_ids) > 0
        if topic_filter_active:
            params["topic_ids"] = request.topic_ids
            match_clauses.append("MATCH (r)-[:RELATES_TO]->(t:Topic)")
            where_clauses.append("t.topic_id IN $topic_ids")
        
        # Organization filter - requires relationship traversal
        org_filter_active = request.organization_ids and len(request.organization_ids) > 0
        if org_filter_active:
            params["org_ids"] = request.organization_ids
            match_clauses.append("MATCH (r)-[:MENTIONS]->(o:Organization)")
            where_clauses.append("o.org_id IN $org_ids")
        
        # Build WHERE clause
        where_clause = ""
        if where_clauses:
            where_clause = "WHERE " + " AND ".join(where_clauses)
        
        # Sorting
        sort_field = "r.publish_date"
        if request.sort_by == "title":
            sort_field = "r.title"
        elif request.sort_by == "relevance":
            # For relevance, we'd use a score - default to date for now
            sort_field = "r.publish_date"
        
        sort_direction = "DESC" if request.sort_order.lower() == "desc" else "ASC"
        
        # First, get total count
        count_query = f"""
            {' '.join(match_clauses)}
            {where_clause}
            RETURN count(DISTINCT r) AS total
        """
        
        logger.debug(f"Document search count query: {count_query}")
        logger.debug(f"Query parameters: {params}")
        
        count_result = repo.client.execute_query(count_query, params)
        total_count = count_result[0].get("total", 0) if count_result else 0
        
        # Main query with pagination
        params["limit"] = request.limit
        params["offset"] = request.offset
        
        main_query = f"""
            {' '.join(match_clauses)}
            {where_clause}
            WITH DISTINCT r
            ORDER BY {sort_field} {sort_direction}
            SKIP $offset
            LIMIT $limit
            
            // Get related topics
            OPTIONAL MATCH (r)-[:RELATES_TO]->(topic:Topic)
            WITH r, collect(DISTINCT topic.name) AS topics
            
            // Get mentioned organizations
            OPTIONAL MATCH (r)-[:MENTIONS]->(org:Organization)
            WITH r, topics, collect(DISTINCT org.name) AS organizations
            
            // Get datasource info
            OPTIONAL MATCH (r)-[:INGESTED_FROM]->(ds:DataSource)
            
            RETURN r.url AS url,
                   r.url_hash AS url_hash,
                   r.title AS title,
                   r.summary AS summary,
                   toString(r.publish_date) AS publish_date,
                   r.category AS category,
                   r.datasource_id AS datasource_id,
                   ds.name AS datasource_name,
                   topics,
                   organizations
        """
        
        results = repo.client.execute_query(main_query, params)
        
        documents = []
        for record in results:
            documents.append(DocumentResult(
                url=record.get("url", ""),
                url_hash=record.get("url_hash", ""),
                title=record.get("title"),
                summary=record.get("summary"),
                publish_date=record.get("publish_date"),
                category=record.get("category"),
                datasource_id=record.get("datasource_id"),
                datasource_name=record.get("datasource_name"),
                topics=record.get("topics", []),
                organizations=record.get("organizations", []),
            ))
        
        # Build filters summary
        filters_applied = {}
        if request.keywords:
            filters_applied["keywords"] = request.keywords
            filters_applied["keyword_match_mode"] = request.keyword_match_mode
        if request.datasource_ids:
            filters_applied["datasource_ids"] = request.datasource_ids
        if request.categories:
            filters_applied["categories"] = request.categories
        if request.topic_ids:
            filters_applied["topic_ids"] = request.topic_ids
        if request.organization_ids:
            filters_applied["organization_ids"] = request.organization_ids
        if request.date_from:
            filters_applied["date_from"] = request.date_from
        if request.date_to:
            filters_applied["date_to"] = request.date_to
        
        logger.info(f"Document search returned {len(documents)} of {total_count} total results")
        
        return DocumentSearchResponse(
            documents=documents,
            total_count=total_count,
            limit=request.limit,
            offset=request.offset,
            filters_applied=filters_applied,
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Document search failed: {e}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "INTERNAL_ERROR",
                "message": str(e),
            }
        )
