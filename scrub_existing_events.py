#!/usr/bin/env python3
"""
Database Migration Script: Scrub Sensitive Information from Existing Events

This script scans all Event nodes in Neo4j, detects sensitive meeting information
(URLs, passcodes, meeting IDs, etc.), and updates the location and description
fields with sanitized versions.

IMPORTANT: 
- Always run in dry-run mode first to preview changes
- Backup your database before running in production mode
- Review the changes carefully before committing

Usage:
    # Dry run (preview changes only - recommended first step)
    python scrub_existing_events.py --dry-run
    
    # Run with verbose output
    python scrub_existing_events.py --dry-run --verbose
    
    # Actually update the database (after reviewing dry-run results)
    python scrub_existing_events.py
    
    # Update only specific datasource
    python scrub_existing_events.py --datasource wfa_causeway
    
    # Show statistics only
    python scrub_existing_events.py --stats-only
"""

import sys
import os
import argparse
from typing import Dict, List, Any, Optional
from datetime import datetime
import json

# Add parent directory and neo4j-client to path to import modules
script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, script_dir)
sys.path.insert(0, os.path.join(script_dir, 'neo4j-client'))

from neo4j_client import Neo4jClient
from retriever.utils.sensitive_info_scrubber import SensitiveInfoScrubber


class EventScrubber:
    """Handles scanning and scrubbing of events in Neo4j database."""
    
    def __init__(self, neo4j_uri: str, neo4j_user: str, neo4j_password: str, 
                 neo4j_database: str = "neo4j", dry_run: bool = True, verbose: bool = False):
        """
        Initialize the event scrubber.
        
        Args:
            neo4j_uri: Neo4j connection URI
            neo4j_user: Neo4j username
            neo4j_password: Neo4j password
            neo4j_database: Database name
            dry_run: If True, only preview changes without updating
            verbose: If True, print detailed information
        """
        self.client = Neo4jClient(
            uri=neo4j_uri,
            user=neo4j_user,
            password=neo4j_password,
            database=neo4j_database
        )
        self.scrubber = SensitiveInfoScrubber()
        self.dry_run = dry_run
        self.verbose = verbose
        
        # Statistics
        self.stats = {
            'total_events': 0,
            'events_with_sensitive_data': 0,
            'events_updated': 0,
            'events_failed': 0,
            'location_sanitized': 0,
            'description_sanitized': 0,
            'patterns_detected': {}
        }
    
    def get_all_events(self, datasource_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Fetch all events from the database.
        
        Args:
            datasource_id: Optional datasource filter
            
        Returns:
            List of event dictionaries
        """
        where_clause = "WHERE e.datasource_id = $datasource_id" if datasource_id else ""
        params = {"datasource_id": datasource_id} if datasource_id else {}
        
        query = f"""
        MATCH (e:Event)
        {where_clause}
        RETURN e.url_hash as url_hash,
               e.name as name,
               e.event_type as event_type,
               e.location as location,
               e.description as description,
               e.datasource_id as datasource_id,
               e.start_date as start_date
        ORDER BY e.start_date DESC
        """
        
        results = self.client.execute_query(query, params)
        return results
    
    def update_event(self, url_hash: str, location: str, description: str) -> bool:
        """
        Update an event's location and description.
        
        Args:
            url_hash: Event identifier
            location: New sanitized location
            description: New sanitized description
            
        Returns:
            True if successful, False otherwise
        """
        query = """
        MATCH (e:Event {url_hash: $url_hash})
        SET e.location = $location,
            e.description = $description,
            e.sanitized_at = datetime()
        RETURN e.url_hash as url_hash
        """
        
        params = {
            "url_hash": url_hash,
            "location": location,
            "description": description
        }
        
        try:
            results = self.client.execute_query(query, params)
            return len(results) > 0
        except Exception as e:
            print(f"ERROR updating event {url_hash}: {e}")
            return False
    
    def process_event(self, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Process a single event, detecting and sanitizing sensitive information.
        
        Args:
            event: Event dictionary from database
            
        Returns:
            Dictionary with change information if changes needed, None otherwise
        """
        url_hash = event.get('url_hash')
        name = event.get('name', 'Unknown')
        location = event.get('location', '')
        description = event.get('description', '')
        
        # Sanitize both fields
        location_result = self.scrubber.sanitize_location(location)
        description_result = self.scrubber.sanitize_description(description)
        
        # Check if any changes were made
        if not location_result.was_modified and not description_result.was_modified:
            return None
        
        # Track detected patterns
        all_patterns = location_result.detected_patterns + description_result.detected_patterns
        for pattern in all_patterns:
            self.stats['patterns_detected'][pattern] = \
                self.stats['patterns_detected'].get(pattern, 0) + 1
        
        # Build change summary
        changes = {
            'url_hash': url_hash,
            'name': name,
            'datasource_id': event.get('datasource_id'),
            'start_date': str(event.get('start_date', '')),
            'location_changed': location_result.was_modified,
            'description_changed': description_result.was_modified,
            'original_location': location_result.original,
            'new_location': location_result.sanitized,
            'original_description': description_result.original[:200] + '...' if len(description_result.original) > 200 else description_result.original,
            'new_description': description_result.sanitized[:200] + '...' if len(description_result.sanitized) > 200 else description_result.sanitized,
            'detected_patterns': list(set(all_patterns))
        }
        
        return changes
    
    def run(self, datasource_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Run the scrubbing process on all events.
        
        Args:
            datasource_id: Optional datasource filter
            
        Returns:
            Dictionary with statistics and results
        """
        print("=" * 80)
        print(f"EVENT SCRUBBER - {'DRY RUN MODE' if self.dry_run else 'PRODUCTION MODE'}")
        print("=" * 80)
        
        if not self.dry_run:
            print("\n⚠️  WARNING: Running in PRODUCTION mode - database will be modified!")
            print("⚠️  Make sure you have a backup of your database!")
            response = input("\nType 'YES' to continue: ")
            if response != 'YES':
                print("Aborted.")
                return self.stats
        
        print(f"\nFetching events from database...")
        if datasource_id:
            print(f"Filtering by datasource: {datasource_id}")
        
        events = self.get_all_events(datasource_id)
        self.stats['total_events'] = len(events)
        
        print(f"Found {len(events)} events to process\n")
        
        changes_list = []
        
        # Process each event
        for i, event in enumerate(events, 1):
            if self.verbose and i % 10 == 0:
                print(f"Processing event {i}/{len(events)}...")
            
            changes = self.process_event(event)
            
            if changes:
                self.stats['events_with_sensitive_data'] += 1
                
                if changes['location_changed']:
                    self.stats['location_sanitized'] += 1
                
                if changes['description_changed']:
                    self.stats['description_sanitized'] += 1
                
                changes_list.append(changes)
                
                # Print change details if verbose
                if self.verbose:
                    print(f"\n{'[DRY RUN]' if self.dry_run else '[UPDATE]'} Event: {changes['name']}")
                    print(f"  URL Hash: {changes['url_hash']}")
                    print(f"  Datasource: {changes['datasource_id']}")
                    print(f"  Patterns detected: {', '.join(changes['detected_patterns'])}")
                    
                    if changes['location_changed']:
                        print(f"  Location: '{changes['original_location']}' → '{changes['new_location']}'")
                    
                    if changes['description_changed']:
                        print(f"  Description modified (showing first 200 chars)")
                        print(f"    Before: {changes['original_description']}")
                        print(f"    After:  {changes['new_description']}")
                
                # Update database if not dry run
                if not self.dry_run:
                    success = self.update_event(
                        changes['url_hash'],
                        changes['new_location'],
                        changes['new_description']
                    )
                    
                    if success:
                        self.stats['events_updated'] += 1
                    else:
                        self.stats['events_failed'] += 1
        
        # Print summary
        print("\n" + "=" * 80)
        print("SUMMARY")
        print("=" * 80)
        print(f"Total events scanned:              {self.stats['total_events']}")
        print(f"Events with sensitive data:        {self.stats['events_with_sensitive_data']}")
        print(f"  - Location sanitized:            {self.stats['location_sanitized']}")
        print(f"  - Description sanitized:         {self.stats['description_sanitized']}")
        
        if not self.dry_run:
            print(f"Events successfully updated:       {self.stats['events_updated']}")
            print(f"Events failed to update:           {self.stats['events_failed']}")
        
        # Print pattern statistics
        if self.stats['patterns_detected']:
            print("\nDetected Pattern Types:")
            for pattern, count in sorted(self.stats['patterns_detected'].items(), key=lambda x: x[1], reverse=True):
                print(f"  - {pattern}: {count}")
        
        # Save detailed report
        if changes_list:
            report_filename = f"scrub_report_{'dry_run_' if self.dry_run else ''}{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            with open(report_filename, 'w') as f:
                json.dump({
                    'stats': self.stats,
                    'changes': changes_list,
                    'dry_run': self.dry_run,
                    'timestamp': datetime.now().isoformat()
                }, f, indent=2)
            
            print(f"\nDetailed report saved to: {report_filename}")
        
        print("\n" + "=" * 80)
        
        if self.dry_run:
            print("\n✓ Dry run complete - no changes were made to the database")
            print("  Review the results above and run without --dry-run to apply changes")
        else:
            print("\n✓ Database update complete")
        
        return self.stats


def get_stats_only(neo4j_uri: str, neo4j_user: str, neo4j_password: str, 
                   neo4j_database: str = "neo4j") -> Dict[str, Any]:
    """
    Get statistics about events without making changes.
    
    Returns:
        Dictionary with event statistics
    """
    client = Neo4jClient(
        uri=neo4j_uri,
        user=neo4j_user,
        password=neo4j_password,
        database=neo4j_database
    )
    
    # Total events
    total_query = "MATCH (e:Event) RETURN count(e) as count"
    total_result = client.execute_query(total_query, {})
    total_events = total_result[0]['count'] if total_result else 0
    
    # Events by datasource
    datasource_query = """
    MATCH (e:Event)
    RETURN e.datasource_id as datasource_id, count(e) as count
    ORDER BY count DESC
    """
    datasource_results = client.execute_query(datasource_query, {})
    
    # Events by type
    type_query = """
    MATCH (e:Event)
    RETURN e.event_type as event_type, count(e) as count
    ORDER BY count DESC
    """
    type_results = client.execute_query(type_query, {})
    
    print("=" * 80)
    print("EVENT DATABASE STATISTICS")
    print("=" * 80)
    print(f"\nTotal events: {total_events}")
    
    print("\nEvents by datasource:")
    for row in datasource_results:
        print(f"  - {row['datasource_id']}: {row['count']}")
    
    print("\nEvents by type:")
    for row in type_results:
        print(f"  - {row['event_type']}: {row['count']}")
    
    print("\n" + "=" * 80)
    
    return {
        'total_events': total_events,
        'by_datasource': datasource_results,
        'by_type': type_results
    }


def main():
    """Main entry point for the script."""
    parser = argparse.ArgumentParser(
        description="Scrub sensitive meeting information from events in Neo4j database",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview changes without updating database (recommended first step)'
    )
    
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Print detailed information about each change'
    )
    
    parser.add_argument(
        '--datasource',
        type=str,
        help='Only process events from this datasource'
    )
    
    parser.add_argument(
        '--stats-only',
        action='store_true',
        help='Show database statistics without making changes'
    )
    
    parser.add_argument(
        '--neo4j-uri',
        type=str,
        default=os.getenv('NEO4J_URI', 'bolt://localhost:7687'),
        help='Neo4j URI (default: bolt://localhost:7687 or NEO4J_URI env var)'
    )
    
    parser.add_argument(
        '--neo4j-user',
        type=str,
        default=os.getenv('NEO4J_USER', 'neo4j'),
        help='Neo4j username (default: neo4j or NEO4J_USER env var)'
    )
    
    parser.add_argument(
        '--neo4j-password',
        type=str,
        default=os.getenv('NEO4J_PASSWORD', 'password'),
        help='Neo4j password (default: password or NEO4J_PASSWORD env var)'
    )
    
    parser.add_argument(
        '--neo4j-database',
        type=str,
        default=os.getenv('NEO4J_DATABASE', 'neo4j'),
        help='Neo4j database name (default: neo4j or NEO4J_DATABASE env var)'
    )
    
    args = parser.parse_args()
    
    # Stats only mode
    if args.stats_only:
        get_stats_only(
            args.neo4j_uri,
            args.neo4j_user,
            args.neo4j_password,
            args.neo4j_database
        )
        return
    
    # Run scrubber
    scrubber = EventScrubber(
        neo4j_uri=args.neo4j_uri,
        neo4j_user=args.neo4j_user,
        neo4j_password=args.neo4j_password,
        neo4j_database=args.neo4j_database,
        dry_run=args.dry_run,
        verbose=args.verbose
    )
    
    scrubber.run(datasource_id=args.datasource)


if __name__ == '__main__':
    main()
