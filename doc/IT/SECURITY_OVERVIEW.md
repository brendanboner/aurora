# Aurora Teams Integration - Security Overview

**Document Version:** 1.0  
**Last Updated:** 2026-03-09  
**Classification:** Internal Use  
**Prepared For:** IT Security & Infrastructure Teams  

---

## Executive Summary

Aurora is an AI-powered knowledge management system that integrates with Microsoft Teams to provide secure, intelligent access to Wi-Fi Alliance documentation. This document outlines the security architecture, authentication mechanisms, and compliance considerations for the Teams integration.

### Application URLs
- **Teams Interface:** `https://d23ew7gbss3vnh.cloudfront.net/teams`
- **Full Application:** `https://d23ew7gbss3vnh.cloudfront.net`

### Key Security Features
- ✅ AWS Cognito OAuth 2.0 authentication
- ✅ JWT token validation on all requests
- ✅ Email domain restriction (@extremenetworks.com)
- ✅ Manual user provisioning by OCTO team
- ✅ Network isolation via Docker private networks
- ✅ CloudFront CDN with HTTPS enforcement
- ✅ Rate limiting and DDoS protection
- ✅ CSRF protection via OAuth state parameters
- ✅ Zero-trust internal architecture

---

## 1. Authentication & Authorization

### 1.1 AWS Cognito Configuration

**Identity Provider:** AWS Cognito User Pool  
**Authentication Method:** OAuth 2.0 Authorization Code Flow with PKCE  
**Token Type:** JWT (JSON Web Tokens)  
**Session Management:** HTTP-only secure cookies  

#### User Requirements
- **Email Domain Restriction:** All users MUST have `@extremenetworks.com` email addresses
- **Provisioning Model:** Manual user creation by OCTO team only
- **No Self-Registration:** Public sign-up is disabled
- **Multi-Factor Authentication:** Available (configurable in Cognito)

### 1.2 Authentication Flow

```
┌─────────────┐                    ┌──────────────────┐                ┌─────────────┐
│   Browser   │                    │  Auth Gateway    │                │ AWS Cognito │
│  (Teams UI) │                    │   (Port 8000)    │                │ User Pool   │
└──────┬──────┘                    └────────┬─────────┘                └──────┬──────┘
       │                                    │                                  │
       │ 1. Access /teams                   │                                  │
       ├───────────────────────────────────>│                                  │
       │                                    │                                  │
       │ 2. No valid token - redirect       │                                  │
       │    to Cognito login                │                                  │
       │<───────────────────────────────────┤                                  │
       │                                    │                                  │
       │ 3. User authenticates              │                                  │
       ├────────────────────────────────────┼─────────────────────────────────>│
       │                                    │                                  │
       │ 4. Callback with auth code         │                                  │
       │<───────────────────────────────────┼──────────────────────────────────┤
       │                                    │                                  │
       │ 5. Exchange code for tokens        │                                  │
       ├───────────────────────────────────>│                                  │
       │                                    │ 6. Validate code                 │
       │                                    ├─────────────────────────────────>│
       │                                    │                                  │
       │                                    │ 7. Return JWT tokens             │
       │                                    │<─────────────────────────────────┤
       │                                    │                                  │
       │ 8. Set HTTP-only cookies           │                                  │
       │<───────────────────────────────────┤                                  │
       │                                    │                                  │
       │ 9. API requests include cookies    │                                  │
       ├───────────────────────────────────>│                                  │
       │                                    │ 10. Validate JWT                 │
       │                                    ├─────────────────────────────────>│
       │                                    │                                  │
       │ 11. Proxy to backend with          │                                  │
       │     X-User-Id, X-User-Email        │                                  │
       │     headers                        │                                  │
```

### 1.3 Token Management

**Token Storage:**
- Access tokens stored in HTTP-only cookies (not accessible to JavaScript)
- Refresh tokens stored in HTTP-only secure cookies
- Tokens never exposed to client-side code

**Token Lifecycle:**
- Access token expiration: 1 hour (configurable)
- Refresh token expiration: 30 days (configurable)
- Automatic refresh when access token expires
- Logout invalidates all tokens

**Session Security:**
- Cookies marked as `Secure` (HTTPS only)
- Cookies marked as `HttpOnly` (no JavaScript access)
- SameSite policy set to `Lax` or `Strict`
- CSRF protection via OAuth state parameter

---

## 2. Network Architecture

### 2.1 CloudFront Distribution

**Primary Entry Point:** AWS CloudFront CDN  
**SSL/TLS:** Managed by AWS Certificate Manager  
**Origin:** Nginx reverse proxy on EC2 instance  

**Security Features:**
- TLS 1.2+ enforcement
- Geographic restrictions (if needed)
- Web Application Firewall (WAF) ready
- DDoS protection via AWS Shield
- Origin access control

### 2.2 Network Isolation

All services operate within a private Docker bridge network:

```
                  Internet
                     │
                     │ HTTPS (443)
                     ▼
         ┌───────────────────────┐
         │  CloudFront CDN       │
         │  (AWS Global)         │
         └───────────┬───────────┘
                     │ HTTPS (443)
                     ▼
         ┌───────────────────────┐
         │  EC2 Instance         │
         │  (VPC Subnet)         │
         │  ┌─────────────────┐  │
         │  │  Nginx (80)     │  │  <-- Only port exposed to internet
         │  └────────┬────────┘  │
         │           │           │
         │  ┌────────▼────────┐  │
         │  │  Auth Gateway   │  │  <-- Port 8000 (internal only)
         │  │  (Port 8000)    │  │
         │  └────────┬────────┘  │
         │           │           │
         │  Docker Private Network (aurora-network)
         │           │
         │  ┌────────┴────────────────────────────┐
         │  │                                     │
         │  │  Backend Services (Internal Only):  │
         │  │  ├─ Backend API (8001)              │
         │  │  ├─ Content Creator (8002)          │
         │  │  ├─ Oracle (8003)                   │
         │  │  ├─ Retriever (8004)                │
         │  │  ├─ Digester (8005)                 │
         │  │  ├─ Curator (8006)                  │
         │  │  ├─ Teams Agent (8007)              │
         │  │  └─ KG View (5173)                  │
         │  │                                     │
         │  │  Infrastructure (Internal Only):    │
         │  │  ├─ PostgreSQL (5432)               │
         │  │  ├─ Neo4j (7474, 7687)              │
         │  │  ├─ RabbitMQ (5672, 15672)          │
         │  │  └─ Redis (6379)                    │
         │  └─────────────────────────────────────┘
         └───────────────────────┘
```

**Security Posture:**
- Only ports 80 and 443 accessible from internet
- All internal services isolated on Docker bridge network
- Services communicate via internal hostnames (no external IPs)
- PostgreSQL, Neo4j, RabbitMQ, Redis not exposed to internet

---

## 3. Authorization Model

### 3.1 Zero-Trust Architecture

All internal services trust the auth gateway as the single point of authentication. Once authenticated, the auth gateway adds trusted headers to proxied requests:

**Trusted Headers:**
- `X-User-Id`: Cognito user UUID
- `X-User-Email`: User's verified email address
- `X-User-Role`: User role (user, admin, superadmin)

**Security Guarantee:**
Internal services can trust these headers because:
1. Only auth gateway can reach internal services (network isolation)
2. Headers cannot be spoofed from external requests
3. Auth gateway validates JWT on every request before proxying

### 3.2 Role-Based Access Control (RBAC)

**User Roles:**
- `user` - Standard access (read content, submit queries)
- `admin` - Elevated access (trigger content refresh, view analytics)
- `superadmin` - Full access (user management, system configuration)

**Authorization Enforcement:**
```python
# Backend services use shared middleware
from common.auth_middleware import require_role

@app.post("/admin/scrape")
@require_role(["admin", "superadmin"])
async def trigger_scrape(user: dict = Depends(get_user_context)):
    # User guaranteed to have admin or superadmin role
    pass
```

---

## 4. Data Protection

### 4.1 Data at Rest

**Database Encryption:**
- PostgreSQL: Volume encryption via Docker/EBS
- Neo4j: Volume encryption via Docker/EBS
- Backup encryption: AES-256 (when enabled)

**Sensitive Data Storage:**
- User passwords: Managed by AWS Cognito (bcrypt)
- API keys: Stored in environment variables (not in code)
- Service credentials: Docker secrets or environment variables

### 4.2 Data in Transit

**External Communications:**
- All client-to-server: HTTPS/TLS 1.2+
- Certificate validation enforced
- Perfect Forward Secrecy enabled

**Internal Communications:**
- Service-to-service: HTTP within Docker network
- No encryption needed (network isolation boundary)
- Could add mutual TLS if required

### 4.3 Data Classification

**Public:**
- Marketing content
- Published documentation (Wi-Fi Alliance specs)

**Internal:**
- User preferences
- Query history
- Analytics data

**Confidential:**
- User email addresses
- Authentication tokens
- System credentials

**No PII Beyond Email:**
- System stores minimal user data (email, preferences)
- No payment information
- No personal health information
- No social security numbers

---

## 5. Logging & Monitoring

### 5.1 Security Event Logging

**Logged Events:**
- Authentication attempts (success/failure)
- Authorization failures (403 responses)
- Token validation failures
- User role changes
- Admin actions
- Anomalous API usage patterns

**Log Format:** Structured JSON with OpenTelemetry  
**Log Retention:** 90 days (configurable)  
**Log Storage:** Grafana Loki (self-hosted)  

### 5.2 Observability Stack

**Components:**
- **Grafana Tempo:** Distributed tracing
- **Grafana Loki:** Log aggregation
- **Prometheus:** Metrics collection
- **Grafana:** Visualization dashboards

**Monitored Metrics:**
- Request latency (p50, p95, p99)
- Error rates by endpoint
- Authentication success/failure rates
- Database connection pool status
- Memory and CPU utilization

---

## 6. Compliance Considerations

### 6.1 GDPR Compliance (if applicable)

**User Rights:**
- Right to access: Users can export their query history
- Right to erasure: User data can be deleted on request
- Right to portability: Data export in JSON format

**Data Minimization:**
- Only email address and preferences stored
- No tracking cookies beyond authentication
- No third-party analytics (self-hosted observability)

### 6.2 Security Standards Alignment

**OWASP Top 10 Mitigations:**
- ✅ A01:2021 – Broken Access Control: RBAC + JWT validation
- ✅ A02:2021 – Cryptographic Failures: HTTPS + secure cookies
- ✅ A03:2021 – Injection: Parameterized queries (SQLAlchemy, Neo4j)
- ✅ A04:2021 – Insecure Design: Security by default architecture
- ✅ A05:2021 – Security Misconfiguration: Principle of least privilege
- ✅ A06:2021 – Vulnerable Components: Automated dependency scanning
- ✅ A07:2021 – Authentication Failures: OAuth 2.0 + AWS Cognito
- ✅ A08:2021 – Data Integrity Failures: HTTPS + secure cookies
- ✅ A09:2021 – Logging Failures: Comprehensive security logging
- ✅ A10:2021 – SSRF: Input validation + network isolation

---

## 7. Incident Response

### 7.1 Security Incident Procedures

**Detection:**
- Automated alerts for authentication anomalies
- Rate limit threshold violations trigger notifications
- Failed authentication attempts logged and monitored

**Response:**
1. Isolate affected services (Docker stop)
2. Preserve logs for forensic analysis
3. Notify security team and stakeholders
4. Investigate root cause
5. Apply patches/mitigations
6. Post-incident review

### 7.2 Emergency Contacts

**OCTO Team (User Provisioning):**  
- Email: [Configured during deployment]  
- Responsible for: User account creation/deletion  

**System Administrator:**  
- Responsible for: Infrastructure, deployment, updates  

**Security Team:**  
- Responsible for: Security reviews, incident response  

---

## 8. User Onboarding Process

### 8.1 New User Request

**Process:**
1. User submits request to OCTO team
2. OCTO team verifies user has @extremenetworks.com email
3. OCTO team creates user in AWS Cognito manually
4. User receives email invitation with temporary password
5. User must change password on first login
6. User gains access to Teams interface

**Manual Provisioning Rationale:**
- Ensures all users are verified employees
- Prevents unauthorized access
- Maintains audit trail of user accounts

### 8.2 User Deprovisioning

**Process:**
1. HR/Manager notifies OCTO team of user departure
2. OCTO team disables user in AWS Cognito
3. User's active sessions invalidated immediately
4. User data retained per retention policy

---

## 9. Penetration Testing Considerations

### 9.1 Recommended Tests

**External Testing:**
- OAuth 2.0 flow security (token theft, CSRF)
- JWT validation bypass attempts
- Session management vulnerabilities
- Rate limiting effectiveness
- Input validation and injection attacks

**Internal Testing:**
- Service-to-service authentication (header spoofing)
- Database injection attacks
- Privilege escalation attempts
- Network segmentation validation

### 9.2 Scope Boundaries

**In Scope:**
- Frontend application (`https://d23ew7gbss3vnh.cloudfront.net`)
- Authentication endpoints
- API endpoints under `/api/*`
- Teams interface (`/teams`)

**Out of Scope:**
- AWS Cognito service (managed by AWS)
- CloudFront infrastructure (managed by AWS)
- Internal services not exposed to internet

---

## 10. Security Hardening Checklist

**Completed:**
- [x] HTTPS enforcement (CloudFront + Nginx)
- [x] HTTP-only secure cookies
- [x] JWT token validation on all requests
- [x] Network isolation (Docker bridge network)
- [x] Rate limiting (Nginx)
- [x] Input validation (FastAPI/Pydantic)
- [x] Parameterized database queries
- [x] Security headers (X-Frame-Options, X-Content-Type-Options, etc.)
- [x] CORS policy restrictions
- [x] Email domain validation (@extremenetworks.com)
- [x] Manual user provisioning

**Recommended Additions:**
- [ ] AWS WAF rules for CloudFront
- [ ] Automated vulnerability scanning (Snyk, Dependabot)
- [ ] Intrusion detection system (Wazuh, OSSEC)
- [ ] Security Information and Event Management (SIEM)
- [ ] Automated certificate rotation monitoring
- [ ] Database backup encryption
- [ ] Multi-factor authentication enforcement

---

## 11. Questions for Security Review

1. **User Access:**
   - Should MFA be mandatory for all users?
   - What is the acceptable session timeout duration?
   - Are there geographic access restrictions?

2. **Data Retention:**
   - How long should user query history be retained?
   - What is the log retention policy?
   - Are there data sovereignty requirements?

3. **Compliance:**
   - Are there specific compliance frameworks to follow (SOC 2, ISO 27001)?
   - Is penetration testing required before go-live?
   - What is the change management process for security updates?

4. **Monitoring:**
   - What security events require real-time alerts?
   - Who should receive security alert notifications?
   - What is the expected incident response time?

---

## 12. Additional Resources

**Related Documentation:**
- [Architecture Diagram](./ARCHITECTURE_DIAGRAM.md)
- [Data Flow Documentation](./DATA_FLOW.md)
- [Authentication Integration Guide](../../auth/INTEGRATION_GUIDE.md)
- [Deployment Documentation](../DEPLOYMENT.md)

**External References:**
- [AWS Cognito Security Best Practices](https://docs.aws.amazon.com/cognito/latest/developerguide/security.html)
- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [OAuth 2.0 Security Best Practices](https://datatracker.ietf.org/doc/html/draft-ietf-oauth-security-topics)

---

**Document Control:**
- **Review Frequency:** Quarterly
- **Next Review Date:** 2026-06-09
- **Document Owner:** OCTO Team
- **Approval Required:** IT Security Team

