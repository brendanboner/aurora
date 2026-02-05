#!/bin/bash
# Clean up Cisco video resources before re-ingestion

echo "=== Cleaning up Cisco AI Summit and Cisco Live 2025 resources ==="

echo ""
echo "Step 1: Count existing resources..."
echo "MATCH (r:Resource) WHERE r.title CONTAINS 'Cisco AI Summit' OR r.title CONTAINS 'Cisco Live 2025' RETURN count(r) as total;" | docker-compose exec -T neo4j cypher-shell -u neo4j -p password

echo ""
echo "Step 2: Detach and delete all related nodes and relationships..."
echo "MATCH (r:Resource) WHERE r.title CONTAINS 'Cisco AI Summit' OR r.title CONTAINS 'Cisco Live 2025' DETACH DELETE r;" | docker-compose exec -T neo4j cypher-shell -u neo4j -p password

echo ""
echo "Step 3: Verify cleanup..."
echo "MATCH (r:Resource) WHERE r.title CONTAINS 'Cisco AI Summit' OR r.title CONTAINS 'Cisco Live 2025' RETURN count(r) as remaining;" | docker-compose exec -T neo4j cypher-shell -u neo4j -p password

echo ""
echo "✅ Cleanup complete! Ready for fresh ingestion."
