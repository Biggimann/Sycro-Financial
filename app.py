import sqlite3
import os
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, flash, g
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
secret_key = os.environ.get("SECRET_KEY")
if not secret_key:
    raise RuntimeError("SECRET_KEY environment variable is required.")
app.secret_key = secret_key

# Render Disk (recommended) can be mounted anywhere; this defaults to instance/.
DB_DIR = os.environ.get("DB_DIR", app.instance_path)
os.makedirs(DB_DIR, exist_ok=True)
DB_PATH = os.path.join(DB_DIR, "sycro.db")

os.makedirs(app.instance_path, exist_ok=True)


# ---------- Database helpers ----------

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            phone TEXT,
            password_hash TEXT NOT NULL,
            member_since TEXT NOT NULL,
            checking_balance REAL NOT NULL DEFAULT 0,
            savings_balance REAL NOT NULL DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            description TEXT NOT NULL,
            amount REAL NOT NULL,
            account TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    """)
    conn.commit()
    conn.close()


# ---------- Auth helpers ----------

def current_user():
    if "user_id" not in session:
        return None
    db = get_db()
    return db.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()


def login_required(view):
    from functools import wraps

    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_user() is None:
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


@app.route("/health", methods=["GET"])
def health():
    return {"status": "ok"}, 200


# ---------- Routes: Auth ----------

@app.route("/", methods=["GET"])
def index():
    if current_user():
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/signup", methods=["GET", "POST"])
def signup():
    # Single-user personal account creation. Remove/disable this route
    # once your own account is created if you want it locked to just you.
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "")
        checking = request.form.get("checking_balance", "0").replace(",", "").strip()
        savings = request.form.get("savings_balance", "0").replace(",", "").strip()

        if not full_name or not email or not password:
            flash("Full name, email, and password are required.", "error")
            return render_template("signup.html")

        try:
            checking_val = float(checking) if checking else 0.0
            savings_val = float(savings) if savings else 0.0
        except ValueError:
            flash("Balances must be numbers.", "error")
            return render_template("signup.html")

        db = get_db()
        existing = db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if existing:
            flash("An account with that email already exists.", "error")
            return render_template("signup.html")

        db.execute(
            """INSERT INTO users
               (full_name, email, phone, password_hash, member_since, checking_balance, savings_balance)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                full_name,
                email,
                phone,
                generate_password_hash(password),
                datetime.utcnow().strftime("%Y"),
                checking_val,
                savings_val,
            ),
        )
        db.commit()
        flash("Account created. Please sign in.", "success")
        return redirect(url_for("login"))

    return render_template("signup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        db = get_db()
        user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()

        if user is None or not check_password_hash(user["password_hash"], password):
            flash("Invalid email or password.", "error")
            return render_template("login.html")

        session["user_id"] = user["id"]
        return redirect(url_for("dashboard"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------- Routes: App ----------

@app.route("/dashboard")
@login_required
def dashboard():
    user = current_user()
    db = get_db()
    txns = db.execute(
        "SELECT * FROM transactions WHERE user_id = ? ORDER BY id DESC LIMIT 8",
        (user["id"],),
    ).fetchall()
    pending_total = 0.0  # no fabricated pending bucket — reflects real state only
    return render_template("dashboard.html", user=user, txns=txns, pending_total=pending_total)


@app.route("/profile")
@login_required
def profile():
    user = current_user()
    return render_template("profile.html", user=user)


@app.route("/transfer", methods=["GET", "POST"])
@login_required
def transfer():
    user = current_user()
    db = get_db()

    if request.method == "POST":
        from_account = request.form.get("from_account")
        to_account = request.form.get("to_account")
        amount_raw = request.form.get("amount", "0").replace(",", "").strip()
        note = request.form.get("note", "").strip() or "Transfer"

        try:
            amount = float(amount_raw)
        except ValueError:
            flash("Enter a valid amount.", "error")
            return render_template("transfer.html", user=user)

        if amount <= 0:
            flash("Amount must be greater than zero.", "error")
            return render_template("transfer.html", user=user)

        if from_account == to_account:
            flash("Choose two different accounts.", "error")
            return render_template("transfer.html", user=user)

        from_col = "checking_balance" if from_account == "checking" else "savings_balance"
        to_col = "checking_balance" if to_account == "checking" else "savings_balance"

        current_from = user[from_col]
        if amount > current_from:
            flash("Insufficient funds in the selected account.", "error")
            return render_template("transfer.html", user=user)

        db.execute(
            f"UPDATE users SET {from_col} = {from_col} - ?, {to_col} = {to_col} + ? WHERE id = ?",
            (amount, amount, user["id"]),
        )
        now = datetime.utcnow().strftime("%b %d, %Y")
        db.execute(
            "INSERT INTO transactions (user_id, description, amount, account, created_at) VALUES (?, ?, ?, ?, ?)",
            (user["id"], f"{note} → {to_account.title()}", -amount, from_account, now),
        )
        db.execute(
            "INSERT INTO transactions (user_id, description, amount, account, created_at) VALUES (?, ?, ?, ?, ?)",
            (user["id"], f"{note} ← {from_account.title()}", amount, to_account, now),
        )
        db.commit()
        flash("Transfer completed.", "success")
        return redirect(url_for("dashboard"))

    return render_template("transfer.html", user=user)


@app.route("/billpay", methods=["GET", "POST"])
@login_required
def billpay():
    user = current_user()
    db = get_db()

    if request.method == "POST":
        payee = request.form.get("payee", "").strip()
        account = request.form.get("account", "checking")
        amount_raw = request.form.get("amount", "0").replace(",", "").strip()

        try:
            amount = float(amount_raw)
        except ValueError:
            flash("Enter a valid amount.", "error")
            return render_template("billpay.html", user=user)

        if not payee or amount <= 0:
            flash("Enter a payee and a valid amount.", "error")
            return render_template("billpay.html", user=user)

        col = "checking_balance" if account == "checking" else "savings_balance"
        if amount > user[col]:
            flash("Insufficient funds in the selected account.", "error")
            return render_template("billpay.html", user=user)

        db.execute(f"UPDATE users SET {col} = {col} - ? WHERE id = ?", (amount, user["id"]))
        now = datetime.utcnow().strftime("%b %d, %Y")
        db.execute(
            "INSERT INTO transactions (user_id, description, amount, account, created_at) VALUES (?, ?, ?, ?, ?)",
            (user["id"], f"Bill Payment – {payee}", -amount, account, now),
        )
        db.commit()
        flash(f"Payment to {payee} sent.", "success")
        return redirect(url_for("dashboard"))

    return render_template("billpay.html", user=user)


# Initialize the SQLite schema both locally and when imported by Gunicorn.
# This is required because production WSGI servers import `app` instead of
# executing this module as a script.
init_db()

if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
