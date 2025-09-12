import sys
import pandas
import binance
import dotenv
import sqlalchemy

print("--- sys.path ---")
for p in sys.path:
    print(p)

print("\n--- Module Locations ---")
print(f"pandas: {pandas.__file__}")
print(f"binance: {binance.__file__}")
print(f"dotenv: {dotenv.__file__}")
print(f"sqlalchemy: {sqlalchemy.__file__}")
