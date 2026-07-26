import mysql.connector
from dotenv import load_dotenv
import os

load_dotenv()

def get_db_connection():

    db_host = os.getenv("DB_HOST")

    connection_config = {
        "host": db_host,
        "port": int(os.getenv("DB_PORT", 3306)),
        "user": os.getenv("DB_USER"),
        "password": os.getenv("DB_PASSWORD"),
        "database": os.getenv("DB_NAME")
    }

    # Use SSL only when connecting to Aiven/Render
    if db_host != "localhost":
        connection_config["ssl_ca"] = os.path.join(
            os.path.dirname(__file__), "ca", "ca.pem"
        )

    connection = mysql.connector.connect(**connection_config)

    return connection