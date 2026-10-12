# Nginx Configurations

This directory contains three nginx setups for different use cases.

## Configuration Files

### 1. Hot Reload Development (Default)
**Files:**
- `Dockerfile.hotreload`
- `nginx.hotreload.conf`

**Use Case:** Active development with instant code updates
- Proxies to React dev server (port 3000)
- WebSocket support for Hot Module Replacement (HMR)
- No caching, no rate limiting
- Source maps enabled

**Used By:**
- `docker-compose.yml` (main development file in root)

**When to Use:**
- ✅ Active feature development
- ✅ Want instant hot reload on code changes
- ✅ Need fast iteration and debugging
- ✅ Don't want to rebuild for every change

**Command:**
```bash
docker compose up -d
```

---

### 2. CloudFront / Static Build
**Files:**
- `Dockerfile.cloudfront`
- `nginx.cloudfront.conf`

**Use Case:** Serves static React files (HTTP only)
- Serves React static files from shared volume
- Rate limiting enabled
- Aggressive caching for performance
- Works for production behind CloudFront

**Used By:**
- `prod-deployment/docker-compose.build.yml` (production with CloudFront)

**When to Use:**
- ✅ Test production build locally
- ✅ Production deployment behind AWS CloudFront
- ✅ Want free HTTPS via CloudFront
- ✅ AWS Cognito authentication (requires HTTPS via CloudFront)
- ✅ Don't have or don't want to manage a custom domain

**Command:**
```bash
# Local testing
docker compose up -d

# Production with CloudFront
docker compose -f prod-deployment/docker-compose.build.yml up -d
```

---

### 3. Let's Encrypt (Custom Domain)
**Files:**
- `Dockerfile.letsencrypt`
- `nginx.letsencrypt.conf`
- `init-ssl.sh`
- `renew-certs.sh`

**Use Case:** Direct EC2 with custom domain
- Nginx handles SSL/HTTPS termination
- Automatic SSL certificates via Let's Encrypt
- Requires custom domain pointed to EC2
- Certificate auto-renewal with cron

**Used By:**
- `prod-deployment/docker-compose.prod.yml` (when building locally)

**When to Use:**
- ✅ Have a custom domain
- ✅ Want full control over SSL configuration
- ✅ Don't want to use CloudFront
- ✅ Need specific SSL settings or certificate customization

**Command:**
```bash
docker compose -f prod-deployment/docker-compose.prod.yml up -d
```

---
**Files:**
- `Dockerfile.letsencrypt`
- `nginx.letsencrypt.conf`
- `init-ssl.sh`
- `renew-certs.sh`

**Use Case:** Direct EC2 with custom domain
- Nginx handles SSL/HTTPS termination
- Automatic SSL certificates via Let's Encrypt
- Requires custom domain pointed to EC2
- Certificate auto-renewal with cron

**Used By:**
- `prod-deployment/docker-compose.prod.yml` (when building locally)

**When to Use:**
- ✅ Have a custom domain
- ✅ Want full control over SSL configuration
- ✅ Don't want to use CloudFront
- ✅ Need specific SSL settings or certificate customization

---

## Quick Reference

### Hot Reload Development
```
localhost → Nginx → React Dev Server (3000) → HMR WebSocket
                 ↓
              Auth Service
```

### CloudFront / Static Build
```
localhost or CloudFront → Nginx (80) → Static files from volume
                                     ↓
                                  Auth Service
```

### Let's Encrypt (Custom Domain)
```
Internet → EC2 (443) → Nginx (SSL) → Static files from volume
                                   ↓
                                Auth Service
```

---

## How to Choose

| Feature | Hot Reload | CloudFront/Static | Let's Encrypt |
|---------|-----------|-------------------|---------------|
| **Environment** | Local dev | Local test OR Production | Production |
| **Hot Reload** | Yes | No | No |
| **Build Type** | Dev server | Production | Production |
| **SSL** | None | CloudFront (if prod) | Let's Encrypt |
| **Custom Domain** | Not needed | Optional | Required |
| **Setup Time** | 2 min | 2-5 min | 10 min |
| **Rebuild for changes** | No | Yes | Yes |
| **Rate Limiting** | No | Yes | Yes |
| **Caching** | No | Aggressive | Aggressive |

---

## Shared Volume Architecture

**Static builds (cloudfront, letsencrypt) use volume pattern:**

1. **Frontend Container**: Builds React app → outputs to `/app/build` → **exits**
2. **Shared Volume**: `frontend-build` volume persists the files
3. **Nginx Container**: Mounts volume at `/usr/share/nginx/html` → serves files directly

**Hot reload (development) uses proxy pattern:**

1. **Frontend Container**: Runs React dev server on port 3000 (stays running)
2. **Nginx Container**: Proxies requests to `frontend:3000` → WebSocket for HMR

**Benefits:**
- ✅ Hot reload in dev, production build for testing/prod
- ✅ Cloudfront config works for both local testing AND production
- ✅ Only 3 configs instead of 4
- ✅ Easy to understand and maintain

---

## Configuration

### Hot Reload Development (Default)
```bash
docker compose up -d
# Access at http://localhost or http://localhost:3000
# Edit code → see changes instantly!
```

### Static Build (Production Testing)
```bash
docker compose -f prod-deployment/docker-compose.build.yml up -d
# Access at http://localhost
# Tests production build with CloudFront config
```

### CloudFront (Production)
```bash
docker compose -f prod-deployment/docker-compose.build.yml up -d
# Same nginx config as local static build
# CloudFront handles HTTPS
```

### CloudFront with a Custom Domain
1. Deploy the CloudFront/static nginx variant.
2. Point your custom domain at the CloudFront distribution, not directly at EC2.
3. Set `DEPLOYMENT_DOMAIN` to the public hostname users will browse.
4. Update Cognito callback/logout URLs to that same hostname.

See: `CLOUDFRONT_SETUP.md`

### Let's Encrypt Setup
1. Point domain A record to EC2 IP
2. Set `DEPLOYMENT_DOMAIN` in `.env.prod`
3. Deploy with `docker-compose.prod.yml`
4. SSL certificates auto-generated on first run
5. Auto-renewal runs daily

See: `PRODUCTION_SETUP.md`

---

## Makefile Targets

```bash
# Test configurations
make nginx-test-cloudfront
make nginx-test-letsencrypt

# Reload nginx
make nginx-reload

# View logs
make nginx-logs
```

---

## Files Overview

```
nginx/
├── Dockerfile.hotreload          # Hot reload dev (proxies to React dev server)
├── nginx.hotreload.conf          # Hot reload nginx config
├── Dockerfile.cloudfront         # Static builds (local testing + CloudFront production)
├── nginx.cloudfront.conf         # Cloudfront nginx config
├── Dockerfile.letsencrypt        # Custom domain with SSL
├── nginx.letsencrypt.conf        # Let's Encrypt nginx config
├── init-ssl.sh                   # SSL certificate setup
├── renew-certs.sh                # SSL renewal script
├── Makefile                      
└── README.md                     # This file
```

**Note:** Cloudfront config is reused for both local testing and production!

---

## Important Notes

### Frontend Container No Longer Runs Nginx

**Old Architecture (per service nginx):**
```
Frontend Container: React app + nginx → Exposed port 3000
Nginx Container: Reverse proxy → Routes to frontend:3000
```

**New Architecture (single nginx):**
```
Frontend Container: React app → Shared volume (/app/build)
Nginx Container: Serves static files from volume + proxies API
```

**You can now delete:** `frontend/nginx.conf` (no longer used)

### Volume Sharing

Both containers share the `frontend-build` volume:
- Frontend writes built files to `/app/build`
- Nginx reads files from `/usr/share/nginx/html` (read-only mount)

---

## Need Help?

- **CloudFront Setup**: See `CLOUDFRONT_SETUP.md`
- **Custom Domain Setup**: See `PRODUCTION_SETUP.md`
- **Troubleshooting**: See `TROUBLESHOOTING.md`
