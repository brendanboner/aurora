#!/bin/bash
# Quick verification script to check if Event nodes were created

echo "=== Checking Event Nodes ==="
echo "MATCH (e:Event) WHERE e.name CONTAINS 'Cisco' RETURN e.name, e.event_type, e.start_date ORDER BY e.start_date DESC;" | docker-compose exec -T neo4j cypher-shell -u neo4j -p password

echo ""
echo "=== Checking Event Relationships ==="
echo "MATCH (r:Resource)-[rel:RELATES_TO]->(e:Event) WHERE e.name CONTAINS 'Cisco' RETURN e.name, count(r) as video_count ORDER BY video_count DESC;" | docker-compose exec -T neo4j cypher-shell -u neo4j -p password

echo ""
echo "=== Sample Resource with Event ==="
echo "MATCH (r:Resource)-[rel:RELATES_TO]->(e:Event) WHERE e.name CONTAINS 'Cisco AI Summit' RETURN r.title, e.name, rel.confidence LIMIT 3;" | docker-compose exec -T neo4j cypher-shell -u neo4j -p password
