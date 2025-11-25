#!/usr/bin/env python3
"""Ensure default system configurations exist in the database."""

import sys
sys.path.insert(0, '/app/backend')

from src.services.postgres import get_conn

def main():
    conn = get_conn()
    cur = conn.cursor()

    # Define default configurations
    configs = [
        ('default', 'Default Configuration', 'daily', True, 1.0, 0.8, 0.9),
        ('wfa_resource_page', 'Wi-Fi Alliance Resource Center', 'daily', True, 1.0, 0.8, 0.9),
        ('manual_upload', 'Manual Document Upload', 'manual', True, 1.0, 0.8, 0.9)
    ]

    print("Ensuring system configurations exist...")
    for datasource_id, name, freq, check_hash, pub_w, upd_w, evt_w in configs:
        cur.execute('''
            INSERT INTO system_configuration 
                (datasource_id, name, scrape_frequency, check_content_hash, publish_weight, update_weight, event_weight)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (datasource_id) DO NOTHING
        ''', (datasource_id, name, freq, check_hash, pub_w, upd_w, evt_w))
        print(f'  ✓ {datasource_id}: {name}')

    conn.commit()
    
    # Verify
    cur.execute("SELECT datasource_id, name FROM system_configuration ORDER BY datasource_id")
    results = cur.fetchall()
    print(f"\nTotal configurations in database: {len(results)}")
    for row in results:
        print(f"  - {row[0]}: {row[1]}")
    
    conn.close()
    print("\nDone!")

if __name__ == "__main__":
    main()
