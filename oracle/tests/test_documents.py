"""Tests for Document Search API endpoints."""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

from src.api import app


class TestCategoriesEndpoint:
    """Tests for GET /documents/categories endpoint."""
    
    @pytest.fixture
    def client(self):
        return TestClient(app)
    
    @pytest.fixture
    def mock_repo(self):
        """Create a mock repository with Neo4j client."""
        mock_client = MagicMock()
        mock_repo = MagicMock()
        mock_repo.client = mock_client
        return mock_repo
    
    def test_categories_requires_authentication(self, client):
        """Test that categories endpoint requires authentication."""
        response = client.get("/documents/categories")
        assert response.status_code == 401
    
    def test_categories_returns_200_with_auth(self, client, mock_repo):
        """Test categories returns 200 with authentication."""
        mock_repo.client.execute_query.return_value = [
            {"category": "press_release", "doc_count": 50},
            {"category": "blog_post", "doc_count": 30},
        ]
        
        with patch('src.routes.documents.get_repo', return_value=mock_repo):
            response = client.get(
                "/documents/categories",
                headers={
                    "X-User-ID": "test-user-123",
                    "X-User-Email": "test@example.com"
                }
            )
            
            assert response.status_code == 200
            data = response.json()
            assert "categories" in data
            assert len(data["categories"]) == 2
    
    def test_categories_returns_correct_format(self, client, mock_repo):
        """Test that categories have correct format."""
        mock_repo.client.execute_query.return_value = [
            {"category": "press_release", "doc_count": 50},
        ]
        
        with patch('src.routes.documents.get_repo', return_value=mock_repo):
            response = client.get(
                "/documents/categories",
                headers={
                    "X-User-ID": "test-user-123",
                    "X-User-Email": "test@example.com"
                }
            )
            
            data = response.json()
            category = data["categories"][0]
            
            assert "category_id" in category
            assert "name" in category
            assert "document_count" in category
            assert category["category_id"] == "press_release"
            assert category["name"] == "Press Release"  # Title case
            assert category["document_count"] == 50
    
    def test_categories_handles_empty_results(self, client, mock_repo):
        """Test categories handles empty results gracefully."""
        mock_repo.client.execute_query.return_value = []
        
        with patch('src.routes.documents.get_repo', return_value=mock_repo):
            response = client.get(
                "/documents/categories",
                headers={
                    "X-User-ID": "test-user-123",
                    "X-User-Email": "test@example.com"
                }
            )
            
            assert response.status_code == 200
            data = response.json()
            assert data["categories"] == []
    
    def test_categories_handles_db_error(self, client, mock_repo):
        """Test categories handles database errors gracefully."""
        mock_repo.client.execute_query.side_effect = Exception("DB connection failed")
        
        with patch('src.routes.documents.get_repo', return_value=mock_repo):
            response = client.get(
                "/documents/categories",
                headers={
                    "X-User-ID": "test-user-123",
                    "X-User-Email": "test@example.com"
                }
            )
            
            assert response.status_code == 500
            data = response.json()
            assert "error" in data["detail"]


class TestFilterOptionsEndpoint:
    """Tests for POST /documents/filter-options endpoint."""
    
    @pytest.fixture
    def client(self):
        return TestClient(app)
    
    @pytest.fixture
    def mock_repo(self):
        """Create a mock repository with Neo4j client."""
        mock_client = MagicMock()
        mock_repo = MagicMock()
        mock_repo.client = mock_client
        return mock_repo
    
    def test_filter_options_requires_authentication(self, client):
        """Test that filter-options endpoint requires authentication."""
        response = client.post("/documents/filter-options", json={})
        assert response.status_code == 401
    
    def test_filter_options_returns_200_with_auth(self, client, mock_repo):
        """Test filter-options returns 200 with authentication."""
        # Mock returns for categories, topics, organizations queries
        mock_repo.client.execute_query.side_effect = [
            [{"category": "press_release", "doc_count": 50}],  # categories
            [{"topic_id": "wifi7", "name": "Wi-Fi 7", "doc_count": 30}],  # topics
            [{"org_id": "wfa", "name": "Wi-Fi Alliance", "doc_count": 20}],  # orgs
        ]
        
        with patch('src.routes.documents.get_repo', return_value=mock_repo):
            response = client.post(
                "/documents/filter-options",
                json={},
                headers={
                    "X-User-ID": "test-user-123",
                    "X-User-Email": "test@example.com"
                }
            )
            
            assert response.status_code == 200
            data = response.json()
            assert "categories" in data
            assert "topics" in data
            assert "organizations" in data
    
    def test_filter_options_without_datasource_filter(self, client, mock_repo):
        """Test filter options returns all options when no datasource specified."""
        mock_repo.client.execute_query.side_effect = [
            [
                {"category": "press_release", "doc_count": 50},
                {"category": "blog_post", "doc_count": 30},
            ],
            [
                {"topic_id": "wifi7", "name": "Wi-Fi 7", "doc_count": 30},
                {"topic_id": "wifi6e", "name": "Wi-Fi 6E", "doc_count": 25},
            ],
            [
                {"org_id": "wfa", "name": "Wi-Fi Alliance", "doc_count": 20},
            ],
        ]
        
        with patch('src.routes.documents.get_repo', return_value=mock_repo):
            response = client.post(
                "/documents/filter-options",
                json={},
                headers={
                    "X-User-ID": "test-user-123",
                    "X-User-Email": "test@example.com"
                }
            )
            
            data = response.json()
            assert len(data["categories"]) == 2
            assert len(data["topics"]) == 2
            assert len(data["organizations"]) == 1
    
    def test_filter_options_with_datasource_filter(self, client, mock_repo):
        """Test filter options filters by datasource when specified."""
        # When datasource is specified, expect filtered results
        mock_repo.client.execute_query.side_effect = [
            [{"category": "press_release", "doc_count": 10}],  # filtered categories
            [{"topic_id": "wifi7", "name": "Wi-Fi 7", "doc_count": 8}],  # filtered topics
            [{"org_id": "wfa", "name": "Wi-Fi Alliance", "doc_count": 5}],  # filtered orgs
        ]
        
        with patch('src.routes.documents.get_repo', return_value=mock_repo):
            response = client.post(
                "/documents/filter-options",
                json={"datasource_ids": ["ds-wifi8"]},
                headers={
                    "X-User-ID": "test-user-123",
                    "X-User-Email": "test@example.com"
                }
            )
            
            assert response.status_code == 200
            data = response.json()
            
            # Verify datasource filter was applied (check query was called with params)
            calls = mock_repo.client.execute_query.call_args_list
            # Each call should have params with datasource_ids
            for call in calls:
                args, kwargs = call
                if len(args) > 1:
                    assert "datasource_ids" in args[1]
    
    def test_filter_options_handles_empty_results(self, client, mock_repo):
        """Test filter options handles empty results gracefully."""
        mock_repo.client.execute_query.side_effect = [
            [],  # no categories
            [],  # no topics
            [],  # no orgs
        ]
        
        with patch('src.routes.documents.get_repo', return_value=mock_repo):
            response = client.post(
                "/documents/filter-options",
                json={},
                headers={
                    "X-User-ID": "test-user-123",
                    "X-User-Email": "test@example.com"
                }
            )
            
            assert response.status_code == 200
            data = response.json()
            assert data["categories"] == []
            assert data["topics"] == []
            assert data["organizations"] == []


class TestDocumentSearchEndpoint:
    """Tests for POST /documents/search endpoint."""
    
    @pytest.fixture
    def client(self):
        return TestClient(app)
    
    @pytest.fixture
    def mock_repo(self):
        """Create a mock repository with Neo4j client."""
        mock_client = MagicMock()
        mock_repo = MagicMock()
        mock_repo.client = mock_client
        return mock_repo
    
    @pytest.fixture
    def sample_document_result(self):
        """Sample document result from Neo4j query."""
        return {
            "url": "https://example.com/doc1",
            "url_hash": "abc123",
            "title": "Wi-Fi 7 Announcement",
            "summary": "Wi-Fi Alliance announces Wi-Fi 7 certification",
            "publish_date": "2025-01-10T00:00:00Z",
            "category": "press_release",
            "datasource_id": "ds-wfa",
            "datasource_name": "Wi-Fi Alliance",
            "topics": ["Wi-Fi 7", "certification"],
            "organizations": ["Wi-Fi Alliance"],
        }
    
    def test_search_requires_authentication(self, client):
        """Test that search endpoint requires authentication."""
        response = client.post("/documents/search", json={})
        assert response.status_code == 401
    
    def test_search_returns_200_with_auth(self, client, mock_repo, sample_document_result):
        """Test search returns 200 with authentication."""
        # Mock count query and main query
        mock_repo.client.execute_query.side_effect = [
            [{"total": 1}],  # count query
            [sample_document_result],  # main query
        ]
        
        with patch('src.routes.documents.get_repo', return_value=mock_repo):
            response = client.post(
                "/documents/search",
                json={},
                headers={
                    "X-User-ID": "test-user-123",
                    "X-User-Email": "test@example.com"
                }
            )
            
            assert response.status_code == 200
            data = response.json()
            assert "documents" in data
            assert "total_count" in data
            assert "limit" in data
            assert "offset" in data
    
    def test_search_returns_correct_document_format(self, client, mock_repo, sample_document_result):
        """Test that documents have correct format."""
        mock_repo.client.execute_query.side_effect = [
            [{"total": 1}],
            [sample_document_result],
        ]
        
        with patch('src.routes.documents.get_repo', return_value=mock_repo):
            response = client.post(
                "/documents/search",
                json={},
                headers={
                    "X-User-ID": "test-user-123",
                    "X-User-Email": "test@example.com"
                }
            )
            
            data = response.json()
            doc = data["documents"][0]
            
            assert doc["url"] == "https://example.com/doc1"
            assert doc["url_hash"] == "abc123"
            assert doc["title"] == "Wi-Fi 7 Announcement"
            assert doc["category"] == "press_release"
            assert doc["topics"] == ["Wi-Fi 7", "certification"]
            assert doc["organizations"] == ["Wi-Fi Alliance"]
    
    def test_search_with_keyword_filter(self, client, mock_repo, sample_document_result):
        """Test search with keyword filtering."""
        mock_repo.client.execute_query.side_effect = [
            [{"total": 1}],
            [sample_document_result],
        ]
        
        with patch('src.routes.documents.get_repo', return_value=mock_repo):
            response = client.post(
                "/documents/search",
                json={"keywords": ["Wi-Fi 7"]},
                headers={
                    "X-User-ID": "test-user-123",
                    "X-User-Email": "test@example.com"
                }
            )
            
            assert response.status_code == 200
            data = response.json()
            assert data["filters_applied"]["keywords"] == ["Wi-Fi 7"]
    
    def test_search_with_multiple_keywords_any_mode(self, client, mock_repo, sample_document_result):
        """Test search with multiple keywords in 'any' (OR) mode."""
        mock_repo.client.execute_query.side_effect = [
            [{"total": 2}],
            [sample_document_result],
        ]
        
        with patch('src.routes.documents.get_repo', return_value=mock_repo):
            response = client.post(
                "/documents/search",
                json={
                    "keywords": ["Wi-Fi", "certification"],
                    "keyword_match_mode": "any"
                },
                headers={
                    "X-User-ID": "test-user-123",
                    "X-User-Email": "test@example.com"
                }
            )
            
            assert response.status_code == 200
            data = response.json()
            assert data["filters_applied"]["keyword_match_mode"] == "any"
    
    def test_search_with_multiple_keywords_all_mode(self, client, mock_repo, sample_document_result):
        """Test search with multiple keywords in 'all' (AND) mode."""
        mock_repo.client.execute_query.side_effect = [
            [{"total": 1}],
            [sample_document_result],
        ]
        
        with patch('src.routes.documents.get_repo', return_value=mock_repo):
            response = client.post(
                "/documents/search",
                json={
                    "keywords": ["Wi-Fi", "certification"],
                    "keyword_match_mode": "all"
                },
                headers={
                    "X-User-ID": "test-user-123",
                    "X-User-Email": "test@example.com"
                }
            )
            
            assert response.status_code == 200
            data = response.json()
            assert data["filters_applied"]["keyword_match_mode"] == "all"
    
    def test_search_with_datasource_filter(self, client, mock_repo, sample_document_result):
        """Test search with datasource filtering."""
        mock_repo.client.execute_query.side_effect = [
            [{"total": 1}],
            [sample_document_result],
        ]
        
        with patch('src.routes.documents.get_repo', return_value=mock_repo):
            response = client.post(
                "/documents/search",
                json={"datasource_ids": ["ds-wfa"]},
                headers={
                    "X-User-ID": "test-user-123",
                    "X-User-Email": "test@example.com"
                }
            )
            
            assert response.status_code == 200
            data = response.json()
            assert data["filters_applied"]["datasource_ids"] == ["ds-wfa"]
    
    def test_search_with_category_filter(self, client, mock_repo, sample_document_result):
        """Test search with category filtering."""
        mock_repo.client.execute_query.side_effect = [
            [{"total": 1}],
            [sample_document_result],
        ]
        
        with patch('src.routes.documents.get_repo', return_value=mock_repo):
            response = client.post(
                "/documents/search",
                json={"categories": ["press_release"]},
                headers={
                    "X-User-ID": "test-user-123",
                    "X-User-Email": "test@example.com"
                }
            )
            
            assert response.status_code == 200
            data = response.json()
            assert data["filters_applied"]["categories"] == ["press_release"]
    
    def test_search_with_topic_filter(self, client, mock_repo, sample_document_result):
        """Test search with topic filtering."""
        mock_repo.client.execute_query.side_effect = [
            [{"total": 1}],
            [sample_document_result],
        ]
        
        with patch('src.routes.documents.get_repo', return_value=mock_repo):
            response = client.post(
                "/documents/search",
                json={"topic_ids": ["wifi7"]},
                headers={
                    "X-User-ID": "test-user-123",
                    "X-User-Email": "test@example.com"
                }
            )
            
            assert response.status_code == 200
            data = response.json()
            assert data["filters_applied"]["topic_ids"] == ["wifi7"]
    
    def test_search_with_organization_filter(self, client, mock_repo, sample_document_result):
        """Test search with organization filtering."""
        mock_repo.client.execute_query.side_effect = [
            [{"total": 1}],
            [sample_document_result],
        ]
        
        with patch('src.routes.documents.get_repo', return_value=mock_repo):
            response = client.post(
                "/documents/search",
                json={"organization_ids": ["wfa"]},
                headers={
                    "X-User-ID": "test-user-123",
                    "X-User-Email": "test@example.com"
                }
            )
            
            assert response.status_code == 200
            data = response.json()
            assert data["filters_applied"]["organization_ids"] == ["wfa"]
    
    def test_search_with_date_range(self, client, mock_repo, sample_document_result):
        """Test search with date range filtering."""
        mock_repo.client.execute_query.side_effect = [
            [{"total": 1}],
            [sample_document_result],
        ]
        
        with patch('src.routes.documents.get_repo', return_value=mock_repo):
            response = client.post(
                "/documents/search",
                json={
                    "date_from": "2025-01-01",
                    "date_to": "2025-01-31"
                },
                headers={
                    "X-User-ID": "test-user-123",
                    "X-User-Email": "test@example.com"
                }
            )
            
            assert response.status_code == 200
            data = response.json()
            assert data["filters_applied"]["date_from"] == "2025-01-01"
            assert data["filters_applied"]["date_to"] == "2025-01-31"
    
    def test_search_with_invalid_date_format(self, client, mock_repo):
        """Test search rejects invalid date format."""
        with patch('src.routes.documents.get_repo', return_value=mock_repo):
            response = client.post(
                "/documents/search",
                json={"date_from": "not-a-date"},
                headers={
                    "X-User-ID": "test-user-123",
                    "X-User-Email": "test@example.com"
                }
            )
            
            assert response.status_code == 400
    
    def test_search_pagination(self, client, mock_repo, sample_document_result):
        """Test search pagination parameters."""
        mock_repo.client.execute_query.side_effect = [
            [{"total": 100}],
            [sample_document_result],
        ]
        
        with patch('src.routes.documents.get_repo', return_value=mock_repo):
            response = client.post(
                "/documents/search",
                json={"limit": 20, "offset": 40},
                headers={
                    "X-User-ID": "test-user-123",
                    "X-User-Email": "test@example.com"
                }
            )
            
            assert response.status_code == 200
            data = response.json()
            assert data["limit"] == 20
            assert data["offset"] == 40
            assert data["total_count"] == 100
    
    def test_search_sorting(self, client, mock_repo, sample_document_result):
        """Test search sorting parameters."""
        mock_repo.client.execute_query.side_effect = [
            [{"total": 1}],
            [sample_document_result],
        ]
        
        with patch('src.routes.documents.get_repo', return_value=mock_repo):
            response = client.post(
                "/documents/search",
                json={"sort_by": "title", "sort_order": "asc"},
                headers={
                    "X-User-ID": "test-user-123",
                    "X-User-Email": "test@example.com"
                }
            )
            
            assert response.status_code == 200
    
    def test_search_validates_limit(self, client):
        """Test search validates limit parameter."""
        response = client.post(
            "/documents/search",
            json={"limit": 500},  # exceeds max of 200
            headers={
                "X-User-ID": "test-user-123",
                "X-User-Email": "test@example.com"
            }
        )
        
        assert response.status_code == 422  # Validation error
    
    def test_search_handles_empty_results(self, client, mock_repo):
        """Test search handles empty results gracefully."""
        mock_repo.client.execute_query.side_effect = [
            [{"total": 0}],
            [],
        ]
        
        with patch('src.routes.documents.get_repo', return_value=mock_repo):
            response = client.post(
                "/documents/search",
                json={},
                headers={
                    "X-User-ID": "test-user-123",
                    "X-User-Email": "test@example.com"
                }
            )
            
            assert response.status_code == 200
            data = response.json()
            assert data["documents"] == []
            assert data["total_count"] == 0
    
    def test_search_handles_db_error(self, client, mock_repo):
        """Test search handles database errors gracefully."""
        mock_repo.client.execute_query.side_effect = Exception("DB connection failed")
        
        with patch('src.routes.documents.get_repo', return_value=mock_repo):
            response = client.post(
                "/documents/search",
                json={},
                headers={
                    "X-User-ID": "test-user-123",
                    "X-User-Email": "test@example.com"
                }
            )
            
            assert response.status_code == 500
            data = response.json()
            assert "error" in data["detail"]
    
    def test_search_with_combined_filters(self, client, mock_repo, sample_document_result):
        """Test search with multiple filters combined."""
        mock_repo.client.execute_query.side_effect = [
            [{"total": 1}],
            [sample_document_result],
        ]
        
        with patch('src.routes.documents.get_repo', return_value=mock_repo):
            response = client.post(
                "/documents/search",
                json={
                    "keywords": ["Wi-Fi"],
                    "datasource_ids": ["ds-wfa"],
                    "categories": ["press_release"],
                    "topic_ids": ["wifi7"],
                    "date_from": "2025-01-01"
                },
                headers={
                    "X-User-ID": "test-user-123",
                    "X-User-Email": "test@example.com"
                }
            )
            
            assert response.status_code == 200
            data = response.json()
            # Verify all filters are recorded
            assert "keywords" in data["filters_applied"]
            assert "datasource_ids" in data["filters_applied"]
            assert "categories" in data["filters_applied"]
            assert "topic_ids" in data["filters_applied"]
            assert "date_from" in data["filters_applied"]
