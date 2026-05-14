# Auth Middleware Quick Reference

## Import Statement

```python
from common.auth_middleware import get_user_context, require_user_context, require_role, check_resource_ownership
from fastapi import Depends
from typing import Optional
```

## Patterns

### 1. Public Endpoint (No Auth Required)
```python
@app.get("/health")
async def health():
    return {"status": "healthy"}
```

### 2. Authenticated Endpoint (Any Logged-In User)
```python
@app.post("/query")
@require_user_context
async def query(data: QueryRequest, user: Optional[dict] = Depends(get_user_context)):
    # user is guaranteed to be not None
    logger.info(f"Query from {user['email']}")
    return {"result": "data"}
```

### 3. Admin-Only Endpoint
```python
@app.post("/admin/settings")
@require_role(["admin", "superadmin"])
async def update_settings(settings: dict, user: Optional[dict] = Depends(get_user_context)):
    logger.info(f"Settings updated by {user['email']} (role: {user['role']})")
    return {"status": "updated"}
```

### 4. Superadmin-Only Endpoint
```python
@app.delete("/users/{user_id}")
@require_role(["superadmin"])
async def delete_user(user_id: int, user: Optional[dict] = Depends(get_user_context)):
    logger.warning(f"User deletion by {user['email']}")
    return {"deleted": user_id}
```

### 5. Flexible Endpoint (User or System)
```python
@app.get("/status")
async def get_status(user: Optional[dict] = Depends(get_user_context)):
    if user:
        logger.info(f"Status check by user {user['email']}")
    else:
        logger.debug("Status check by internal service")
    return {"status": "running"}
```

### 6. Resource Ownership Check
```python
@app.get("/documents/{doc_id}")
@require_user_context
async def get_document(doc_id: str, user: Optional[dict] = Depends(get_user_context)):
    doc = get_document_from_db(doc_id)
    
    # Check ownership (users can only access their own, admins can access any)
    if not check_resource_ownership(doc.owner_id, user, allow_admin=True):
        raise HTTPException(status_code=403, detail="Access denied")
    
    return doc
```

### 7. Manual Authorization Check
```python
@app.get("/users/{user_id}/data")
@require_user_context
async def get_user_data(user_id: int, user: Optional[dict] = Depends(get_user_context)):
    # Users can only access their own data unless admin
    if str(user_id) != user["user_id"] and user["role"] not in ["admin", "superadmin"]:
        raise HTTPException(status_code=403, detail="Access denied")
    
    return {"data": "sensitive info"}
```

## User Context Dictionary

When user context is present, it contains:

```python
{
    "user_id": "cognito-user-id",
    "email": "user@example.com",
    "role": "user"  # or "admin" or "superadmin"
}
```

## Service-to-Service Calls

### Import
```python
from common.service_client import call_backend_service, call_curator_service, call_retriever_service
```

### With User Context (User-Initiated)
```python
async def handle_user_request(user: dict):
    result = await call_curator_service(
        path="/trigger/topics",
        method="POST",
        user_context=user  # Propagate user context
    )
    return result
```

### Without User Context (System Operation)
```python
async def scheduled_job():
    status = await call_curator_service(
        path="/status",
        method="GET"
        # No user_context
    )
    return status
```

## Common Role Combinations

- **Public**: No decorator, no auth required
- **Any User**: `@require_user_context`
- **Admin Only**: `@require_role(["admin", "superadmin"])`
- **Superadmin Only**: `@require_role(["superadmin"])`

## Logging Best Practices

```python
# Regular access
logger.info(f"Query from user {user['email']}")

# Privileged access
logger.warning(f"Admin action by {user['email']} (role: {user['role']})")

# Sensitive operations
logger.warning(f"User deletion by {user['email']}: user_id={target_user_id}")
```

## Quick Troubleshooting

**401 Unauthorized**: No user context found
- Check that auth service is passing X-User-* headers
- For testing, manually add headers to request

**403 Forbidden**: User doesn't have required role
- Check user's role in Cognito custom:role attribute
- Verify `@require_role()` decorator has correct roles

**ImportError**: Can't find common.auth_middleware
- Verify common/ folder is copied in Dockerfile
- Rebuild Docker image: `docker-compose build <service>`

## Testing with curl

```bash
# Simulate authenticated request
curl -H "X-User-Id: 123" \
     -H "X-User-Email: user@example.com" \
     -H "X-User-Role: user" \
     http://localhost:8001/query

# Simulate admin request
curl -H "X-User-Id: 456" \
     -H "X-User-Email: admin@example.com" \
     -H "X-User-Role: admin" \
     http://localhost:8001/admin/settings
```
