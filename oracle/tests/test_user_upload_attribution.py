"""Tests for user-upload source enrichment.

When a user uploads a document via the chat, the document's URL is the
opaque `s3://aurora-document-uploads/...` key — useless to readers. The
oracle's `_enrich_user_upload_sources` rewrites the per-document `source`
field to "Uploaded by <Name>" and exposes a structured `uploaded_by_name`
field that client renderers (Teams, frontend Copy-as-Markdown) use to
build human-friendly attributions without a broken `s3://` link.
"""

from unittest.mock import MagicMock, patch

from src.models.response import Document
from src.routes.query import _enrich_user_upload_sources


def _doc(url, datasource_id="user_upload"):
    return Document(url=url, title="X", datasource_id=datasource_id)


def test_enrichment_prefers_name_over_email():
    """We show the uploader's display name (e.g. 'Brendan Bonner'), not
    their email — names are friendlier in chat surfaces."""
    s3_url = "s3://aurora-document-uploads/uploads/abc/file.pdf"
    docs = [_doc(s3_url)]
    mock_client = MagicMock()
    mock_client.execute_query.return_value = [
        {"url": s3_url, "email": "brendan@example.com", "name": "Brendan Bonner"},
    ]
    mock_repo = MagicMock()
    mock_repo.client = mock_client

    with patch("src.routes.query.get_repo", return_value=mock_repo):
        _enrich_user_upload_sources(docs)

    assert docs[0].source == "Uploaded by Brendan Bonner"
    assert docs[0].uploaded_by_name == "Brendan Bonner"


def test_enrichment_falls_back_to_email_when_no_name():
    """When the Person node has no name, email is the next-best label."""
    s3_url = "s3://aurora-document-uploads/uploads/abc/file.pdf"
    docs = [_doc(s3_url)]
    mock_client = MagicMock()
    mock_client.execute_query.return_value = [
        {"url": s3_url, "email": "anon@example.com", "name": None},
    ]
    mock_repo = MagicMock()
    mock_repo.client = mock_client

    with patch("src.routes.query.get_repo", return_value=mock_repo):
        _enrich_user_upload_sources(docs)

    assert docs[0].source == "Uploaded by anon@example.com"
    assert docs[0].uploaded_by_name is None


def test_enrichment_ignores_non_user_uploads():
    """Documents from other datasources must pass through untouched."""
    docs = [_doc("https://wballiance.com/doc1", datasource_id="wba")]
    with patch("src.routes.query.get_repo") as mock:
        _enrich_user_upload_sources(docs)
        # No user-upload URLs → repo never queried.
        mock.assert_not_called()
    assert docs[0].source is None
    assert docs[0].uploaded_by_name is None


def test_enrichment_skips_on_repo_failure():
    """Repo errors must NOT propagate — answers degrade gracefully."""
    s3_url = "s3://aurora-document-uploads/uploads/abc/file.pdf"
    docs = [_doc(s3_url)]
    mock_repo = MagicMock()
    mock_repo.client.execute_query.side_effect = RuntimeError("neo4j boom")
    with patch("src.routes.query.get_repo", return_value=mock_repo):
        # Must not raise.
        _enrich_user_upload_sources(docs)
    assert docs[0].source is None
