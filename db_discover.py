"""Discover the database schema: list tables/views accessible to SMART user."""
import os

import oracledb

connection = oracledb.connect(
    user=os.environ.get("REVIEWER_DB_USER", "SMART"),
    password=os.environ.get("REVIEWER_DB_PASSWORD", "SMART"),
    dsn=os.environ.get("REVIEWER_DB_DSN", "nximpress-refprod-KAR-PFE:1521/SMART"),
)
cursor = connection.cursor()

print("─" * 60)
print("Tables/views accessible to SMART (limited to first 200):")
print("─" * 60)

cursor.execute("""
    SELECT owner, object_name, object_type
    FROM all_objects
    WHERE object_type IN ('TABLE', 'VIEW')
      AND owner NOT IN ('SYS', 'SYSTEM', 'XDB', 'CTXSYS', 'MDSYS',
                        'ORDSYS', 'OUTLN', 'WMSYS', 'EXFSYS',
                        'DBSNMP', 'APPQOSSYS', 'OJVMSYS',
                        'GSMADMIN_INTERNAL', 'AUDSYS', 'DVSYS')
    ORDER BY owner, object_name
    FETCH FIRST 200 ROWS ONLY
""")

current_owner = None
for owner, name, kind in cursor:
    if owner != current_owner:
        print(f"\n[{owner}]")
        current_owner = owner
    print(f"  {kind:5} {name}")

cursor.close()
connection.close()