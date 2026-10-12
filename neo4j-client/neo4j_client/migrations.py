"""Neo4j database migrations for knowledge graph schema enhancements."""

import logging
from typing import Dict, Any, Optional
from neo4j import Session

logger = logging.getLogger(__name__)


class Migrations:
    """Handle Neo4j schema migrations."""

    @staticmethod
    def run_all(session: Session, database: str = "neo4j") -> bool:
        """
        Run all pending migrations.
        
        Args:
            session: Neo4j session
            database: Database name
            
        Returns:
            True if all migrations succeeded, False otherwise
        """
        migrations = [
            Migrations.add_tier_to_topics,
            Migrations.add_importance_to_nodes,
            Migrations.add_ietf_datasources,
            Migrations.add_wba_newsroom_datasource,
            Migrations.backfill_doc_type,
            Migrations.backfill_datasource_metadata,
            Migrations.backfill_resource_domains,
            Migrations.fix_wba_subdatasource_types,
            Migrations.add_ieee802_datasources,
            Migrations.add_mef_datasources,
            Migrations.add_nist_datasources,
            Migrations.add_onf_datasources,
            Migrations.add_dmtf_datasources,
            Migrations.add_datasource_parent_index,
            Migrations.add_wba_extranet_root_datasource,
            Migrations.fix_wba_extranet_child_scraper_type,
            Migrations.add_techfieldday_datasources,
            Migrations.add_wfa_root_datasource_hierarchy,
        ]
        
        for migration_func in migrations:
            try:
                if not migration_func(session):
                    logger.error(f"Migration {migration_func.__name__} failed")
                    return False
            except Exception as e:
                logger.error(f"Error running migration {migration_func.__name__}: {e}")
                return False
        
        return True

    @staticmethod
    def add_tier_to_topics(session: Session) -> bool:
        """
        Add tier property to Topic nodes (0 = root, 1 = major, 2 = leaf).
        
        Idempotent - only updates topics WHERE tier IS NULL.
        """
        try:
            # Tier 0: Topics with no parent
            query_tier_0 = """
            MATCH (t:Topic)
            WHERE t.tier IS NULL
                AND NOT EXISTS ((t)<-[:ENCOMPASSES]-(:Topic))
            SET t.tier = 0
            RETURN COUNT(t) as updated
            """
            result = session.run(query_tier_0)
            record = result.single()
            count_0 = record["updated"] if record else 0
            logger.info(f"Set tier=0 for {count_0} root topics")
            
            # Tier 1: Topics with parent but no grandparent
            query_tier_1 = """
            MATCH (t:Topic)<-[:ENCOMPASSES]-(parent:Topic)
            WHERE t.tier IS NULL
                AND NOT EXISTS ((parent)<-[:ENCOMPASSES]-(:Topic))
            SET t.tier = 1
            RETURN COUNT(t) as updated
            """
            result = session.run(query_tier_1)
            record = result.single()
            count_1 = record["updated"] if record else 0
            logger.info(f"Set tier=1 for {count_1} major topics")
            
            # Tier 2: All remaining topics (leaf/nested)
            query_tier_2 = """
            MATCH (t:Topic)
            WHERE t.tier IS NULL
            SET t.tier = 2
            RETURN COUNT(t) as updated
            """
            result = session.run(query_tier_2)
            record = result.single()
            count_2 = record["updated"] if record else 0
            logger.info(f"Set tier=2 for {count_2} leaf topics")
            
            # Verify
            query_verify = """
            MATCH (t:Topic)
            WHERE t.tier IS NOT NULL
            RETURN COUNT(t) as total
            """
            result = session.run(query_verify)
            record = result.single()
            total = record["total"] if record else 0
            logger.info(f"Total topics with tier property: {total}")
            
            return True
            
        except Exception as e:
            logger.error(f"Error adding tier to topics: {e}")
            return False

    @staticmethod
    def add_importance_to_nodes(session: Session) -> bool:
        """
        Add importance property to nodes based on inbound relationship count.
        
        Importance = COUNT(inbound_rels) / 100 (clamped 0-1)
        Idempotent - only updates nodes WHERE importance IS NULL.
        """
        try:
            # Add importance to Topics (based on resources that discuss them)
            query_topics = """
            MATCH (t:Topic)
            WHERE t.importance IS NULL
            WITH t, SIZE([(r:Resource)-[:DISCUSSES]->(t) | r]) as rel_count
            WITH t, rel_count,
                 CASE 
                     WHEN rel_count = 0 THEN 0.0
                     WHEN rel_count > 100 THEN 1.0
                     ELSE ROUND(rel_count / 100.0, 2)
                 END as importance_value
            SET t.importance = importance_value
            RETURN COUNT(t) as updated, ROUND(AVG(importance_value), 2) as avg_importance
            """
            result = session.run(query_topics)
            record = result.single()
            if record:
                logger.info(f"Added importance to {record['updated']} topics, avg={record['avg_importance']}")
            
            # Add importance to Organizations
            query_orgs = """
            MATCH (o:Organization)
            WHERE o.importance IS NULL
            WITH o, SIZE([(r:Resource)-[:PUBLISHED_BY]->(o) | r]) as rel_count
            WITH o, rel_count,
                 CASE 
                     WHEN rel_count = 0 THEN 0.0
                     WHEN rel_count > 100 THEN 1.0
                     ELSE ROUND(rel_count / 100.0, 2)
                 END as importance_value
            SET o.importance = importance_value
            RETURN COUNT(o) as updated
            """
            result = session.run(query_orgs)
            record = result.single()
            if record:
                logger.info(f"Added importance to {record['updated']} organizations")
            
            # Add importance to Persons
            query_persons = """
            MATCH (p:Person)
            WHERE p.importance IS NULL
            WITH p, SIZE([(r:Resource)-[:AUTHORED_BY]->(p) | r]) as rel_count
            WITH p, rel_count,
                 CASE 
                     WHEN rel_count = 0 THEN 0.0
                     WHEN rel_count > 100 THEN 1.0
                     ELSE ROUND(rel_count / 100.0, 2)
                 END as importance_value
            SET p.importance = importance_value
            RETURN COUNT(p) as updated
            """
            result = session.run(query_persons)
            record = result.single()
            if record:
                logger.info(f"Added importance to {record['updated']} persons")
            
            # Verify
            query_verify = """
            MATCH (n)
            WHERE n.importance IS NOT NULL
            RETURN COUNT(n) as total, 
                   ROUND(AVG(n.importance), 2) as avg_importance,
                   MIN(n.importance) as min_importance,
                   MAX(n.importance) as max_importance
            """
            result = session.run(query_verify)
            record = result.single()
            if record:
                logger.info(f"Importance stats: {record['total']} nodes, avg={record['avg_importance']}, "
                           f"min={record['min_importance']}, max={record['max_importance']}")
            
            return True
            
        except Exception as e:
            logger.error(f"Error adding importance to nodes: {e}")
            return False

    @staticmethod
    def add_ietf_datasources(session: Session) -> bool:
        """
        Upsert IETF Blog and IETF Datatracker DataSource nodes.

        Idempotent — uses MERGE so it is safe to run on every startup.
        These nodes are defined in initial_data.json but are skipped when
        base data already exists (organisations present). This migration
        ensures they are always present regardless of when the service was
        first initialised.
        """
        try:
            datasources = [
                {
                    "datasource_id": "ietf_blog",
                    "name": "IETF Blog",
                    "display_name": "IETF",
                    "org_id": "ietf",
                    "source_type": "scraped_webpage",
                    "fetch_url": "https://www.ietf.org/blog/",
                    "has_events": False,
                    "scraper_type": "ietf_blog",
                    "resource_url": "/blog/",
                    "scrape_schedule": "0 6 * * *",
                    "run_on_startup": False,
                    "check_content_hash": True,
                    "publish_weight": 1.0,
                    "update_weight": 0.8,
                    "event_weight": 0.7,
                    "temporal_extraction_days": 90,
                    "scraper_delay": 1.0,
                    "max_resources": 100,
                    "max_redirects": 5,
                    "discovery_mode": "incremental",
                    "consecutive_duplicates_limit": 5,
                    "description": "IETF public blog — news, announcements and IETF meeting previews",
                },
                {
                    "datasource_id": "ietf_datatracker_api",
                    "name": "IETF Datatracker",
                    "display_name": "IETF Datatracker",
                    "org_id": "ietf",
                    "source_type": "scraped_webpage",
                    "fetch_url": "https://datatracker.ietf.org/",
                    "has_events": True,
                    "scraper_type": "ietf_datatracker",
                    "resource_url": "/",
                    "scrape_schedule": "0 4 * * *",
                    "run_on_startup": False,
                    "check_content_hash": True,
                    "publish_weight": 1.0,
                    "update_weight": 0.9,
                    "event_weight": 1.0,
                    "temporal_extraction_days": 180,
                    "scraper_delay": 1.0,
                    "max_resources": -1,
                    "max_redirects": 5,
                    "discovery_mode": "incremental",
                    "consecutive_duplicates_limit": 0,
                    "description": "IETF Datatracker — internet-drafts, RFCs and meeting sessions for selected areas and working groups",
                    "folders": ["area:wit", "area:int", "area:rtg", "area:sec"],
                },
            ]

            for ds in datasources:
                folders = ds.pop("folders", None)
                query = """
                MERGE (d:DataSource {datasource_id: $datasource_id})
                ON CREATE SET
                    d.name                        = $name,
                    d.display_name                = $display_name,
                    d.org_id                      = $org_id,
                    d.source_type                 = $source_type,
                    d.fetch_url                   = $fetch_url,
                    d.has_events                  = $has_events,
                    d.scraper_type                = $scraper_type,
                    d.resource_url                = $resource_url,
                    d.scrape_schedule             = $scrape_schedule,
                    d.run_on_startup              = $run_on_startup,
                    d.check_content_hash          = $check_content_hash,
                    d.publish_weight              = $publish_weight,
                    d.update_weight               = $update_weight,
                    d.event_weight                = $event_weight,
                    d.temporal_extraction_days    = $temporal_extraction_days,
                    d.scraper_delay               = $scraper_delay,
                    d.max_resources               = $max_resources,
                    d.max_redirects               = $max_redirects,
                    d.discovery_mode              = $discovery_mode,
                    d.consecutive_duplicates_limit= $consecutive_duplicates_limit,
                    d.description                 = $description
                ON MATCH SET
                    d.display_name                = $display_name,
                    d.description                 = $description
                RETURN d.datasource_id as id, (d.name IS NOT NULL) as existed
                """
                result = session.run(query, **ds)
                record = result.single()
                if record:
                    action = "updated" if record["existed"] else "created"
                    logger.info(f"IETF datasource '{record['id']}' {action}")

                # Always ensure folders is set for ietf_datatracker_api
                if folders is not None:
                    session.run(
                        """
                        MATCH (d:DataSource {datasource_id: $datasource_id})
                        WHERE d.folders IS NULL OR size(d.folders) = 0
                        SET d.folders = $folders
                        """,
                        datasource_id=ds["datasource_id"],
                        folders=folders,
                    )
                    logger.info(f"Set folders on '{ds['datasource_id']}': {folders}")

            return True

        except Exception as e:
            logger.error(f"Error upserting IETF datasources: {e}")
            return False

    @staticmethod
    def add_wba_newsroom_datasource(session: Session) -> bool:
        """
        Upsert a WBA Newsroom DataSource node.

        The WBA newsroom (wballiance.com/newsroom/) is a WordPress blog
        containing press releases, partner spotlights, and trial reports.
        It is separate from the /resources/ section and was previously not
        scraped.  This migration ensures the datasource is present so the
        retriever will scrape it on its next scheduled run.

        Idempotent — uses MERGE on datasource_id.
        """
        try:
            ds = {
                "datasource_id": "wba_newsroom",
                "name": "WBA Newsroom",
                "display_name": "WBA Newsroom",
                "org_id": "wba",
                "source_type": "scraped_webpage",
                "fetch_url": "https://wballiance.com/newsroom/",
                "has_events": False,
                "scraper_type": "wba",
                "resource_url": "/newsroom/",
                "scrape_schedule": "0 7 * * *",
                "run_on_startup": False,
                "check_content_hash": True,
                "publish_weight": 1.0,
                "update_weight": 0.9,
                "event_weight": 0.7,
                "temporal_extraction_days": 90,
                "scraper_delay": 1.0,
                "max_resources": 200,
                "max_redirects": 5,
                "discovery_mode": "incremental",
                "consecutive_duplicates_limit": 5,
                "description": "WBA Newsroom — press releases, partner spotlights and field trial reports",
            }

            query = """
            MERGE (d:DataSource {datasource_id: $datasource_id})
            ON CREATE SET
                d.name                        = $name,
                d.display_name                = $display_name,
                d.org_id                      = $org_id,
                d.source_type                 = $source_type,
                d.fetch_url                   = $fetch_url,
                d.has_events                  = $has_events,
                d.scraper_type                = $scraper_type,
                d.resource_url                = $resource_url,
                d.scrape_schedule             = $scrape_schedule,
                d.run_on_startup              = $run_on_startup,
                d.check_content_hash          = $check_content_hash,
                d.publish_weight              = $publish_weight,
                d.update_weight               = $update_weight,
                d.event_weight                = $event_weight,
                d.temporal_extraction_days    = $temporal_extraction_days,
                d.scraper_delay               = $scraper_delay,
                d.max_resources               = $max_resources,
                d.max_redirects               = $max_redirects,
                d.discovery_mode              = $discovery_mode,
                d.consecutive_duplicates_limit= $consecutive_duplicates_limit,
                d.description                 = $description
            ON MATCH SET
                d.display_name                = $display_name,
                d.description                 = $description
            RETURN d.datasource_id as id, (d.name IS NOT NULL) as existed
            """
            result = session.run(query, **ds)
            record = result.single()
            if record:
                action = "updated" if record["existed"] else "created"
                logger.info(f"WBA Newsroom datasource '{record['id']}' {action}")

            return True

        except Exception as e:
            logger.error(f"Error upserting WBA Newsroom datasource: {e}")
            return False

    @staticmethod
    def backfill_doc_type(session: Session) -> bool:
        """
        Backfill doc_type for all Resource nodes where doc_type is NULL or 'unknown'.

        Uses rule-based mapping from datasource_id and category fields — the fast,
        safe cases that don't need LLM inference. Only touches resources where
        doc_type IS NULL or = 'unknown' so it is safe to run repeatedly.

        Idempotent — WHERE clause limits to uncategorised resources only.
        """
        try:
            query = """
            MATCH (r:Resource)
            WHERE r.doc_type IS NULL OR toLower(r.doc_type) = 'unknown'
            SET r.doc_type = CASE
                WHEN r.datasource_id STARTS WITH 'youtube'
                    THEN 'video-transcript'
                WHEN toLower(r.category) IN ['video', 'videos']
                    THEN 'video-transcript'
                WHEN toLower(r.category) IN ['podcast', 'podcasts']
                    THEN 'video-transcript'
                WHEN toLower(r.category) IN ['wba tv']
                    THEN 'video-transcript'
                WHEN toLower(r.category) IN ['brochure', 'brochures']
                    THEN 'whitepaper'
                WHEN toLower(r.category) IN [
                    'root', 'rg meetings & documents',
                    'meeting documents', 'meeting & documents'
                ]
                    THEN 'meeting-minutes'
                WHEN toLower(r.category) IN ['internet-draft', 'internet draft']
                    THEN 'internet-draft'
                WHEN toLower(r.category) IN ['blog', 'blogs']
                    THEN 'blog'
                WHEN toLower(r.category) IN ['newsletter', 'newsletters', 'highlights']
                    THEN 'newsletter'
                WHEN toLower(r.category) IN [
                    'agendas & meeting documents', 'agenda', 'agendas', 'meeting agenda'
                ]
                    THEN 'agenda'
                WHEN toLower(r.category) IN [
                    'attendance & minutes', 'meeting minutes',
                    'minutes & attendance', 'minutes'
                ]
                    THEN 'meeting-minutes'
                WHEN toLower(r.category) IN ['press release', 'press releases']
                    THEN 'press-release'
                WHEN toLower(r.category) IN [
                    'case studies and articles', 'case study', 'case studies'
                ]
                    THEN 'case-study'
                WHEN toLower(r.category) IN [
                    'specification', 'specifications',
                    'specifications & guidelines', 'technical specification'
                ]
                    THEN 'specification'
                WHEN toLower(r.category) IN [
                    'paper', 'white paper', 'whitepaper',
                    'wba white papers', 'white papers'
                ]
                    THEN 'whitepaper'
                WHEN toLower(r.category) IN ['presentation', 'presentations', 'slides']
                    THEN 'presentation'
                WHEN toLower(r.category) IN [
                    'governing document', 'governing documents', 'policy'
                ]
                    THEN 'governing-document'
                WHEN toLower(r.category) IN ['infographic', 'infographics']
                    THEN 'infographic'
                ELSE 'unknown'
            END
            RETURN count(r) AS updated
            """
            result = session.run(query)
            record = result.single()
            if record:
                logger.info(f"backfill_doc_type: updated {record['updated']} Resource nodes")

            # Log how many still remain unknown after rule-based pass
            check = session.run(
                "MATCH (r:Resource) WHERE toLower(r.doc_type) = 'unknown' RETURN count(r) AS remaining"
            )
            check_record = check.single()
            if check_record:
                logger.info(
                    f"backfill_doc_type: {check_record['remaining']} resources still 'unknown' "
                    f"(LLM re-classification needed for these)"
                )

            return True

        except Exception as e:
            logger.error(f"Error in backfill_doc_type migration: {e}")
            return False

    @staticmethod
    def backfill_datasource_metadata(session: Session) -> bool:
        """
        Populate DataSource nodes with id, type, and enabled fields.

        All 109 DataSource nodes previously had NULL for these fields, which
        prevents datasource-level filtering in oracle queries.

        Idempotent — only updates nodes WHERE id IS NULL.
        """
        try:
            query = """
            MATCH (d:DataSource)
            WHERE d.id IS NULL
            SET
                d.id      = d.datasource_id,
                d.enabled = true,
                d.type    = CASE
                    WHEN d.datasource_id STARTS WITH 'wfa_'    THEN 'official'
                    WHEN d.datasource_id STARTS WITH 'wba_'    THEN 'industry'
                    WHEN d.datasource_id STARTS WITH 'ietf_'   THEN 'standards'
                    WHEN d.datasource_id STARTS WITH '3gpp_'   THEN 'standards'
                    WHEN d.datasource_id STARTS WITH 'ieee_'   THEN 'standards'
                    WHEN d.datasource_id STARTS WITH 'youtube' THEN 'video'
                    WHEN d.datasource_id IN ['manual_upload', 'default'] THEN 'manual'
                    ELSE 'public'
                END
            RETURN count(d) AS updated
            """
            result = session.run(query)
            record = result.single()
            if record:
                logger.info(f"backfill_datasource_metadata: updated {record['updated']} DataSource nodes")
            return True

        except Exception as e:
            logger.error(f"Error in backfill_datasource_metadata migration: {e}")
            return False

    @staticmethod
    def backfill_resource_domains(session: Session) -> bool:
        """
        Tag Resource nodes with r.domains[] — the networking domain(s) each
        resource belongs to.

        Domain taxonomy (for Extreme Networks enterprise context):
            wi-fi               Wi-Fi / 802.11 / WLAN
            wired               Ethernet, switching, wired LAN
            routing             BGP, OSPF, IS-IS, MPLS, SR, routing protocols
            security            TLS, PKI, zero-trust, auth, cryptography
            transport           TCP, QUIC, UDP, HTTP transport layer
            cloud               SD-WAN, cloud networking, virtualization, DC
            iot                 IoT, constrained devices, 6LoWPAN, LPWAN
            video-audio         Video/audio streaming, media protocols
            wireless-broadband  WBA content, broadband wireless

        Assignment is datasource-first (most reliable signal), with
        doc_type as a secondary signal for video content.

        Idempotent — only updates resources WHERE domains IS NULL OR domains = [].
        """
        try:
            query = """
            MATCH (r:Resource)
            WHERE r.domains IS NULL OR size(r.domains) = 0
            SET r.domains = CASE
                // Wi-Fi Alliance official sources
                WHEN r.datasource_id STARTS WITH 'wfa_'
                    THEN ['wi-fi']

                // WBA (Wireless Broadband Alliance) — wireless + broadband
                WHEN r.datasource_id STARTS WITH 'wba_'
                    THEN ['wi-fi', 'wireless-broadband']

                // 3GPP — cellular / mobile networking
                WHEN r.datasource_id STARTS WITH '3gpp_'
                    THEN ['wireless-broadband']

                // IEEE (802.1, 802.3, 802.11 etc) — wired + wi-fi
                WHEN r.datasource_id STARTS WITH 'ieee_'
                    THEN ['wi-fi', 'wired']

                // YouTube videos — general (could be any domain, indexed per-video)
                WHEN r.datasource_id STARTS WITH 'youtube'
                    THEN ['general']

                // IETF Routing Area working groups
                WHEN r.datasource_id IN [
                    'ietf_wg_idr',    // BGP
                    'ietf_wg_lsr',    // Link-State Routing
                    'ietf_wg_bess',   // BGP-Enabled Services
                    'ietf_wg_pce',    // Path Computation
                    'ietf_wg_teas',   // Traffic Engineering
                    'ietf_wg_mpls',   // MPLS
                    'ietf_wg_spring', // SR/SPRING
                    'ietf_wg_lsvr',   // Link-State Vector Routing
                    'ietf_wg_bfd',    // BFD
                    'ietf_wg_lisp',   // LISP
                    'ietf_wg_nvo3',   // Network Virtualisation
                    'ietf_wg_pim',    // PIM Multicast
                    'ietf_wg_bier',   // BIER
                    'ietf_wg_detnet', // DetNet
                    'ietf_wg_cats',   // CATS
                    'ietf_wg_manet',  // MANET
                    'ietf_wg_rtgwg',  // Routing WG
                    'ietf_wg_babel',  // Babel routing
                    'ietf_wg_ospf',   // OSPF
                    'ietf_wg_isis'    // IS-IS
                ]
                    THEN ['routing']

                // IETF Security Area
                WHEN r.datasource_id IN [
                    'ietf_wg_tls',      // TLS
                    'ietf_wg_ipsecme',  // IPsec
                    'ietf_wg_kitten',   // GSSAPI/Kerberos
                    'ietf_wg_jose',     // JSON Object Signing
                    'ietf_wg_oauth',    // OAuth
                    'ietf_wg_acme',     // ACME cert provisioning
                    'ietf_wg_lamps',    // PKI/CMS
                    'ietf_wg_mls',      // Messaging Layer Security
                    'ietf_wg_ace',      // ACE for IoT
                    'ietf_wg_lake',     // Lightweight Auth
                    'ietf_wg_cose',     // CBOR Object Signing
                    'ietf_wg_keytrans', // Key Transparency
                    'ietf_wg_dance',    // DNS Auth
                    'ietf_wg_openpgp',  // OpenPGP
                    'ietf_wg_hpke',     // HPKE
                    'ietf_wg_saag',     // Security Area Advisory
                    'ietf_wg_emu',      // EAP methods
                    'ietf_wg_rats'      // Remote Attestation
                ]
                    THEN ['security']

                // IETF Transport / Application
                WHEN r.datasource_id IN [
                    'ietf_wg_quic',    // QUIC
                    'ietf_wg_tcpm',    // TCP
                    'ietf_wg_httpbis', // HTTP
                    'ietf_wg_httpapi', // HTTP APIs
                    'ietf_wg_masque',  // MASQUE / proxying
                    'ietf_wg_ccwg',    // Congestion Control
                    'ietf_wg_moq',     // Media over QUIC
                    'ietf_wg_webtrans',// WebTransport
                    'ietf_wg_tsvwg'    // Transport Area WG
                ]
                    THEN ['transport']

                // IETF IoT / Constrained Devices
                WHEN r.datasource_id IN [
                    'ietf_wg_6lo',   // 6LoWPAN
                    'ietf_wg_6man',  // IPv6 maintenance
                    'ietf_wg_core',  // CoAP / constrained REST
                    'ietf_wg_dult',  // Detecting Unwanted Location Trackers
                    'ietf_wg_asdf',  // Semantic Definition Format
                    'ietf_wg_iotops' // IoT Operations
                ]
                    THEN ['iot']

                // IETF Media / Video-Audio
                WHEN r.datasource_id IN [
                    'ietf_wg_avtcore', // Audio/Video Transport Core
                    'ietf_wg_mmusic',  // Multiparty Multimedia
                    'ietf_wg_payload'  // RTP payload formats
                ]
                    THEN ['video-audio']

                // IETF Infrastructure (DNS, DHCP, NTP etc)
                WHEN r.datasource_id IN [
                    'ietf_wg_ntp',   // NTP
                    'ietf_wg_dhc',   // DHCP
                    'ietf_wg_dnssd', // DNS-SD
                    'ietf_wg_add',   // Adaptive DNS Discovery
                    'ietf_wg_dnsop'  // DNS Operations
                ]
                    THEN ['routing']  // closest to infrastructure/routing

                // Blog and general IETF sources — general networking
                WHEN r.datasource_id IN ['ietf_blog', 'ietf_datatracker_api']
                    THEN ['routing', 'security', 'transport']

                // Manual uploads and unknowns — leave for per-resource tagging
                ELSE ['general']
            END
            RETURN count(r) AS updated
            """
            result = session.run(query)
            record = result.single()
            if record:
                logger.info(f"backfill_resource_domains: tagged {record['updated']} Resource nodes")
            return True

        except Exception as e:
            logger.error(f"Error in backfill_resource_domains migration: {e}")
            return False

    @staticmethod
    def fix_wba_subdatasource_types(session: Session) -> bool:
        """
        Fix WBA sub-datasource nodes that were created via the Admin UI without
        source_type, scraper_type, or fetch_url — making them invisible in the
        sources preferences list and unscrappable.

        Idempotent: only sets fields that are currently NULL/empty.
        """
        try:
            result = session.run("""
                MATCH (d:DataSource)
                WHERE d.datasource_id IN [
                    'wba_case_studies', 'wba_industry_reports',
                    'wba_presentations', 'wba_specifications', 'wba_whitepapers'
                ]
                SET d.source_type  = coalesce(d.source_type,  'scraped_webpage'),
                    d.scraper_type = coalesce(d.scraper_type, 'wba'),
                    d.fetch_url    = CASE WHEN d.fetch_url IS NULL OR d.fetch_url = ''
                                         THEN 'https://wballiance.com/resources/'
                                         ELSE d.fetch_url END,
                    d.resource_url = coalesce(d.resource_url, '/resources/'),
                    d.category_filter = CASE d.datasource_id
                        WHEN 'wba_case_studies'     THEN coalesce(d.category_filter, 'case study')
                        WHEN 'wba_industry_reports' THEN coalesce(d.category_filter, 'industry report')
                        WHEN 'wba_presentations'    THEN coalesce(d.category_filter, 'presentation')
                        WHEN 'wba_specifications'   THEN coalesce(d.category_filter, 'specifications')
                        WHEN 'wba_whitepapers'      THEN coalesce(d.category_filter, 'whitepaper')
                        ELSE d.category_filter
                    END
                RETURN count(d) AS updated
            """)
            record = result.single()
            updated = record["updated"] if record else 0
            logger.info(f"fix_wba_subdatasource_types: patched {updated} WBA sub-datasource nodes")
            return True
        except Exception as e:
            logger.error(f"Error in fix_wba_subdatasource_types migration: {e}")
            return False

    # ------------------------------------------------------------------
    # IEEE 802 datasource migrations
    # ------------------------------------------------------------------

    @staticmethod
    def add_ieee802_datasources(session: Session) -> bool:
        """
        Upsert DataSource nodes for IEEE 802 working groups.

        Three datasources:
          ieee802_11  —  802.11 / Wi-Fi working group
          ieee802_1   —  802.1 Bridging & Security
          ieee802_3   —  802.3 Ethernet

        Idempotent — uses MERGE on datasource_id.
        """
        datasources = [
            {
                "datasource_id": "ieee802_11",
                "name": "IEEE 802.11 Working Group",
                "display_name": "IEEE 802.11 (Wi-Fi)",
                "org_id": "ieee",
                "source_type": "scraped_webpage",
                "fetch_url": "https://www.ieee802.org/11/",
                "has_events": False,
                "scraper_type": "ieee802",
                "resource_url": "https://www.ieee802.org/11/",
                "scrape_schedule": "0 6 * * *",
                "run_on_startup": False,
                "check_content_hash": True,
                "publish_weight": 1.0,
                "update_weight": 0.9,
                "event_weight": 0.7,
                "temporal_extraction_days": 90,
                "scraper_delay": 1.0,
                "max_resources": 200,
                "max_redirects": 5,
                "discovery_mode": "incremental",
                "consecutive_duplicates_limit": 5,
                "description": "IEEE 802.11 Wi-Fi working group — draft amendments, approved standards, and technical documents",
            },
            {
                "datasource_id": "ieee802_1",
                "name": "IEEE 802.1 Working Group",
                "display_name": "IEEE 802.1 (Bridging & Security)",
                "org_id": "ieee",
                "source_type": "scraped_webpage",
                "fetch_url": "https://www.ieee802.org/1/",
                "has_events": False,
                "scraper_type": "ieee802",
                "resource_url": "https://www.ieee802.org/1/",
                "scrape_schedule": "0 6 * * *",
                "run_on_startup": False,
                "check_content_hash": True,
                "publish_weight": 1.0,
                "update_weight": 0.9,
                "event_weight": 0.7,
                "temporal_extraction_days": 90,
                "scraper_delay": 1.0,
                "max_resources": 200,
                "max_redirects": 5,
                "discovery_mode": "incremental",
                "consecutive_duplicates_limit": 5,
                "description": "IEEE 802.1 working group — bridging, VLANs, TSN, and network security standards",
            },
            {
                "datasource_id": "ieee802_3",
                "name": "IEEE 802.3 Working Group",
                "display_name": "IEEE 802.3 (Ethernet)",
                "org_id": "ieee",
                "source_type": "scraped_webpage",
                "fetch_url": "https://www.ieee802.org/3/",
                "has_events": False,
                "scraper_type": "ieee802",
                "resource_url": "https://www.ieee802.org/3/",
                "scrape_schedule": "0 6 * * *",
                "run_on_startup": False,
                "check_content_hash": True,
                "publish_weight": 1.0,
                "update_weight": 0.9,
                "event_weight": 0.7,
                "temporal_extraction_days": 90,
                "scraper_delay": 1.0,
                "max_resources": 200,
                "max_redirects": 5,
                "discovery_mode": "incremental",
                "consecutive_duplicates_limit": 5,
                "description": "IEEE 802.3 Ethernet working group — Ethernet standards, amendments, and technical specifications",
            },
            {
                "datasource_id": "ieee802_11_tg",
                "name": "IEEE 802.11 Task Groups & Amendments",
                "display_name": "IEEE 802.11 Task Groups",
                "org_id": "ieee",
                "source_type": "ieee_wg",
                "fetch_url": "https://www.ieee802.org/11/",
                "has_events": True,
                "scraper_type": "ieee802_11_tg",
                "resource_url": "https://www.ieee802.org/11/Reports/",
                "scrape_schedule": "0 4 * * 1",
                "run_on_startup": True,
                "check_content_hash": False,
                "publish_weight": 0.7,
                "update_weight": 0.7,
                "event_weight": 0.9,
                "temporal_extraction_days": 60,
                "scraper_delay": 2.0,
                "max_resources": 100,
                "max_redirects": 5,
                "discovery_mode": "incremental",
                "consecutive_duplicates_limit": 0,
                "description": (
                    "IEEE 802.11 active task group status pages covering TGbn (802.11bn/Wi-Fi 8), "
                    "TGbi, TGbp, TGbt, TGbq, TGbr, TGmf — ballot status, timelines, "
                    "leadership, plenary reports, and upcoming meeting schedule. "
                    "All data sourced from public www.ieee802.org/11/ pages."
                ),
            },
        ]

        query = """
        MERGE (d:DataSource {datasource_id: $datasource_id})
        ON CREATE SET
            d.name                        = $name,
            d.display_name                = $display_name,
            d.org_id                      = $org_id,
            d.source_type                 = $source_type,
            d.fetch_url                   = $fetch_url,
            d.has_events                  = $has_events,
            d.scraper_type                = $scraper_type,
            d.resource_url                = $resource_url,
            d.scrape_schedule             = $scrape_schedule,
            d.run_on_startup              = $run_on_startup,
            d.check_content_hash          = $check_content_hash,
            d.publish_weight              = $publish_weight,
            d.update_weight               = $update_weight,
            d.event_weight                = $event_weight,
            d.temporal_extraction_days    = $temporal_extraction_days,
            d.scraper_delay               = $scraper_delay,
            d.max_resources               = $max_resources,
            d.max_redirects               = $max_redirects,
            d.discovery_mode              = $discovery_mode,
            d.consecutive_duplicates_limit= $consecutive_duplicates_limit,
            d.description                 = $description
        ON MATCH SET
            d.display_name                = $display_name,
            d.description                 = $description
        RETURN d.datasource_id as id, (d.name IS NOT NULL) as existed
        """

        try:
            for ds in datasources:
                result = session.run(query, **ds)
                record = result.single()
                if record:
                    action = "updated" if record["existed"] else "created"
                    logger.info(f"IEEE 802 datasource '{record['id']}' {action}")
            return True
        except Exception as e:
            logger.error(f"Error upserting IEEE 802 datasources: {e}")
            return False

    # ------------------------------------------------------------------
    # MEF datasource migrations
    # ------------------------------------------------------------------

    @staticmethod
    def add_mef_datasources(session: Session) -> bool:
        """
        Upsert DataSource nodes for MEF (Metro Ethernet Forum).

        Two datasources:
          mef_specs  — technical specifications
          mef_news   — news and updates

        Idempotent — uses MERGE on datasource_id.
        """
        datasources = [
            {
                "datasource_id": "mef_specs",
                "name": "MEF Technical Specifications",
                "display_name": "MEF Technical Specifications",
                "org_id": "mef",
                "source_type": "scraped_webpage",
                "fetch_url": "https://www.mef.net/resources/technical-specifications/",
                "has_events": False,
                "scraper_type": "mef",
                "resource_url": "https://www.mef.net/resources/technical-specifications/",
                "scrape_schedule": "30 6 * * *",
                "run_on_startup": False,
                "check_content_hash": True,
                "publish_weight": 1.0,
                "update_weight": 0.9,
                "event_weight": 0.7,
                "temporal_extraction_days": 90,
                "scraper_delay": 1.0,
                "max_resources": 200,
                "max_redirects": 5,
                "discovery_mode": "incremental",
                "consecutive_duplicates_limit": 5,
                "description": "MEF technical specifications — carrier Ethernet, SD-WAN, and LSO API standards",
            },
            {
                "datasource_id": "mef_news",
                "name": "MEF News and Updates",
                "display_name": "MEF News",
                "org_id": "mef",
                "source_type": "scraped_webpage",
                "fetch_url": "https://www.mef.net/news-and-updates/",
                "has_events": False,
                "scraper_type": "mef",
                "resource_url": "https://www.mef.net/news-and-updates/",
                "scrape_schedule": "30 6 * * *",
                "run_on_startup": False,
                "check_content_hash": True,
                "publish_weight": 1.0,
                "update_weight": 0.9,
                "event_weight": 0.7,
                "temporal_extraction_days": 90,
                "scraper_delay": 1.0,
                "max_resources": 200,
                "max_redirects": 5,
                "discovery_mode": "incremental",
                "consecutive_duplicates_limit": 5,
                "description": "MEF news and updates — press releases and industry announcements",
            },
        ]

        query = """
        MERGE (d:DataSource {datasource_id: $datasource_id})
        ON CREATE SET
            d.name                        = $name,
            d.display_name                = $display_name,
            d.org_id                      = $org_id,
            d.source_type                 = $source_type,
            d.fetch_url                   = $fetch_url,
            d.has_events                  = $has_events,
            d.scraper_type                = $scraper_type,
            d.resource_url                = $resource_url,
            d.scrape_schedule             = $scrape_schedule,
            d.run_on_startup              = $run_on_startup,
            d.check_content_hash          = $check_content_hash,
            d.publish_weight              = $publish_weight,
            d.update_weight               = $update_weight,
            d.event_weight                = $event_weight,
            d.temporal_extraction_days    = $temporal_extraction_days,
            d.scraper_delay               = $scraper_delay,
            d.max_resources               = $max_resources,
            d.max_redirects               = $max_redirects,
            d.discovery_mode              = $discovery_mode,
            d.consecutive_duplicates_limit= $consecutive_duplicates_limit,
            d.description                 = $description
        ON MATCH SET
            d.display_name                = $display_name,
            d.description                 = $description
        RETURN d.datasource_id as id, (d.name IS NOT NULL) as existed
        """

        try:
            for ds in datasources:
                result = session.run(query, **ds)
                record = result.single()
                if record:
                    action = "updated" if record["existed"] else "created"
                    logger.info(f"MEF datasource '{record['id']}' {action}")
            return True
        except Exception as e:
            logger.error(f"Error upserting MEF datasources: {e}")
            return False

    # ------------------------------------------------------------------
    # NIST datasource migrations
    # ------------------------------------------------------------------

    @staticmethod
    def add_nist_datasources(session: Session) -> bool:
        """
        Upsert DataSource nodes for NIST CSRC.

        Two datasources:
          nist_sp800  — SP 800 series (cybersecurity)
          nist_fips   — FIPS standards

        Idempotent — uses MERGE on datasource_id.
        """
        datasources = [
            {
                "datasource_id": "nist_sp800",
                "name": "NIST SP 800 Series",
                "display_name": "NIST SP 800 (Cybersecurity)",
                "org_id": "nist",
                "source_type": "scraped_webpage",
                "fetch_url": "https://csrc.nist.gov/publications/sp800",
                "has_events": False,
                "scraper_type": "nist",
                "resource_url": "https://csrc.nist.gov/publications/sp800",
                "scrape_schedule": "0 5 * * *",
                "run_on_startup": False,
                "check_content_hash": True,
                "publish_weight": 1.0,
                "update_weight": 0.9,
                "event_weight": 0.7,
                "temporal_extraction_days": 90,
                "scraper_delay": 1.0,
                "max_resources": 200,
                "max_redirects": 5,
                "discovery_mode": "incremental",
                "consecutive_duplicates_limit": 5,
                "description": "NIST Special Publication 800 series — cybersecurity guidelines, frameworks, and best practices",
            },
            {
                "datasource_id": "nist_fips",
                "name": "NIST FIPS Standards",
                "display_name": "NIST FIPS",
                "org_id": "nist",
                "source_type": "scraped_webpage",
                "fetch_url": "https://csrc.nist.gov/publications/fips",
                "has_events": False,
                "scraper_type": "nist",
                "resource_url": "https://csrc.nist.gov/publications/fips",
                "scrape_schedule": "0 5 * * *",
                "run_on_startup": False,
                "check_content_hash": True,
                "publish_weight": 1.0,
                "update_weight": 0.9,
                "event_weight": 0.7,
                "temporal_extraction_days": 90,
                "scraper_delay": 1.0,
                "max_resources": 200,
                "max_redirects": 5,
                "discovery_mode": "incremental",
                "consecutive_duplicates_limit": 5,
                "description": "NIST Federal Information Processing Standards (FIPS) — mandatory security standards for US federal agencies",
            },
        ]

        query = """
        MERGE (d:DataSource {datasource_id: $datasource_id})
        ON CREATE SET
            d.name                        = $name,
            d.display_name                = $display_name,
            d.org_id                      = $org_id,
            d.source_type                 = $source_type,
            d.fetch_url                   = $fetch_url,
            d.has_events                  = $has_events,
            d.scraper_type                = $scraper_type,
            d.resource_url                = $resource_url,
            d.scrape_schedule             = $scrape_schedule,
            d.run_on_startup              = $run_on_startup,
            d.check_content_hash          = $check_content_hash,
            d.publish_weight              = $publish_weight,
            d.update_weight               = $update_weight,
            d.event_weight                = $event_weight,
            d.temporal_extraction_days    = $temporal_extraction_days,
            d.scraper_delay               = $scraper_delay,
            d.max_resources               = $max_resources,
            d.max_redirects               = $max_redirects,
            d.discovery_mode              = $discovery_mode,
            d.consecutive_duplicates_limit= $consecutive_duplicates_limit,
            d.description                 = $description
        ON MATCH SET
            d.display_name                = $display_name,
            d.description                 = $description
        RETURN d.datasource_id as id, (d.name IS NOT NULL) as existed
        """

        try:
            for ds in datasources:
                result = session.run(query, **ds)
                record = result.single()
                if record:
                    action = "updated" if record["existed"] else "created"
                    logger.info(f"NIST datasource '{record['id']}' {action}")
            return True
        except Exception as e:
            logger.error(f"Error upserting NIST datasources: {e}")
            return False

    # ------------------------------------------------------------------
    # ONF datasource migrations
    # ------------------------------------------------------------------

    @staticmethod
    def add_onf_datasources(session: Session) -> bool:
        """
        Upsert DataSource nodes for ONF (Open Networking Foundation).

        Two datasources:
          onf_blog  — blog / news
          onf_docs  — technical documents

        Idempotent — uses MERGE on datasource_id.
        """
        datasources = [
            {
                "datasource_id": "onf_blog",
                "name": "ONF Blog",
                "display_name": "ONF Blog",
                "org_id": "onf",
                "source_type": "scraped_webpage",
                "fetch_url": "https://opennetworking.org/news-and-events/blog/",
                "has_events": False,
                "scraper_type": "onf",
                "resource_url": "https://opennetworking.org/news-and-events/blog/",
                "scrape_schedule": "0 7 * * *",
                "run_on_startup": False,
                "check_content_hash": True,
                "publish_weight": 1.0,
                "update_weight": 0.9,
                "event_weight": 0.7,
                "temporal_extraction_days": 90,
                "scraper_delay": 1.0,
                "max_resources": 200,
                "max_redirects": 5,
                "discovery_mode": "incremental",
                "consecutive_duplicates_limit": 5,
                "description": "ONF blog — open networking technology news, project updates, and thought leadership",
            },
            {
                "datasource_id": "onf_docs",
                "name": "ONF Technical Documents",
                "display_name": "ONF Technical Documents",
                "org_id": "onf",
                "source_type": "scraped_webpage",
                "fetch_url": "https://opennetworking.org/technical-documents/",
                "has_events": False,
                "scraper_type": "onf",
                "resource_url": "https://opennetworking.org/technical-documents/",
                "scrape_schedule": "0 7 * * *",
                "run_on_startup": False,
                "check_content_hash": True,
                "publish_weight": 1.0,
                "update_weight": 0.9,
                "event_weight": 0.7,
                "temporal_extraction_days": 90,
                "scraper_delay": 1.0,
                "max_resources": 200,
                "max_redirects": 5,
                "discovery_mode": "incremental",
                "consecutive_duplicates_limit": 5,
                "description": "ONF technical documents — white papers, specifications, and architecture guides for open networking",
            },
        ]

        query = """
        MERGE (d:DataSource {datasource_id: $datasource_id})
        ON CREATE SET
            d.name                        = $name,
            d.display_name                = $display_name,
            d.org_id                      = $org_id,
            d.source_type                 = $source_type,
            d.fetch_url                   = $fetch_url,
            d.has_events                  = $has_events,
            d.scraper_type                = $scraper_type,
            d.resource_url                = $resource_url,
            d.scrape_schedule             = $scrape_schedule,
            d.run_on_startup              = $run_on_startup,
            d.check_content_hash          = $check_content_hash,
            d.publish_weight              = $publish_weight,
            d.update_weight               = $update_weight,
            d.event_weight                = $event_weight,
            d.temporal_extraction_days    = $temporal_extraction_days,
            d.scraper_delay               = $scraper_delay,
            d.max_resources               = $max_resources,
            d.max_redirects               = $max_redirects,
            d.discovery_mode              = $discovery_mode,
            d.consecutive_duplicates_limit= $consecutive_duplicates_limit,
            d.description                 = $description
        ON MATCH SET
            d.display_name                = $display_name,
            d.description                 = $description
        RETURN d.datasource_id as id, (d.name IS NOT NULL) as existed
        """

        try:
            for ds in datasources:
                result = session.run(query, **ds)
                record = result.single()
                if record:
                    action = "updated" if record["existed"] else "created"
                    logger.info(f"ONF datasource '{record['id']}' {action}")
            return True
        except Exception as e:
            logger.error(f"Error upserting ONF datasources: {e}")
            return False

    # ------------------------------------------------------------------
    # DMTF datasource migrations
    # ------------------------------------------------------------------

    @staticmethod
    def add_dmtf_datasources(session: Session) -> bool:
        """
        Upsert DataSource nodes for DMTF.

        Two datasources:
          dmtf_news     — news / press releases
          dmtf_redfish  — Redfish specifications

        Idempotent — uses MERGE on datasource_id.
        """
        datasources = [
            {
                "datasource_id": "dmtf_news",
                "name": "DMTF News",
                "display_name": "DMTF News",
                "org_id": "dmtf",
                "source_type": "scraped_webpage",
                "fetch_url": "https://www.dmtf.org/about/news",
                "has_events": False,
                "scraper_type": "dmtf",
                "resource_url": "https://www.dmtf.org/about/news",
                "scrape_schedule": "30 7 * * *",
                "run_on_startup": False,
                "check_content_hash": True,
                "publish_weight": 1.0,
                "update_weight": 0.9,
                "event_weight": 0.7,
                "temporal_extraction_days": 90,
                "scraper_delay": 1.0,
                "max_resources": 200,
                "max_redirects": 5,
                "discovery_mode": "incremental",
                "consecutive_duplicates_limit": 5,
                "description": "DMTF news — press releases and announcements from the Distributed Management Task Force",
            },
            {
                "datasource_id": "dmtf_redfish",
                "name": "DMTF Redfish Specifications",
                "display_name": "DMTF Redfish Specs",
                "org_id": "dmtf",
                "source_type": "scraped_webpage",
                "fetch_url": "https://www.dmtf.org/standards/redfish",
                "has_events": False,
                "scraper_type": "dmtf",
                "resource_url": "https://www.dmtf.org/standards/redfish",
                "scrape_schedule": "30 7 * * *",
                "run_on_startup": False,
                "check_content_hash": True,
                "publish_weight": 1.0,
                "update_weight": 0.9,
                "event_weight": 0.7,
                "temporal_extraction_days": 90,
                "scraper_delay": 1.0,
                "max_resources": 200,
                "max_redirects": 5,
                "discovery_mode": "incremental",
                "consecutive_duplicates_limit": 5,
                "description": "DMTF Redfish specifications — RESTful API standard for data center hardware management (DSP0266, DSP0268, etc.)",
            },
        ]

        query = """
        MERGE (d:DataSource {datasource_id: $datasource_id})
        ON CREATE SET
            d.name                        = $name,
            d.display_name                = $display_name,
            d.org_id                      = $org_id,
            d.source_type                 = $source_type,
            d.fetch_url                   = $fetch_url,
            d.has_events                  = $has_events,
            d.scraper_type                = $scraper_type,
            d.resource_url                = $resource_url,
            d.scrape_schedule             = $scrape_schedule,
            d.run_on_startup              = $run_on_startup,
            d.check_content_hash          = $check_content_hash,
            d.publish_weight              = $publish_weight,
            d.update_weight               = $update_weight,
            d.event_weight                = $event_weight,
            d.temporal_extraction_days    = $temporal_extraction_days,
            d.scraper_delay               = $scraper_delay,
            d.max_resources               = $max_resources,
            d.max_redirects               = $max_redirects,
            d.discovery_mode              = $discovery_mode,
            d.consecutive_duplicates_limit= $consecutive_duplicates_limit,
            d.description                 = $description
        ON MATCH SET
            d.display_name                = $display_name,
            d.description                 = $description
        RETURN d.datasource_id as id, (d.name IS NOT NULL) as existed
        """

        try:
            for ds in datasources:
                result = session.run(query, **ds)
                record = result.single()
                if record:
                    action = "updated" if record["existed"] else "created"
                    logger.info(f"DMTF datasource '{record['id']}' {action}")
            return True
        except Exception as e:
            logger.error(f"Error upserting DMTF datasources: {e}")
            return False

    @staticmethod
    def add_wba_extranet_root_datasource(session: Session) -> bool:
        """
        Upsert the root WBA Extranet DataSource node.

        Running this DataSource triggers the WBAExtranetScraper, which then
        discovers per-community child DataSources at scrape time. Default
        cadence: weekly (Mondays 02:00). Disabled by default — set
        run_on_startup or wait for the scheduled slot to fire.

        Idempotent — MERGE on datasource_id.
        """
        try:
            ds = {
                "datasource_id": "wba_extranet",
                "name": "WBA Extranet",
                "display_name": "WBA Extranet (Programmes & Workgroups)",
                "org_id": "wba",
                "source_type": "authenticated_portal",
                "fetch_url": "https://extranet.wballiance.com",
                "has_events": False,
                "scraper_type": "wba_extranet",
                "resource_url": "/",
                "scrape_schedule": "0 2 * * 1",
                "run_on_startup": True,
                "check_content_hash": True,
                "publish_weight": 1.0,
                "update_weight": 0.9,
                "event_weight": 0.8,
                "temporal_extraction_days": 90,
                "scraper_delay": 1.0,
                "max_resources": -1,
                "max_redirects": 5,
                "discovery_mode": "incremental",
                "consecutive_duplicates_limit": 5,
                "description": (
                    "WBA Extranet — member-only Higher Logic portal. "
                    "Root datasource that drives weekly discovery of programmes "
                    "and workgroups (e.g., Next Gen, AI/ML, PQC, Wi-Fi Design). "
                    "Each discovered community becomes its own child DataSource."
                ),
            }
            query = """
            MERGE (d:DataSource {datasource_id: $datasource_id})
            ON CREATE SET
                d.name                        = $name,
                d.display_name                = $display_name,
                d.org_id                      = $org_id,
                d.source_type                 = $source_type,
                d.fetch_url                   = $fetch_url,
                d.has_events                  = $has_events,
                d.scraper_type                = $scraper_type,
                d.resource_url                = $resource_url,
                d.scrape_schedule             = $scrape_schedule,
                d.run_on_startup              = $run_on_startup,
                d.check_content_hash          = $check_content_hash,
                d.publish_weight              = $publish_weight,
                d.update_weight               = $update_weight,
                d.event_weight                = $event_weight,
                d.temporal_extraction_days    = $temporal_extraction_days,
                d.scraper_delay               = $scraper_delay,
                d.max_resources               = $max_resources,
                d.max_redirects               = $max_redirects,
                d.discovery_mode              = $discovery_mode,
                d.consecutive_duplicates_limit= $consecutive_duplicates_limit,
                d.description                 = $description
            ON MATCH SET
                d.display_name                = $display_name,
                d.description                 = $description,
                d.run_on_startup              = true
            RETURN d.datasource_id AS id, (d.name IS NOT NULL) AS existed
            """
            result = session.run(query, **ds)
            record = result.single()
            if record:
                action = "updated" if record["existed"] else "created"
                logger.info(f"WBA Extranet root DataSource '{record['id']}' {action}")
            return True
        except Exception as e:
            logger.error(f"Error upserting WBA Extranet root datasource: {e}")
            return False

    @staticmethod
    def add_datasource_parent_index(session: Session) -> bool:
        """
        Index DataSource.parent_datasource_id so programme→workgroup hierarchy
        lookups are O(log n) instead of full scans.

        Used by the fast oracle pipeline when expanding "what's new in <programme>"
        queries to include child workgroups, and by the frontend tree picker.

        Idempotent — IF NOT EXISTS guard.
        """
        try:
            session.run(
                "CREATE INDEX datasource_parent_id IF NOT EXISTS "
                "FOR (d:DataSource) ON (d.parent_datasource_id)"
            )
            logger.info("Created/verified index on DataSource.parent_datasource_id")
            return True
        except Exception as e:
            logger.error(f"Error creating datasource_parent_id index: {e}")
            return False

    @staticmethod
    def fix_wba_extranet_child_scraper_type(session: Session) -> bool:
        """
        Remove scraper_type and scrape_schedule from WBA Extranet child DataSource nodes.

        Child community nodes (datasource_id STARTS WITH 'wba_extranet_') were
        incorrectly created with scraper_type='wba_extranet' and a weekly cron.
        This caused the scheduler to trigger N+1 independent full scrapes (one per
        community) instead of a single root-driven run.  Child nodes exist only for
        document and event attribution — they should never be scheduled directly.

        Idempotent: REMOVE on properties that may not exist is a no-op in Cypher.
        """
        try:
            result = session.run("""
                MATCH (d:DataSource)
                WHERE d.datasource_id STARTS WITH 'wba_extranet_'
                REMOVE d.scraper_type, d.scrape_schedule
                RETURN count(d) AS fixed
            """)
            record = result.single()
            fixed = record["fixed"] if record else 0
            logger.info(f"fix_wba_extranet_child_scraper_type: cleared {fixed} child node(s)")
            return True
        except Exception as e:
            logger.error(f"Error in fix_wba_extranet_child_scraper_type: {e}")
            return False

    # ------------------------------------------------------------------
    # Tech Field Day datasource migrations
    # ------------------------------------------------------------------

    @staticmethod
    def add_techfieldday_datasources(session: Session) -> bool:
        """
        Upsert the Tech Field Day root datasource + one child per topic listed
        at https://techfieldday.com/topics. Children inherit auth/config from
        the root via parent_datasource_id.

        @-mention aliases follow the community-standard short forms:
          @aifd  → AI Field Day        @cfd   → Cloud Field Day
          @nfd   → Networking Field Day @mfd  → Mobility Field Day
          @sfd   → Storage Field Day   @secfd → Security Field Day
          @vfd   → Virtualization Field Day  @efd → Edge Field Day
        etc. The root @techfieldday / @tfd matches all of them.

        Idempotent — MERGE on datasource_id.
        """
        root = {
            "datasource_id": "techfieldday",
            "name": "Tech Field Day",
            "display_name": "Tech Field Day",
            "org_id": "techfieldday",
            "source_type": "scraped_webpage",
            "fetch_url": "https://stg-techfielddayq-staging.kinsta.cloud",
            "has_events": True,
            "scraper_type": "techfieldday",
            "resource_url": "https://stg-techfielddayq-staging.kinsta.cloud",
            "scrape_schedule": "15 7 * * *",   # daily 07:15 UTC
            "run_on_startup": False,
            "check_content_hash": True,
            "publish_weight": 1.0,
            "update_weight": 0.8,
            "event_weight": 1.0,
            "temporal_extraction_days": 365,
            "scraper_delay": 0.5,
            "max_resources": 600,
            "max_redirects": 5,
            "discovery_mode": "incremental",
            "consecutive_duplicates_limit": 20,
            "description": (
                "Tech Field Day — an invite-only enterprise IT influencer programme "
                "(AI Field Day, Cloud Field Day, Networking Field Day, etc.). "
                "Each video session links delegates, presenters and sponsor companies."
            ),
            "primary_alias": "techfieldday",
            "aliases": ["tfd", "techfieldday"],
            "parent_datasource_id": None,
        }

        # (datasource_id_suffix, display_name, primary_alias, [aliases…])
        topics = [
            ("ai",                     "AI Field Day",                       "aifd",   ["aifd", "ai-field-day", "tfd-ai"]),
            ("ai-infrastructure",      "AI Infrastructure Field Day",        "aiifd",  ["aiifd", "ai-infra", "ai-infrastructure-field-day"]),
            ("appdev",                 "AppDev Field Day",                   "adfd",   ["adfd", "appdev-field-day"]),
            ("cloud",                  "Cloud Field Day",                    "cfd",    ["cfd", "cloud-field-day"]),
            ("data",                   "Data Field Day",                     "datafd", ["datafd", "data-field-day"]),
            ("edge",                   "Edge Field Day",                     "efd",    ["efd", "edge-field-day"]),
            ("mainframe",              "Mainframe Field Day",                "mffd",   ["mffd", "mainframe-field-day"]),
            ("mobility",               "Mobility Field Day",                 "mfd",    ["mfd", "mobility-field-day"]),
            ("networking",             "Networking Field Day",               "nfd",    ["nfd", "networking-field-day"]),
            ("security",               "Security Field Day",                 "xfd",    ["xfd", "secfd", "security-field-day"]),
            ("storage",                "Storage Field Day",                  "sfd",    ["sfd", "storage-field-day"]),
            ("tech",                   "Tech Field Day",                     "tfdcore",["tfd-core", "tech-field-day"]),
            ("unified-communications", "Unified Communications Field Day",   "ucfd",   ["ucfd", "uc-field-day"]),
            ("virtualization",         "Virtualization Field Day",           "vfd",    ["vfd", "virt-field-day"]),
            ("wireless",               "Wireless Field Day",                 "wfd",    ["wfd", "wireless-field-day"]),
        ]

        upsert_query = """
        MERGE (d:DataSource {datasource_id: $datasource_id})
        ON CREATE SET
            d.name                        = $name,
            d.display_name                = $display_name,
            d.org_id                      = $org_id,
            d.source_type                 = $source_type,
            d.fetch_url                   = $fetch_url,
            d.has_events                  = $has_events,
            d.scraper_type                = $scraper_type,
            d.resource_url                = $resource_url,
            d.scrape_schedule             = $scrape_schedule,
            d.run_on_startup              = $run_on_startup,
            d.check_content_hash          = $check_content_hash,
            d.publish_weight              = $publish_weight,
            d.update_weight               = $update_weight,
            d.event_weight                = $event_weight,
            d.temporal_extraction_days    = $temporal_extraction_days,
            d.scraper_delay               = $scraper_delay,
            d.max_resources               = $max_resources,
            d.max_redirects               = $max_redirects,
            d.discovery_mode              = $discovery_mode,
            d.consecutive_duplicates_limit= $consecutive_duplicates_limit,
            d.description                 = $description,
            d.primary_alias               = $primary_alias,
            d.aliases                     = $aliases,
            d.parent_datasource_id        = $parent_datasource_id
        ON MATCH SET
            d.display_name                = $display_name,
            d.description                 = $description,
            d.primary_alias               = $primary_alias,
            d.aliases                     = $aliases,
            d.parent_datasource_id        = $parent_datasource_id,
            d.scraper_type                = $scraper_type
        RETURN d.datasource_id as id, (d.name IS NOT NULL) as existed
        """

        try:
            session.run(upsert_query, **root)
            for topic_slug, display_name, primary, aliases in topics:
                ds = {
                    "datasource_id": f"techfieldday_{topic_slug}",
                    "name": display_name,
                    "display_name": display_name,
                    "org_id": "techfieldday",
                    "source_type": "scraped_webpage",
                    "fetch_url": f"https://stg-techfielddayq-staging.kinsta.cloud/topic/{topic_slug}/",
                    "has_events": True,
                    "scraper_type": "techfieldday",
                    "resource_url": f"https://stg-techfielddayq-staging.kinsta.cloud/topic/{topic_slug}/",
                    "scrape_schedule": "15 7 * * *",
                    "run_on_startup": False,
                    "check_content_hash": True,
                    "publish_weight": 1.0,
                    "update_weight": 0.8,
                    "event_weight": 1.0,
                    "temporal_extraction_days": 365,
                    "scraper_delay": 0.5,
                    "max_resources": -1,
                    "max_redirects": 5,
                    "discovery_mode": "incremental",
                    "consecutive_duplicates_limit": 20,
                    "description": (
                        f"{display_name} — Tech Field Day sessions on {display_name.lower().replace(' field day','')}. "
                        f"Includes presenter, sponsor company, event date, and video link."
                    ),
                    "primary_alias": primary,
                    "aliases": aliases,
                    "parent_datasource_id": "techfieldday",
                }
                session.run(upsert_query, **ds)
            logger.info(f"Tech Field Day datasources: root + {len(topics)} topic children upserted")
            return True
        except Exception as e:
            logger.error(f"Error upserting Tech Field Day datasources: {e}")
            return False

    @staticmethod
    def add_wfa_root_datasource_hierarchy(session: Session) -> bool:
        """
        Upsert a `wfa` root DataSource and parent every wfa_causeway_* /
        wfa_resource_page node to it.

        Without this, the wfa_* DataSource nodes are all siblings with no
        parent, so the @-mention resolver and `_expand_datasource_parents`
        cannot fan `@wfa` out to every workgroup — it ends up scoping the
        chat to whichever single wfa_* node won the alphabetical tiebreak
        (typically `wfa_resource_page`). That made docs from `OperatorMSTG`
        and other Causeway TGs invisible unless the user explicitly
        @-mentioned them by exact slug.

        The root is metadata only — `scraper_type` is left unset so the
        retriever scheduler never picks it up; the children continue to do
        the actual scraping. Idempotent — MERGE on datasource_id.
        """
        try:
            root = {
                "datasource_id": "wfa",
                "name": "Wi-Fi Alliance",
                "display_name": "Wi-Fi Alliance",
                "org_id": "wfa",
                "source_type": "umbrella",
                "description": (
                    "Wi-Fi Alliance — umbrella DataSource that fans @wfa out "
                    "to every Wi-Fi Alliance child source (Causeway task/"
                    "market segment groups plus the public Resource Center)."
                ),
                "primary_alias": "wfa",
                "aliases": ["wfa", "wi-fi alliance", "wifi alliance", "wifialliance"],
            }
            session.run(
                """
                MERGE (d:DataSource {datasource_id: $datasource_id})
                ON CREATE SET
                    d.name           = $name,
                    d.display_name   = $display_name,
                    d.org_id         = $org_id,
                    d.source_type    = $source_type,
                    d.description    = $description,
                    d.primary_alias  = $primary_alias,
                    d.aliases        = $aliases,
                    d.parent_datasource_id = NULL
                ON MATCH SET
                    d.display_name   = $display_name,
                    d.description    = $description,
                    d.primary_alias  = $primary_alias,
                    d.aliases        = $aliases
                """,
                **root,
            )

            # Re-parent all wfa_* children except the root itself.
            result = session.run(
                """
                MATCH (d:DataSource)
                WHERE d.datasource_id STARTS WITH 'wfa_'
                  AND (d.parent_datasource_id IS NULL OR d.parent_datasource_id <> 'wfa')
                SET d.parent_datasource_id = 'wfa'
                RETURN count(d) AS reparented
                """
            )
            record = result.single()
            reparented = record["reparented"] if record else 0
            logger.info(
                "add_wfa_root_datasource_hierarchy: ensured wfa root + reparented "
                f"{reparented} wfa_* child(ren)"
            )
            return True
        except Exception as e:
            logger.error(f"Error wiring WFA datasource hierarchy: {e}")
            return False

    @staticmethod
    def verify_migrations(session: Session) -> Dict[str, Any]:
        """
        Verify migration status and return statistics.
        
        Returns:
            Dictionary with migration status and counts
        """
        stats = {}
        
        try:
            # Check tier distribution on Topics
            query = """
            MATCH (t:Topic)
            RETURN t.tier as tier, COUNT(t) as count
            ORDER BY tier
            """
            result = session.run(query)
            tier_dist = {}
            for record in result:
                tier = record['tier'] if record['tier'] is not None else 'NULL'
                tier_dist[tier] = record['count']
            stats['tier_distribution'] = tier_dist
            
            # Check importance distribution
            query = """
            MATCH (n)
            WHERE n.importance IS NOT NULL
            RETURN 
                COUNT(n) as total,
                ROUND(AVG(n.importance), 2) as avg,
                MIN(n.importance) as min,
                MAX(n.importance) as max
            """
            result = session.run(query)
            record = result.single()
            if record:
                stats['importance'] = {
                    'total_nodes': record['total'],
                    'avg': record['avg'],
                    'min': record['min'],
                    'max': record['max'],
                }
            
            return stats
            
        except Exception as e:
            logger.error(f"Error verifying migrations: {e}")
            return {'error': str(e)}
