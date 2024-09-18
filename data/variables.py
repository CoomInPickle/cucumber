"""
Variables Configuration File

This file contains variables used by the application. These variables
can be configured through the .env file or Docker Compose settings.

DO NOT MAKE CHANGES DIRECTLY IN THIS FILE.

Usage:
- Modify .env for local development.
- Adjust Docker Compose for containerized environments.
"""

# Imports
import os
from dotenv import load_dotenv
import datetime


load_dotenv()

# Variables
BOT_TOKEN = os.getenv('BOT_TOKEN')
APPLICATION_ID = os.getenv('APPLICATION_ID')
DEV_USER = None

# Fucntions
def Timestamp():
    stamp = datetime.datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")  # Timestamp for log
    return stamp