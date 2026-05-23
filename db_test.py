"""Smoke test: connect to the DataHub Oracle instance and verify access."""
import oracledb

connection = oracledb.connect(
    user="SMART",
    password="SMART",
    dsn="nximpress-refprod-KAR-PFE:1521/SMART",
)

print(f"Connected. Oracle version: {connection.version}")

cursor = connection.cursor()
cursor.execute("SELECT USER FROM DUAL")
row = cursor.fetchone()
print(f"Connected as: {row[0]}")

cursor.close()
connection.close()
print("Connection closed cleanly.")