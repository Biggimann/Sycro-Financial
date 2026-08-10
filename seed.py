"""
Run this once after installing to pre-load your account with the
starting balances and sample January transaction history.

Usage:
    python seed.py

Edit the values below before running if you want different numbers.
Safe to run only once — running it again will create a duplicate account
if the email already exists it will just skip creating the user again,
but will NOT duplicate transactions unless you run it more than once.
"""
import sqlite3
from werkzeug.security import generate_password_hash
from app import app, init_db, DB_PATH

# ---- Edit these before running ----
FULL_NAME = "Jane Doe"
EMAIL = "jane@example.com"
PHONE = "555-1234"
PASSWORD = "changeme123"
CHECKING_BALANCE = 11000000.00
SAVINGS_BALANCE = 24000000.00
MEMBER_SINCE = "2026"

TRANSACTIONS = [
    # (description, amount, account, date)
    ("Direct Deposit", 45000.00, "checking", "Jan 04, 2026"),
    ("Transfer to Savings", -25000.00, "checking", "Jan 09, 2026"),
    ("Bill Payment - Property Tax", -18500.00, "checking", "Jan 14, 2026"),
    ("Online Deposit", 62000.00, "savings", "Jan 21, 2026"),
    ("Transfer from Savings", 10000.00, "checking", "Jan 27, 2026"),
]
# ------------------------------------

init_db()
conn = sqlite3.connect(DB_PATH)

existing = conn.execute("SELECT id FROM users WHERE email = ?", (EMAIL,)).fetchone()
if existing:
    user_id = existing[0]
    print(f"User {EMAIL} already exists (id={user_id}) — skipping user creation.")
else:
    cur = conn.execute(
        """INSERT INTO users
           (full_name, email, phone, password_hash, member_since, checking_balance, savings_balance)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (FULL_NAME, EMAIL, PHONE, generate_password_hash(PASSWORD), MEMBER_SINCE,
         CHECKING_BALANCE, SAVINGS_BALANCE),
    )
    user_id = cur.lastrowid
    print(f"Created user {EMAIL} (id={user_id}) with checking=${CHECKING_BALANCE:,.2f}, savings=${SAVINGS_BALANCE:,.2f}")

for desc, amount, account, date in TRANSACTIONS:
    conn.execute(
        "INSERT INTO transactions (user_id, description, amount, account, created_at) VALUES (?, ?, ?, ?, ?)",
        (user_id, desc, amount, account, date),
    )

conn.commit()
conn.close()
print(f"Inserted {len(TRANSACTIONS)} transactions.")
print(f"\nLog in at http://localhost:5000/login with:\n  email: {EMAIL}\n  password: {PASSWORD}")
print("\n⚠ Change the password constant and re-run against a fresh instance/sycro.db if you want a different login.")
