# Third-Party Licenses and Dependencies

**Document Version:** 1.0  
**Last Updated:** January 5, 2026  
**Owner:** Extreme Networks, Inc.

This document catalogs all third-party dependencies used in the Aurora Knowledge Management System, their licenses, and associated compliance considerations for enterprise deployment.

---

## Executive Summary

### License Risk Assessment

| Risk Level | License Type | Components | Enterprise Impact |
|------------|--------------|------------|-------------------|
| 🔴 **CRITICAL** | GPLv3 (Strong Copyleft) | Neo4j Community Edition | **Requires commercial license purchase** before client deployment to avoid GPL obligations |
| 🟡 **MEDIUM** | AGPL-3.0 (Network Copyleft) | Grafana, Loki, Tempo | Observability tools only - can be removed or isolated for production |
| 🟢 **LOW** | MIT/Apache 2.0/BSD | 80+ Python/JS packages | Permissive licenses - safe for commercial use |
| 🟢 **LOW** | MPL 2.0 (Weak Copyleft) | RabbitMQ | Safe for use - file-level copyleft only |
| 🔵 **COMMERCIAL** | Proprietary/Pay-per-use | Azure OpenAI, AWS Cognito | Standard commercial services with clear ToS |

### Key Decisions & Mitigations

1. **Neo4j Community (GPLv3)**: Purchase Neo4j Enterprise licenses before production deployment
2. **Grafana Stack (AGPL)**: Observability stack is optional; can be removed or replaced with Apache 2.0 alternatives
3. **Sentence Transformers Model**: Use runtime download approach instead of Docker layer bundling to reduce image size (~1.5GB saved)
4. **All Application Code**: Assumed proprietary to Extreme Networks, Inc. (no LICENSE file currently exists - recommend adding)

---

## Infrastructure Dependencies (Docker Images)

### Database Systems

#### Neo4j Community Edition 🔴 **CRITICAL COPYLEFT RISK**
- **Image:** `neo4j:2025-community`
- **License:** GNU General Public License v3.0 (GPLv3)
- **Official License:** https://www.gnu.org/licenses/gpl-3.0.html
- **Risk Level:** 🔴 **CRITICAL** - Strong copyleft
- **Impact:** 
  - GPLv3 requires that any distributed software using Neo4j must also be licensed under GPLv3
  - If Aurora is distributed to clients/customers, entire codebase may need to be open-sourced
  - Network use may not trigger GPL obligations, but distribution does
- **Mitigation Strategy:**
  - ✅ **APPROVED:** Purchase Neo4j Enterprise licenses (~$18k+/year per server)
  - Alternative: Migrate to Apache 2.0 graph database (ArangoDB, JanusGraph)
- **Used By:** Backend, Digester, Curator, Neo4j-client library

#### PostgreSQL
- **Image:** `postgres:16-alpine`
- **License:** PostgreSQL License (BSD-like, very permissive)
- **Official License:** https://www.postgresql.org/about/licence/
- **Risk Level:** 🟢 **SAFE** - Permissive
- **Used By:** Backend, Auth, Retriever

### Message Queue & Cache

#### RabbitMQ
- **Image:** `rabbitmq:4.2.0-management-alpine`
- **License:** Mozilla Public License 2.0 (MPL 2.0)
- **Official License:** https://www.mozilla.org/en-US/MPL/2.0/
- **Risk Level:** 🟡 **LOW** - Weak copyleft (file-level only)
- **Impact:** Modifications to RabbitMQ source files must be disclosed; using RabbitMQ as-is is safe
- **Used By:** Retriever, Digester, Curator, rabbitmq-client library

#### Redis
- **Image:** `redis:7-alpine`
- **License:** BSD 3-Clause License
- **Official License:** https://redis.io/docs/about/license/
- **Risk Level:** 🟢 **SAFE** - Permissive
- **Used By:** Auth, Backend, Curator, Digester, Retriever

### Observability Stack 🟡 **AGPL NETWORK COPYLEFT**

#### Grafana
- **Image:** `grafana/grafana:10.2.3`
- **License:** GNU Affero General Public License v3.0 (AGPL-3.0)
- **Official License:** https://github.com/grafana/grafana/blob/main/LICENSE
- **Risk Level:** 🟡 **MEDIUM** - Network copyleft
- **Impact:** 
  - AGPL requires source disclosure even for SaaS/network use
  - Providing network access to Grafana dashboards may trigger AGPL obligations
- **Mitigation:** Observability is optional; can be removed for production or replaced with alternatives
- **Alternatives:** Prometheus + VictoriaMetrics (Apache 2.0)

#### Tempo
- **Image:** `grafana/tempo:2.3.1`
- **License:** AGPL-3.0
- **Risk Level:** 🟡 **MEDIUM** - Network copyleft
- **Mitigation:** Same as Grafana; optional component

#### Loki
- **Image:** `grafana/loki:2.9.3`
- **License:** AGPL-3.0
- **Risk Level:** 🟡 **MEDIUM** - Network copyleft
- **Mitigation:** Same as Grafana; optional component

#### Prometheus
- **Image:** `prom/prometheus:v2.48.1`
- **License:** Apache License 2.0
- **Risk Level:** 🟢 **SAFE** - Permissive

#### OpenTelemetry Collector
- **Image:** `otel/opentelemetry-collector-contrib:0.91.0`
- **License:** Apache License 2.0
- **Risk Level:** 🟢 **SAFE** - Permissive

### Base Images

#### Python
- **Images:** `python:3.11-slim`, `python:3.12-slim`, `python:3.13-slim`
- **License:** Python Software Foundation License (PSF)
- **Official License:** https://docs.python.org/3/license.html
- **Risk Level:** 🟢 **SAFE** - GPL-compatible, permissive
- **Used By:** All Python services (Auth, Backend, Curator, Digester, Retriever, Content Creator)

#### Node.js
- **Image:** `node:20-alpine`
- **License:** MIT License
- **Risk Level:** 🟢 **SAFE** - Permissive
- **Used By:** Frontend (build stage)

#### Nginx
- **Image:** `nginx:alpine`
- **License:** BSD 2-Clause License
- **Official License:** http://nginx.org/LICENSE
- **Risk Level:** 🟢 **SAFE** - Permissive
- **Used By:** Frontend (runtime)

---

## Python Dependencies

### Core Web Frameworks (All Services)

#### FastAPI
- **Version:** 0.104.1 - 0.115.0 (varies by service)
- **License:** MIT
- **PyPI:** https://pypi.org/project/fastapi/
- **Risk Level:** 🟢 **SAFE**

#### Uvicorn
- **Version:** 0.24.0 - 0.32.0
- **License:** BSD 3-Clause
- **Risk Level:** 🟢 **SAFE**

#### Pydantic
- **Version:** 2.9.2 - 2.10.0
- **License:** MIT
- **Risk Level:** 🟢 **SAFE**

### Azure OpenAI SDK 🔵 **COMMERCIAL SERVICE**

#### OpenAI Python Client
- **Version:** >=1.0.0
- **Package License:** Apache 2.0 (SDK itself)
- **Service License:** Commercial - Microsoft Azure OpenAI Service Terms
- **Official Terms:** https://azure.microsoft.com/en-us/support/legal/
- **Risk Level:** 🔵 **COMMERCIAL** - Requires valid Azure subscription and API keys
- **Cost:** Pay-per-use (token-based billing)
- **Data Privacy:** Subject to Azure data processing agreements
- **Used By:** Backend, Digester, Curator, Content Creator, neo4j-client

### Database Drivers

#### Neo4j Python Driver
- **Version:** >=5.26.0
- **License:** Apache 2.0 (driver itself)
- **Risk Level:** 🟢 **SAFE** - Driver is Apache 2.0; server is GPLv3 (see above)
- **Used By:** Backend, neo4j-client library

#### Psycopg2-binary (PostgreSQL)
- **Version:** >=2.9.0
- **License:** LGPL with exceptions (safe for dynamic linking)
- **Risk Level:** 🟢 **SAFE**
- **Used By:** Backend, Auth, Retriever

#### Redis-py
- **Version:** >=5.0.0
- **License:** MIT
- **Risk Level:** 🟢 **SAFE**
- **Used By:** Auth, Backend, Curator, Digester, Retriever

#### Pika (RabbitMQ)
- **Version:** >=1.3.0
- **License:** BSD 3-Clause
- **Risk Level:** 🟢 **SAFE**
- **Used By:** Digester, Curator, rabbitmq-client library

### Machine Learning & NLP

#### Sentence-Transformers 🔵 **MODEL LICENSING**
- **Version:** >=2.0.0
- **Package License:** Apache 2.0
- **Default Model:** `sentence-transformers/all-mpnet-base-v2`
- **Model License:** Apache 2.0 (see NOTICE file for full attribution)
- **Model Size:** ~420MB (compressed), ~1.5GB (uncompressed)
- **Training Data:** MS MARCO dataset (Microsoft, permissive)
- **Risk Level:** 🟢 **SAFE** - Apache 2.0 covers both code and models
- **Recommendation:** ✅ **APPROVED** - Use runtime download approach instead of Docker bundling
  - Reduces Docker image size by ~1.5GB
  - Allows model updates without rebuilding images
  - See NOTICE file for implementation details
- **Used By:** Digester, Curator, neo4j-client (optional)

#### Scikit-learn
- **Version:** >=1.3.0
- **License:** BSD 3-Clause (New BSD)
- **Risk Level:** 🟢 **SAFE**
- **Used By:** Curator (clustering)

#### NumPy
- **Version:** >=1.24.0
- **License:** BSD 3-Clause
- **Risk Level:** 🟢 **SAFE**
- **Used By:** Curator (numerical operations)

### Document Processing

#### PyPDF
- **Version:** >=3.9.0 / >=4.0.0 (varies)
- **License:** BSD 3-Clause
- **Risk Level:** 🟢 **SAFE**
- **Used By:** Retriever, Digester

#### python-docx
- **Version:** >=1.0.0 / >=1.1.0
- **License:** MIT
- **Risk Level:** 🟢 **SAFE**
- **Used By:** Retriever, Digester

#### python-pptx
- **Version:** >=0.6.23
- **License:** MIT
- **Risk Level:** 🟢 **SAFE**
- **Used By:** Retriever, Digester

#### openpyxl (Excel)
- **Version:** >=3.1.0
- **License:** MIT
- **Risk Level:** 🟢 **SAFE**
- **Used By:** Retriever

### Web Scraping

#### aiohttp
- **Version:** 3.13.2
- **License:** Apache 2.0
- **Risk Level:** 🟢 **SAFE**
- **Used By:** Retriever

#### BeautifulSoup4
- **Version:** 4.14.2
- **License:** MIT
- **Risk Level:** 🟢 **SAFE**
- **Used By:** Retriever

### Authentication & Security

#### python-jose[cryptography]
- **Version:** 3.3.0
- **License:** MIT
- **Risk Level:** 🟢 **SAFE**
- **Used By:** Auth service

#### httpx
- **Version:** 0.27.2
- **License:** BSD 3-Clause
- **Risk Level:** 🟢 **SAFE**
- **Used By:** Auth, Content Creator

#### slowapi (Rate Limiting)
- **Version:** 0.1.9
- **License:** MIT
- **Risk Level:** 🟢 **SAFE**
- **Used By:** Auth service

### OpenTelemetry (Observability)

#### opentelemetry-api
- **Version:** >=1.0.0 / >=1.20.0
- **License:** Apache 2.0
- **Risk Level:** 🟢 **SAFE**
- **Used By:** All services

#### opentelemetry-sdk
- **Version:** >=1.0.0 / >=1.20.0
- **License:** Apache 2.0
- **Risk Level:** 🟢 **SAFE**

#### opentelemetry-instrumentation-* (various)
- **License:** Apache 2.0
- **Risk Level:** 🟢 **SAFE**
- **Modules:** fastapi, httpx, redis, psycopg2, rabbitmq

### Utilities

#### python-dotenv
- **Version:** >=1.0.0
- **License:** BSD 3-Clause
- **Risk Level:** 🟢 **SAFE**

#### python-dateutil
- **Version:** >=2.8.2 / >=2.9.0
- **License:** Apache 2.0 / BSD Dual License
- **Risk Level:** 🟢 **SAFE**

#### APScheduler
- **Version:** >=3.10.0
- **License:** MIT
- **Risk Level:** 🟢 **SAFE**
- **Used By:** Curator (scheduled curation runs)

#### croniter
- **Version:** >=2.0.0
- **License:** MIT
- **Risk Level:** 🟢 **SAFE**
- **Used By:** Retriever (cron scheduling)

#### jellyfish (String Similarity)
- **Version:** >=1.0.0
- **License:** BSD 2-Clause
- **Risk Level:** 🟢 **SAFE**
- **Used By:** neo4j-client

### Testing (Dev Dependencies)

#### pytest
- **Version:** >=7.4.0
- **License:** MIT
- **Risk Level:** 🟢 **SAFE** (dev only)

#### pytest-asyncio
- **Version:** 0.21.1
- **License:** Apache 2.0
- **Risk Level:** 🟢 **SAFE** (dev only)

#### pytest-cov
- **Version:** >=4.1.0
- **License:** MIT
- **Risk Level:** 🟢 **SAFE** (dev only)

---

## JavaScript/Node.js Dependencies (Frontend)

### React Ecosystem

#### React & React-DOM
- **Version:** 18.2.0
- **License:** MIT
- **Risk Level:** 🟢 **SAFE**

#### React Router DOM
- **Version:** 6.20.0
- **License:** MIT
- **Risk Level:** 🟢 **SAFE**

#### React Scripts (Create React App)
- **Version:** 5.0.1
- **License:** MIT
- **Risk Level:** 🟢 **SAFE**

### Markdown Rendering

#### react-markdown
- **Version:** 9.0.1
- **License:** MIT
- **Risk Level:** 🟢 **SAFE**

#### remark-gfm (GitHub Flavored Markdown)
- **Version:** 4.0.0
- **License:** MIT
- **Risk Level:** 🟢 **SAFE**

### HTTP Client

#### Axios
- **Version:** 1.6.0
- **License:** MIT
- **Risk Level:** 🟢 **SAFE**

### Testing Libraries

#### @testing-library/react
- **Version:** 13.4.0
- **License:** MIT
- **Risk Level:** 🟢 **SAFE** (dev only)

#### @testing-library/jest-dom
- **Version:** 5.17.0
- **License:** MIT
- **Risk Level:** 🟢 **SAFE** (dev only)

#### @testing-library/user-event
- **Version:** 13.5.0
- **License:** MIT
- **Risk Level:** 🟢 **SAFE** (dev only)

---

## External Services (Commercial)

### Azure OpenAI Service
- **Provider:** Microsoft Corporation
- **Service Type:** Large Language Model API (GPT-4, embeddings)
- **License/Terms:** Microsoft Azure Terms of Service
- **Official Terms:** https://azure.microsoft.com/en-us/support/legal/
- **Cost Model:** Pay-per-use (token-based billing)
- **Data Processing:** Subject to Azure data processing agreements
- **Compliance:** SOC 2, ISO 27001, GDPR-compliant
- **Risk Level:** 🔵 **COMMERCIAL** - Requires valid subscription
- **Models Used:**
  - GPT-4o (deployment name configurable)
  - text-embedding-3-small (embeddings)
- **Usage:** LLM completions, query parsing, summarization, metadata extraction, embedding generation

### AWS Cognito
- **Provider:** Amazon Web Services, Inc.
- **Service Type:** User authentication and identity management
- **License/Terms:** AWS Customer Agreement
- **Official Terms:** https://aws.amazon.com/agreement/
- **Cost Model:** Pay-per-MAU (Monthly Active User)
- **Free Tier:** First 50,000 MAUs free, then $0.0055/MAU
- **Compliance:** SOC 1/2/3, ISO 27001, GDPR-compliant
- **Risk Level:** 🔵 **COMMERCIAL** - Requires AWS account
- **Usage:** OAuth2 authentication, JWT token management, user pool management

---

## Internal/Proprietary Libraries

### neo4j-client
- **Location:** `./neo4j-client/`
- **Declared License:** Proprietary (per README.md)
- **Copyright:** Assumed Extreme Networks, Inc.
- **Risk Level:** 🟢 **INTERNAL** - Owned by organization
- **Recommendation:** Add formal copyright header and license file

### rabbitmq-client
- **Location:** `./rabbitmq-client/`
- **Declared License:** Proprietary (per README.md)
- **Copyright:** Assumed Extreme Networks, Inc.
- **Risk Level:** 🟢 **INTERNAL** - Owned by organization
- **Recommendation:** Add formal copyright header and license file

### common/ (Shared Utilities)
- **Location:** `./common/`
- **Declared License:** None (no LICENSE file)
- **Copyright:** Assumed Extreme Networks, Inc.
- **Risk Level:** 🟢 **INTERNAL** - Owned by organization
- **Includes:** auth_middleware.py, llm_instrumentation.py, telemetry.py, make-utils.mk
- **Recommendation:** Add copyright headers to all source files

---

## License Compliance Checklist

### Before Production Deployment

- [ ] **CRITICAL:** Purchase Neo4j Enterprise licenses (contact Neo4j sales)
- [ ] **CRITICAL:** Add LICENSE file to repository root (recommend Apache 2.0 or Proprietary)
- [ ] **HIGH:** Add copyright headers to all source files: `© 2025-2026 Extreme Networks, Inc.`
- [ ] **HIGH:** Implement Sentence Transformers runtime download approach (see NOTICE file)
- [ ] **MEDIUM:** Review Grafana stack usage - remove or isolate if providing external network access
- [ ] **MEDIUM:** Create NOTICE file with all third-party attributions (especially Sentence Transformers model)
- [ ] **LOW:** Document Azure OpenAI data processing agreement for compliance team
- [ ] **LOW:** Document AWS Cognito setup and user data handling for compliance team
- [ ] **LOW:** Run `pip-audit` and `npm audit` for CVE scanning before deployment

### Ongoing Maintenance

- [ ] Review dependency updates for license changes (especially copyleft introductions)
- [ ] Monitor Neo4j Enterprise license renewal dates
- [ ] Track Azure OpenAI and AWS Cognito usage costs
- [ ] Keep this document updated with new dependencies

---

## Recommendations

### Immediate Actions (Before Client Deployment)

1. **Neo4j Licensing (CRITICAL)**
   - Contact Neo4j sales: https://neo4j.com/contact-us/
   - Request quote for Enterprise licenses based on deployment scale
   - Budget: ~$18,000+/year per production server
   - Timeline: Allow 2-4 weeks for procurement

2. **Add Project License (HIGH)**
   - Decision needed: Apache 2.0, MIT, or Proprietary
   - If Proprietary: "© 2025-2026 Extreme Networks, Inc. All Rights Reserved. Proprietary and Confidential."
   - Add LICENSE file to repository root
   - Add copyright headers to all `.py`, `.js`, `.ts` files

3. **Sentence Transformers Optimization (MEDIUM)**
   - Implement runtime model download (details in NOTICE file)
   - Remove `RUN python -c "from sentence_transformers..."` from Dockerfiles
   - Reduces image size from ~3.5GB to ~2GB
   - Improves image build/push times

### Future Considerations

1. **Grafana Stack Alternatives**
   - If AGPL is concern, consider:
     - VictoriaMetrics (Apache 2.0) instead of Grafana
     - Jaeger (Apache 2.0) instead of Tempo
     - Elasticsearch Stack (Elastic License v2) instead of Loki
   - Cost: ~1-2 weeks engineering effort for migration

2. **Neo4j Alternatives (Long-term)**
   - If licensing costs become prohibitive:
     - ArangoDB (Apache 2.0, multi-model database)
     - JanusGraph (Apache 2.0, distributed graph DB)
   - Cost: ~4-6 weeks engineering effort + testing

---

## Questions or Concerns?

For questions about this document or licensing concerns, contact:
- **Legal/Compliance Team:** [Add contact]
- **Engineering Lead:** [Add contact]
- **Document Owner:** [Add contact]

---

**Document History:**
- v1.0 (2026-01-05): Initial comprehensive dependency audit
