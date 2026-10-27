
import oracledb
from dotenv import load_dotenv
import os

load_dotenv(".env")

connection = oracledb.connect(
    user="RIKHTAARYAN_SCHEMA_0MI6C",
    password=os.getenv("DB_PASSWORD"),
    dsn="tcps://db.freesql.com:2484/26ai_un3c1"
)

print("Successfully connected to Oracle Database!")

cursor = connection.cursor()
cursor.execute("SELECT * FROM DUAL")
print(cursor.fetchone())

cursor.close()
connection.close()
