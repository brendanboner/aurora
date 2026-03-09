# Aurora Teams Integration - IT Documentation

**Document Collection Version:** 1.0  
**Last Updated:** 2026-03-09  
**Prepared For:** IT Security & Infrastructure Teams  
**Prepared By:** OCTO Team  

---

## Overview

This directory contains comprehensive technical documentation for the Aurora Teams integration, prepared for IT security reviews, infrastructure planning, and compliance audits. The documentation covers architecture, security controls, data flows, and operational procedures.

---

## Document Index

### 1. [SECURITY_OVERVIEW.md](./SECURITY_OVERVIEW.md)
**Purpose:** Comprehensive security documentation covering authentication, authorization, network security, and compliance.

**Key Topics:**
- AWS Cognito OAuth 2.0 authentication flow
- Email domain restrictions (@extremenetworks.com)
- Manual user provisioning by OCTO team
- Network isolation and zero-trust architecture
- Role-based access control (RBAC)
- Data protection (at rest and in transit)
- Logging and monitoring (OpenTelemetry stack)
- OWASP Top 10 mitigations
- Incident response procedures
- GDPR/CCPA compliance considerations
- Security hardening checklist

**Target Audience:** Security teams, compliance officers, security auditors

---

### 2. [ARCHITECTURE_DIAGRAM.md](./ARCHITECTURE_DIAGRAM.md)
**Purpose:** Detailed system architecture diagrams showing component relationships, network topology, and technology stack.

**Key Topics:**
- High-level system architecture (all layers)
- Network security zones (DMZ, trusted, data layers)
- Teams integration architecture
- Authentication flow diagrams
- Query processing pipeline
- Service communication patterns
- AWS deployment architecture
- Scaling considerations
- Disaster recovery procedures
- Technology stack summary

**Target Audience:** Infrastructure teams, DevOps engineers, solution architects

---

### 3. [DATA_FLOW.md](./DATA_FLOW.md)
**Purpose:** Comprehensive data flow documentation for security reviews and compliance audits.

**Key Topics:**
- Authentication data flows (OAuth 2.0)
- Query processing end-to-end flow
- Content ingestion pipeline (scraping → graph)
- Teams interface data flows
- User data management (what we collect/don't collect)
- External service integrations (Azure OpenAI, AWS Cognito, CloudFront)
- Data at rest (databases, backups, encryption)
- Data retention and deletion policies
- GDPR right to erasure procedures
- Data residency and cross-border transfers

**Target Audience:** Security teams, compliance officers, data protection officers

---

## Quick Reference

### Application Access Points

| URL | Purpose | Authentication |
|-----|---------|----------------|
| `https://d23ew7gbss3vnh.cloudfront.net/teams` | Teams interface (chat + feed) | AWS Cognito OAuth 2.0 |
| `https://d23ew7gbss3vnh.cloudfront.net` | Full application (web UI) | AWS Cognito OAuth 2.0 |
| `https://d23ew7gbss3vnh.cloudfront.net/visualisation` | Knowledge graph viewer | AWS Cognito OAuth 2.0 |

---

### Security Controls Summary

✅ **Authentication:**
- AWS Cognito User Pool (OAuth 2.0 + JWT)
- Email domain restriction (@extremenetworks.com)
- Manual user provisioning (OCTO team only)
- HTTP-only secure cookies (no JavaScript access)
- Automatic token refresh
- MFA available (configurable)

✅ **Authorization:**
- Role-based access control (user, admin, superadmin)
- Zero-trust internal architecture
- JWT validation on every request
- Trusted headers (X-User-Id, X-User-Email, X-User-Role)

✅ **Network Security:**
- CloudFront CDN with DDoS protection (AWS Shield)
- TLS 1.2+ enforcement
- Private Docker bridge network (aurora-network)
- Only ports 80/443 exposed to internet
- All databases/services internal only

✅ **Data Protection:**
- HTTPS/TLS for all client communication
- EBS volume encryption (optional, recommended)
- S3 backup encryption (AES-256)
- No passwords stored (managed by Cognito)
- Minimal PII (email only)

✅ **Monitoring:**
- OpenTelemetry stack (Tempo, Loki, Prometheus, Grafana)
- Security event logging
- Failed authentication tracking
- Rate limit monitoring
- Automated alerting

---

### User Management

**Provisioning Process:**
1. User requests access via OCTO team
2. OCTO team verifies @extremenetworks.com email
3. OCTO team creates user in AWS Cognito manually
4. User receives invitation email with temporary password
5. User must change password on first login
6. User gains access to Teams interface

**Deprovisioning Process:**
1. HR/Manager notifies OCTO team
2. OCTO team disables user in AWS Cognito (immediate)
3. User's sessions invalidated
4. After 30-day grace period, permanent deletion

**No Self-Registration:** Public sign-up disabled by design

---

### Infrastructure

**Hosting:**
- AWS EC2 instance (VPC subnet)
- Ubuntu 22.04 LTS
- Docker + Docker Compose
- EBS storage (100GB gp3, expandable)

**CDN:**
- AWS CloudFront distribution
- SSL/TLS via AWS Certificate Manager
- Global edge locations
- Origin: EC2 public IP

**Services:**
- **Frontend:** React 18 + TypeScript
- **Backend:** FastAPI (Python) microservices
- **Databases:** PostgreSQL 16, Neo4j 2025
- **Message Queue:** RabbitMQ 3.12
- **Cache:** Redis 7.2
- **Observability:** Grafana stack

---

### Data Classification

| Classification | Examples | Storage Location |
|----------------|----------|------------------|
| **Public** | Published documentation | Neo4j, public internet |
| **Internal** | User preferences, query history | PostgreSQL (EC2) |
| **Confidential** | Email addresses, JWT tokens | AWS Cognito, PostgreSQL |
| **Secrets** | API keys, database passwords | Environment variables |

---

### Compliance

**GDPR:**
- Right to access: Query history export available
- Right to erasure: Documented deletion procedure
- Right to portability: JSON export format
- Data minimization: Email + preferences only

**OWASP Top 10:**
- All mitigations documented in SECURITY_OVERVIEW.md
- Regular security updates via Docker images
- Input validation via FastAPI/Pydantic
- Parameterized database queries

**Data Retention:**
- Query history: 90 days
- Feedback: 1 year
- Backups: 30 days
- Logs: 30 days

---

### Contact Information

**OCTO Team (User Provisioning):**
- Responsible for: User account creation/deletion
- Email: [To be configured]

**System Administrator:**
- Responsible for: Infrastructure, deployment, updates
- Email: [To be configured]

**Security Team:**
- Responsible for: Security reviews, incident response
- Email: [To be configured]

---

## Security Review Checklist

Use this checklist when conducting security reviews:

**Authentication & Authorization:**
- [ ] Verify AWS Cognito configuration (email domain, MFA)
- [ ] Test OAuth 2.0 flow (authorization code + PKCE)
- [ ] Confirm JWT validation on all endpoints
- [ ] Verify role-based access control (RBAC)
- [ ] Test session timeout and token refresh

**Network Security:**
- [ ] Confirm only ports 80/443 exposed to internet
- [ ] Verify Docker network isolation
- [ ] Test rate limiting (Nginx)
- [ ] Confirm CloudFront origin access control
- [ ] Review security group rules (AWS)

**Data Protection:**
- [ ] Verify HTTPS enforcement (no HTTP allowed)
- [ ] Confirm HTTP-only secure cookies
- [ ] Test backup encryption (S3)
- [ ] Verify no sensitive data in logs
- [ ] Review data retention policies

**Monitoring & Logging:**
- [ ] Confirm security event logging enabled
- [ ] Test alerting for failed authentication
- [ ] Review Grafana dashboards
- [ ] Verify log retention (30 days)
- [ ] Test incident response procedures

**Compliance:**
- [ ] Verify GDPR right to erasure procedure
- [ ] Confirm data minimization (email only)
- [ ] Review privacy policy
- [ ] Test user data export
- [ ] Verify no third-party tracking

---

## Deployment Architecture

```
Internet Users (@extremenetworks.com)
         │
         │ HTTPS (443)
         ▼
    CloudFront CDN (AWS)
         │
         │ HTTPS (443)
         ▼
    Nginx Reverse Proxy (EC2)
         │
         │ HTTP (internal)
         ▼
    Auth Gateway Service (8000)
         │
         │ JWT validation
         │ X-User-* headers
         ▼
    ┌─────────────────────────────┐
    │   Backend Services          │
    │   • Backend API (8001)      │
    │   • Content Creator (8002)  │
    │   • Oracle (8003)           │
    │   • Retriever (8004)        │
    │   • Digester (8005)         │
    │   • Curator (8006)          │
    │   • Teams Agent (8007)      │
    │   • KG View (5173)          │
    └─────────────────────────────┘
         │
         ▼
    ┌─────────────────────────────┐
    │   Data Layer (Internal)     │
    │   • PostgreSQL (5432)       │
    │   • Neo4j (7474, 7687)      │
    │   • RabbitMQ (5672)         │
    │   • Redis (6379)            │
    └─────────────────────────────┘
```

---

## Technology Stack

| Layer | Technology | Version | Purpose |
|-------|-----------|---------|---------|
| **CDN** | AWS CloudFront | - | Content delivery, SSL/TLS |
| **Web Server** | Nginx | 1.24+ | Reverse proxy, rate limiting |
| **Auth Provider** | AWS Cognito | - | OAuth 2.0, JWT tokens |
| **Auth Gateway** | FastAPI | 0.115+ | Authentication proxy |
| **Backend** | FastAPI | 0.115+ | REST APIs |
| **Frontend** | React | 18.x | Teams UI, web UI |
| **Frontend Language** | TypeScript | 5.x | Type safety |
| **Database** | PostgreSQL | 16.x | User data, preferences |
| **Graph Database** | Neo4j | 2025 | Knowledge graph, vectors |
| **Message Queue** | RabbitMQ | 3.12+ | Async processing |
| **Cache** | Redis | 7.2+ | Rate limiting, sessions |
| **LLM** | Azure OpenAI | GPT-4o | Q&A, entity extraction |
| **Embeddings** | Azure OpenAI | text-embedding-3-large | Vector search |
| **Observability** | Grafana Stack | - | Logs, metrics, traces |
| **Orchestration** | Docker Compose | 2.x | Service management |
| **OS** | Ubuntu | 22.04 LTS | EC2 instance |

---

## Penetration Testing Scope

**In Scope:**
- Frontend application (all routes)
- Authentication endpoints (OAuth flow)
- API endpoints under `/api/*`
- Teams interface (`/teams`)
- Session management
- Input validation
- Authorization bypass attempts

**Out of Scope:**
- AWS Cognito service (managed by AWS)
- CloudFront infrastructure (managed by AWS)
- Internal services not exposed to internet
- Physical security of AWS data centers

**Recommended Tests:**
- OAuth 2.0 security (token theft, replay attacks, CSRF)
- JWT validation bypass attempts
- Session fixation and hijacking
- SQL injection (parameterized queries)
- XSS attacks (input validation)
- CSRF (state parameter validation)
- Rate limiting effectiveness
- Privilege escalation attempts

---

## Incident Response

**Detection:**
- Automated alerts for authentication anomalies
- Rate limit violations
- Failed authentication attempts (> 5 in 10 minutes)
- Unusual API usage patterns

**Response Procedure:**
1. **Isolate:** Stop affected services (`docker stop <service>`)
2. **Preserve:** Export logs for forensic analysis
3. **Notify:** Alert security team and stakeholders
4. **Investigate:** Analyze logs, identify root cause
5. **Mitigate:** Apply patches, update configurations
6. **Review:** Post-incident review, update procedures

**Emergency Contacts:**
- OCTO Team (user management)
- System Administrator (infrastructure)
- Security Team (incident response)

---

## Change Management

**Security-Related Changes:**
- All changes require security review
- Changes tracked in Git repository
- Automated dependency scanning (Dependabot)
- Regular security updates (quarterly)

**Deployment Process:**
1. Test in development environment
2. Security review (if applicable)
3. Deploy to production (off-hours)
4. Monitor for anomalies (24 hours)
5. Rollback procedure ready

---

## Disaster Recovery

**Backup Strategy:**
- PostgreSQL: Daily automated backups
- Neo4j: Weekly graph snapshots
- Configuration: Git repository (version controlled)
- Retention: 30 days (automatic deletion)

**Recovery Process:**
1. Provision new EC2 instance (or restore existing)
2. Restore Docker volumes from S3 backups
3. Start services via Docker Compose
4. Verify data integrity
5. Update CloudFront origin (if new EC2)

**RTO/RPO:**
- Recovery Time Objective (RTO): < 4 hours
- Recovery Point Objective (RPO): < 24 hours

---

## Scaling Considerations

**Current Capacity:**
- ~100 concurrent users
- ~500 queries/hour
- ~100 documents ingested/hour

**Bottlenecks:**
- Azure OpenAI API rate limits
- Single EC2 instance (no horizontal scaling)
- Database connections (PostgreSQL, Neo4j)

**Scaling Path:**
- Add Application Load Balancer
- Deploy multiple EC2 instances
- Migrate to RDS PostgreSQL (managed)
- Migrate to Neo4j AuraDB (managed)
- Implement ElastiCache (managed Redis)

---

## Questions for IT Teams

**Before Approving:**
1. Is MFA mandatory for all users?
2. What is the acceptable session timeout?
3. Are there geographic access restrictions?
4. What is the data retention policy?
5. Is penetration testing required?
6. What compliance frameworks apply (SOC 2, ISO 27001)?
7. Who should receive security alerts?
8. What is the expected incident response time?
9. Are there specific logging requirements?
10. Should we implement AWS WAF rules?

---

## Additional Resources

**External Documentation:**
- [AWS Cognito Best Practices](https://docs.aws.amazon.com/cognito/latest/developerguide/security.html)
- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [OAuth 2.0 Security Best Practices](https://datatracker.ietf.org/doc/html/draft-ietf-oauth-security-topics)
- [FastAPI Security](https://fastapi.tiangolo.com/tutorial/security/)
- [Neo4j Security](https://neo4j.com/docs/operations-manual/current/security/)

**Internal Documentation:**
- [Main Deployment Guide](../DEPLOYMENT.md)
- [Auth Integration Guide](../../auth/INTEGRATION_GUIDE.md)
- [Teams Integration Guide](../../TEAMS_INTEGRATION_GUIDE.md)
- [Pipeline Flow](../PIPELINE_FLOW.md)

---

## Document Control

**Review Schedule:**
- Frequency: Quarterly or after major system changes
- Next Review: 2026-06-09
- Owner: OCTO Team
- Approvers: IT Security Team, Infrastructure Team

**Change Log:**
- 2026-03-09: Initial version 1.0 (all documents)

---

## Support

For questions about this documentation or the Aurora system:

**Technical Questions:**
- Contact: System Administrator
- Email: [To be configured]

**Security Questions:**
- Contact: Security Team
- Email: [To be configured]

**User Access Questions:**
- Contact: OCTO Team
- Email: [To be configured]

---

**End of Document**

