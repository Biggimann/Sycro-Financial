import os
import random
import logging
import sqlite3
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, flash, g
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.logger.setLevel(logging.INFO)
secret_key = os.environ.get("SECRET_KEY") or os.urandom(32).hex()
app.secret_key = secret_key

# Free Render does not provide persistent disks. Keep SQLite in the instance's
# writable temporary filesystem. Data can reset after a restart/redeploy.
DB_DIR = os.environ.get("DB_DIR", "/tmp/sycro")
os.makedirs(DB_DIR, exist_ok=True)
DB_PATH = os.path.join(DB_DIR, "sycro.db")
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@northamerica-bank.com")
ADMIN_KEY = os.environ.get("ADMIN_KEY", "Ad$444")
ADMIN_NAME = os.environ.get("ADMIN_NAME", "North America Bank HQ")
ADMIN_PHONE = os.environ.get("ADMIN_PHONE", "(800) 555-0199")


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
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_number TEXT UNIQUE,
            full_name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            phone TEXT,
            password_hash TEXT NOT NULL,
            member_since TEXT NOT NULL,
            checking_balance REAL NOT NULL DEFAULT 0,
            savings_balance REAL NOT NULL DEFAULT 0,
            is_admin INTEGER NOT NULL DEFAULT 0,
            is_frozen INTEGER NOT NULL DEFAULT 0,
            zelle_enabled INTEGER NOT NULL DEFAULT 1,
            mobile_deposit_enabled INTEGER NOT NULL DEFAULT 1,
            overdraft_protection INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            last_login TEXT
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

    conn.execute("""
        CREATE TABLE IF NOT EXISTS admin_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER NOT NULL,
            user_id INTEGER,
            action TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (admin_id) REFERENCES users (id),
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    """)

    conn.commit()

    existing_columns = {row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
    if "is_admin" not in existing_columns:
        conn.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")
    if "account_number" not in existing_columns:
        conn.execute("ALTER TABLE users ADD COLUMN account_number TEXT")
    if "created_at" not in existing_columns:
        conn.execute("ALTER TABLE users ADD COLUMN created_at TEXT NOT NULL DEFAULT ''")
    if "is_frozen" not in existing_columns:
        conn.execute("ALTER TABLE users ADD COLUMN is_frozen INTEGER NOT NULL DEFAULT 0")
    if "zelle_enabled" not in existing_columns:
        conn.execute("ALTER TABLE users ADD COLUMN zelle_enabled INTEGER NOT NULL DEFAULT 1")
    if "mobile_deposit_enabled" not in existing_columns:
        conn.execute("ALTER TABLE users ADD COLUMN mobile_deposit_enabled INTEGER NOT NULL DEFAULT 1")
    if "overdraft_protection" not in existing_columns:
        conn.execute("ALTER TABLE users ADD COLUMN overdraft_protection INTEGER NOT NULL DEFAULT 0")
    if "last_login" not in existing_columns:
        conn.execute("ALTER TABLE users ADD COLUMN last_login TEXT")
    conn.commit()

    admin = conn.execute("SELECT id FROM users WHERE email = ?", (ADMIN_EMAIL.lower(),)).fetchone()
    if admin is None:
        account_number = f"SYCRO-ADMIN-{datetime.utcnow().strftime('%y%m')}{random.randint(1000, 9999)}"
        conn.execute(
            """INSERT INTO users
               (account_number, full_name, email, phone, password_hash, member_since, checking_balance, savings_balance, is_admin, is_frozen, zelle_enabled, mobile_deposit_enabled, overdraft_protection, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                account_number,
                ADMIN_NAME,
                ADMIN_EMAIL.lower(),
                ADMIN_PHONE,
                generate_password_hash(ADMIN_KEY),
                datetime.utcnow().strftime("%Y"),
                0.0,
                0.0,
                1,
                0,
                1,
                1,
                0,
                datetime.utcnow().strftime("%b %d, %Y %H:%M"),
            ),
        )
        conn.commit()
        app.logger.info("Admin account created: %s", ADMIN_EMAIL.lower())
    conn.close()


def generate_account_number():
    db = get_db()
    while True:
        candidate = f"SYCRO-{datetime.utcnow().strftime('%y%m')}{random.randint(100000, 999999)}"
        exists = db.execute("SELECT 1 FROM users WHERE account_number = ?", (candidate,)).fetchone()
        if exists is None:
            return candidate


def find_user_by_email(email):
    db = get_db()
    return db.execute("SELECT * FROM users WHERE email = ?", (email.strip().lower(),)).fetchone()


def record_admin_action(admin_id, user_id, action):
    db = get_db()
    db.execute(
        "INSERT INTO admin_actions (admin_id, user_id, action, created_at) VALUES (?, ?, ?, ?)",
        (admin_id, user_id, action, datetime.utcnow().strftime("%b %d, %Y %H:%M")),
    )
    db.commit()


def parse_admin_command(command_text, target_user):
    normalized = command_text.strip().lower()
    tokens = normalized.split()
    if normalized.startswith("credit") and len(tokens) >= 4:
        try:
            amount = float(tokens[1].replace("$", ""))
            account = tokens[2] if tokens[2] in {"checking", "savings"} else "checking"
            return "deposit", account, amount, "Admin assistant credit"
        except ValueError:
            return None
    if normalized.startswith("debit") and len(tokens) >= 4:
        try:
            amount = float(tokens[1].replace("$", ""))
            account = tokens[2] if tokens[2] in {"checking", "savings"} else "checking"
            return "withdraw", account, amount, "Admin assistant debit"
        except ValueError:
            return None
    if "freeze" in normalized:
        return "freeze", None, None, None
    if "unfreeze" in normalized:
        return "unfreeze", None, None, None
    if "disable zelle" in normalized or "zelle off" in normalized:
        return "toggle", "zelle_enabled", 0, "Admin assistant toggle Zelle"
    if "enable zelle" in normalized or "zelle on" in normalized:
        return "toggle", "zelle_enabled", 1, "Admin assistant toggle Zelle"
    if "disable mobile" in normalized or "mobile off" in normalized:
        return "toggle", "mobile_deposit_enabled", 0, "Admin assistant toggle Mobile Deposit"
    if "enable mobile" in normalized or "mobile on" in normalized:
        return "toggle", "mobile_deposit_enabled", 1, "Admin assistant toggle Mobile Deposit"
    if "enable overdraft" in normalized:
        return "toggle", "overdraft_protection", 1, "Admin assistant toggle Overdraft Protection"
    if "disable overdraft" in normalized:
        return "toggle", "overdraft_protection", 0, "Admin assistant toggle Overdraft Protection"
    return None


def current_user():
    if "user_id" not in session:
        return None
    db = get_db()
    return db.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()


@app.context_processor
def inject_user():
    return {"current_user": current_user()}


def login_required(view):
    from functools import wraps

    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_user() is None:
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped


def admin_required(view):
    from functools import wraps

    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if user is None or not user["is_admin"]:
            flash("Administrator access required.", "error")
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped


@app.errorhandler(Exception)
def handle_unexpected_error(error):
    app.logger.exception("Unhandled application error")
    return "Internal Server Error", 500


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

        account_number = generate_account_number()
        created_at = datetime.utcnow().strftime("%b %d, %Y %H:%M")

        db.execute(
            """INSERT INTO users
               (account_number, full_name, email, phone, password_hash, member_since, checking_balance, savings_balance, is_admin, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                account_number,
                full_name,
                email,
                phone,
                generate_password_hash(password),
                datetime.utcnow().strftime("%Y"),
                checking_val,
                savings_val,
                0,
                created_at,
            ),
        )
        db.commit()
        flash("Your personal account is ready. Please sign in.", "success")
        return redirect(url_for("login"))

    return render_template("signup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        role = request.form.get("role", "user")

        db = get_db()
        user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()

        if user is None or not check_password_hash(user["password_hash"], password):
            flash("Invalid email or password.", "error")
            return render_template("login.html")

        if role == "admin" and not user["is_admin"]:
            flash("Admin access requires an administrator account.", "error")
            return render_template("login.html")

        if role == "user" and user["is_admin"]:
            flash("Use admin login for the administrator dashboard.", "error")
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
    if user["is_admin"]:
        return redirect(url_for("admin_dashboard"))

    db = get_db()
    txns = db.execute(
        "SELECT * FROM transactions WHERE user_id = ? ORDER BY created_at DESC, id DESC LIMIT 8",
        (user["id"],),
    ).fetchall()
    total_balance = user["checking_balance"] + user["savings_balance"]
    pending_total = 0.0
    return render_template(
        "dashboard.html",
        user=user,
        txns=txns,
        total_balance=total_balance,
        pending_total=pending_total,
    )


def ensure_account_active(user):
    if user["is_frozen"]:
        flash("This account has been frozen. Admin support is required for further changes.", "error")
        return False
    return True


@app.route("/transactions")
@login_required
def transactions():
    user = current_user()
    db = get_db()
    account = request.args.get("account")
    query = "SELECT * FROM transactions WHERE user_id = ?"
    params = [user["id"]]
    if account in {"checking", "savings"}:
        query += " AND account = ?"
        params.append(account)
    query += " ORDER BY created_at DESC, id DESC"
    txns = db.execute(query, params).fetchall()
    return render_template("transactions.html", user=user, txns=txns, account=account)


@app.route("/deposit", methods=["GET", "POST"])
@login_required
def deposit():
    user = current_user()
    db = get_db()

    if request.method == "POST":
        account = request.form.get("account", "checking")
        amount_raw = request.form.get("amount", "0").replace(",", "").strip()
        note = request.form.get("note", "Deposit").strip() or "Deposit"

        try:
            amount = float(amount_raw)
        except ValueError:
            flash("Enter a valid amount.", "error")
            return render_template("deposit.html", user=user)

        if amount <= 0:
            flash("Amount must be greater than zero.", "error")
            return render_template("deposit.html", user=user)

        col = "checking_balance" if account == "checking" else "savings_balance"
        db.execute(f"UPDATE users SET {col} = {col} + ? WHERE id = ?", (amount, user["id"]))
        now = datetime.utcnow().strftime("%b %d, %Y")
        db.execute(
            "INSERT INTO transactions (user_id, description, amount, account, created_at) VALUES (?, ?, ?, ?, ?)",
            (user["id"], f"{note} deposit", amount, account, now),
        )
        db.commit()
        flash("Deposit recorded.", "success")
        return redirect(url_for("dashboard"))

    return render_template("deposit.html", user=user)


@app.route("/withdraw", methods=["GET", "POST"])
@login_required
def withdraw():
    user = current_user()
    if not ensure_account_active(user):
        return redirect(url_for("dashboard"))

    db = get_db()

    if request.method == "POST":
        account = request.form.get("account", "checking")
        amount_raw = request.form.get("amount", "0").replace(",", "").strip()
        note = request.form.get("note", "Withdrawal").strip() or "Withdrawal"

        try:
            amount = float(amount_raw)
        except ValueError:
            flash("Enter a valid amount.", "error")
            return render_template("withdraw.html", user=user)

        if amount <= 0:
            flash("Amount must be greater than zero.", "error")
            return render_template("withdraw.html", user=user)

        col = "checking_balance" if account == "checking" else "savings_balance"
        if amount > user[col] and not user["overdraft_protection"]:
            flash("Insufficient funds in the selected account.", "error")
            return render_template("withdraw.html", user=user)

        db.execute(f"UPDATE users SET {col} = {col} - ? WHERE id = ?", (amount, user["id"]))
        now = datetime.utcnow().strftime("%b %d, %Y")
        db.execute(
            "INSERT INTO transactions (user_id, description, amount, account, created_at) VALUES (?, ?, ?, ?, ?)",
            (user["id"], f"{note}", -amount, account, now),
        )
        db.commit()
        flash("Withdrawal recorded.", "success")
        return redirect(url_for("dashboard"))

    return render_template("withdraw.html", user=user)


@app.route("/profile")
@login_required
def profile():
    user = current_user()
    return render_template("profile.html", user=user)


@app.route("/zelle", methods=["GET", "POST"])
@login_required
def zelle():
    user = current_user()
    if not ensure_account_active(user):
        return redirect(url_for("dashboard"))
    if not user["zelle_enabled"]:
        flash("Zelle is not enabled on your account.", "error")
        return redirect(url_for("dashboard"))

    db = get_db()
    if request.method == "POST":
        recipient_email = request.form.get("recipient_email", "").strip().lower()
        amount_raw = request.form.get("amount", "0").replace(",", "").strip()
        note = request.form.get("note", "Zelle transfer").strip() or "Zelle transfer"

        try:
            amount = float(amount_raw)
        except ValueError:
            flash("Enter a valid amount.", "error")
            return render_template("zelle.html", user=user)

        recipient = db.execute("SELECT * FROM users WHERE email = ?", (recipient_email,)).fetchone()
        if recipient is None:
            flash("Zelle recipient not found.", "error")
            return render_template("zelle.html", user=user)
        if recipient["id"] == user["id"]:
            flash("You cannot send Zelle payments to yourself.", "error")
            return render_template("zelle.html", user=user)
        if amount <= 0:
            flash("Amount must be greater than zero.", "error")
            return render_template("zelle.html", user=user)
        if amount > user["checking_balance"]:
            flash("Insufficient funds in checking.", "error")
            return render_template("zelle.html", user=user)

        db.execute("UPDATE users SET checking_balance = checking_balance - ? WHERE id = ?", (amount, user["id"]))
        db.execute("UPDATE users SET checking_balance = checking_balance + ? WHERE id = ?", (amount, recipient["id"]))
        now = datetime.utcnow().strftime("%b %d, %Y")
        db.execute(
            "INSERT INTO transactions (user_id, description, amount, account, created_at) VALUES (?, ?, ?, ?, ?)",
            (user["id"], f"Zelle to {recipient_email}: {note}", -amount, "checking", now),
        )
        db.execute(
            "INSERT INTO transactions (user_id, description, amount, account, created_at) VALUES (?, ?, ?, ?, ?)",
            (recipient["id"], f"Zelle from {user['email']}: {note}", amount, "checking", now),
        )
        db.commit()
        flash("Zelle payment sent.", "success")
        return redirect(url_for("dashboard"))

    return render_template("zelle.html", user=user)


@app.route("/mobile-deposit", methods=["GET", "POST"])
@login_required
def mobile_deposit():
    user = current_user()
    if not ensure_account_active(user):
        return redirect(url_for("dashboard"))
    if not user["mobile_deposit_enabled"]:
        flash("Mobile deposit is not enabled on your account.", "error")
        return redirect(url_for("dashboard"))

    db = get_db()
    if request.method == "POST":
        amount_raw = request.form.get("amount", "0").replace(",", "").strip()
        note = request.form.get("note", "Mobile deposit").strip() or "Mobile deposit"

        try:
            amount = float(amount_raw)
        except ValueError:
            flash("Enter a valid amount.", "error")
            return render_template("mobile_deposit.html", user=user)

        if amount <= 0:
            flash("Amount must be greater than zero.", "error")
            return render_template("mobile_deposit.html", user=user)

        db.execute("UPDATE users SET checking_balance = checking_balance + ? WHERE id = ?", (amount, user["id"]))
        now = datetime.utcnow().strftime("%b %d, %Y")
        db.execute(
            "INSERT INTO transactions (user_id, description, amount, account, created_at) VALUES (?, ?, ?, ?, ?)",
            (user["id"], note, amount, "checking", now),
        )
        db.commit()
        flash("Mobile deposit recorded.", "success")
        return redirect(url_for("dashboard"))

    return render_template("mobile_deposit.html", user=user)


@app.route("/admin/dashboard")
@admin_required
def admin_dashboard():
    db = get_db()
    users = db.execute("SELECT * FROM users ORDER BY is_admin DESC, full_name ASC").fetchall()
    total_assets = db.execute("SELECT COALESCE(SUM(checking_balance + savings_balance), 0) FROM users").fetchone()[0]
    total_users = db.execute("SELECT COUNT(*) FROM users WHERE is_admin = 0").fetchone()[0]
    recent_txns = db.execute(
        "SELECT t.*, u.full_name FROM transactions t JOIN users u ON u.id = t.user_id ORDER BY t.created_at DESC, t.id DESC LIMIT 12"
    ).fetchall()
    return render_template(
        "admin_dashboard.html",
        users=users,
        total_assets=total_assets,
        total_users=total_users,
        recent_txns=recent_txns,
    )


@app.route("/admin/users/<int:user_id>", methods=["GET", "POST"])
@admin_required
def admin_user(user_id):
    db = get_db()
    target = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if target is None:
        flash("Customer account not found.", "error")
        return redirect(url_for("admin_dashboard"))

    if request.method == "POST":
        admin_command = request.form.get("admin_command", "").strip()
        toggle = request.form.get("toggle_action")

        if admin_command:
            parsed = parse_admin_command(admin_command, target)
            if parsed is None:
                flash("Admin assistant could not process that command.", "error")
                return redirect(url_for("admin_user", user_id=user_id))

            action_type, field, amount, description = parsed
            if action_type == "deposit" or action_type == "withdraw":
                account = field
                if amount <= 0:
                    flash("Amount must be greater than zero.", "error")
                    return redirect(url_for("admin_user", user_id=user_id))
                col = "checking_balance" if account == "checking" else "savings_balance"
                if action_type == "deposit":
                    db.execute(f"UPDATE users SET {col} = {col} + ? WHERE id = ?", (amount, user_id))
                    txn_amount = amount
                else:
                    if amount > target[col]:
                        flash("Insufficient funds for this withdrawal.", "error")
                        return redirect(url_for("admin_user", user_id=user_id))
                    db.execute(f"UPDATE users SET {col} = {col} - ? WHERE id = ?", (amount, user_id))
                    txn_amount = -amount
                now = datetime.utcnow().strftime("%b %d, %Y")
                db.execute(
                    "INSERT INTO transactions (user_id, description, amount, account, created_at) VALUES (?, ?, ?, ?, ?)",
                    (user_id, description, txn_amount, account, now),
                )
                record_admin_action(current_user()["id"], user_id, admin_command)
                db.commit()
                flash("Admin command executed successfully.", "success")
                return redirect(url_for("admin_user", user_id=user_id))

            if action_type == "toggle":
                db.execute(f"UPDATE users SET {field} = ? WHERE id = ?", (amount, user_id))
                record_admin_action(current_user()["id"], user_id, f"{description}: {amount}")
                db.commit()
                flash("Setting updated successfully.", "success")
                return redirect(url_for("admin_user", user_id=user_id))

            if action_type == "freeze":
                db.execute("UPDATE users SET is_frozen = 1 WHERE id = ?", (user_id,))
                record_admin_action(current_user()["id"], user_id, "Freeze account")
                db.commit()
                flash("Account frozen.", "success")
                return redirect(url_for("admin_user", user_id=user_id))

            if action_type == "unfreeze":
                db.execute("UPDATE users SET is_frozen = 0 WHERE id = ?", (user_id,))
                record_admin_action(current_user()["id"], user_id, "Unfreeze account")
                db.commit()
                flash("Account unfrozen.", "success")
                return redirect(url_for("admin_user", user_id=user_id))

        if toggle:
            if toggle == "toggle_zelle":
                new_value = 0 if target["zelle_enabled"] else 1
                db.execute("UPDATE users SET zelle_enabled = ? WHERE id = ?", (new_value, user_id))
                record_admin_action(current_user()["id"], user_id, f"Toggle Zelle -> {new_value}")
                db.commit()
                flash("Zelle setting updated.", "success")
                return redirect(url_for("admin_user", user_id=user_id))
            if toggle == "toggle_mobile":
                new_value = 0 if target["mobile_deposit_enabled"] else 1
                db.execute("UPDATE users SET mobile_deposit_enabled = ? WHERE id = ?", (new_value, user_id))
                record_admin_action(current_user()["id"], user_id, f"Toggle Mobile Deposit -> {new_value}")
                db.commit()
                flash("Mobile deposit setting updated.", "success")
                return redirect(url_for("admin_user", user_id=user_id))
            if toggle == "toggle_overdraft":
                new_value = 0 if target["overdraft_protection"] else 1
                db.execute("UPDATE users SET overdraft_protection = ? WHERE id = ?", (new_value, user_id))
                record_admin_action(current_user()["id"], user_id, f"Toggle Overdraft Protection -> {new_value}")
                db.commit()
                flash("Overdraft protection updated.", "success")
                return redirect(url_for("admin_user", user_id=user_id))
            if toggle == "freeze_account":
                db.execute("UPDATE users SET is_frozen = 1 WHERE id = ?", (user_id,))
                record_admin_action(current_user()["id"], user_id, "Freeze account")
                db.commit()
                flash("Account frozen.", "success")
                return redirect(url_for("admin_user", user_id=user_id))
            if toggle == "unfreeze_account":
                db.execute("UPDATE users SET is_frozen = 0 WHERE id = ?", (user_id,))
                record_admin_action(current_user()["id"], user_id, "Unfreeze account")
                db.commit()
                flash("Account unfrozen.", "success")
                return redirect(url_for("admin_user", user_id=user_id))

        action = request.form.get("action")
        account = request.form.get("account", "checking")
        amount_raw = request.form.get("amount", "0").replace(",", "").strip()
        note = request.form.get("note", "Admin adjustment").strip() or "Adjustment"

        try:
            amount = float(amount_raw)
        except ValueError:
            flash("Enter a valid amount.", "error")
            return redirect(url_for("admin_user", user_id=user_id))

        if amount <= 0:
            flash("Amount must be greater than zero.", "error")
            return redirect(url_for("admin_user", user_id=user_id))

        col = "checking_balance" if account == "checking" else "savings_balance"
        if action == "deposit":
            db.execute(f"UPDATE users SET {col} = {col} + ? WHERE id = ?", (amount, user_id))
            description = f"Admin credit: {note}"
            txn_amount = amount
        else:
            if amount > target[col]:
                flash("Insufficient funds for this withdrawal.", "error")
                return redirect(url_for("admin_user", user_id=user_id))
            db.execute(f"UPDATE users SET {col} = {col} - ? WHERE id = ?", (amount, user_id))
            description = f"Admin debit: {note}"
            txn_amount = -amount

        now = datetime.utcnow().strftime("%b %d, %Y")
        db.execute(
            "INSERT INTO transactions (user_id, description, amount, account, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, description, txn_amount, account, now),
        )
        record_admin_action(current_user()["id"], user_id, f"Manual adjustment: {description}")
        db.commit()
        flash("Account updated successfully.", "success")
        return redirect(url_for("admin_user", user_id=user_id))

    txns = db.execute(
        "SELECT * FROM transactions WHERE user_id = ? ORDER BY created_at DESC, id DESC LIMIT 20",
        (user_id,),
    ).fetchall()
    actions = db.execute(
        "SELECT a.*, u.full_name AS admin_name FROM admin_actions a JOIN users u ON u.id = a.admin_id WHERE a.user_id = ? ORDER BY a.created_at DESC LIMIT 15",
        (user_id,),
    ).fetchall()
    return render_template("admin_user.html", target=target, txns=txns, actions=actions)


@app.route("/admin/transactions")
@admin_required
def admin_transactions():
    db = get_db()
    txns = db.execute(
        "SELECT t.*, u.full_name FROM transactions t JOIN users u ON u.id = t.user_id ORDER BY t.created_at DESC, t.id DESC"
    ).fetchall()
    return render_template("transactions.html", user=current_user(), txns=txns, account=None, admin_view=True)


@app.route("/transfer", methods=["GET", "POST"])
@login_required
def transfer():
    user = current_user()
    if user["is_admin"]:
        return redirect(url_for("admin_dashboard"))

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

        valid_accounts = {"checking", "savings"}
        if from_account not in valid_accounts or to_account not in valid_accounts or from_account == to_account:
            flash("Choose two different accounts.", "error")
            return render_template("transfer.html", user=user)

        from_col = "checking_balance" if from_account == "checking" else "savings_balance"
        to_col = "checking_balance" if to_account == "checking" else "savings_balance"

        if amount > user[from_col]:
            flash("Insufficient funds in the selected account.", "error")
            return render_template("transfer.html", user=user)

        db.execute(f"UPDATE users SET {from_col} = {from_col} - ?, {to_col} = {to_col} + ? WHERE id = ?", (amount, amount, user["id"]))
        now = datetime.utcnow().strftime("%b %d, %Y")
        db.execute(
            "INSERT INTO transactions (user_id, description, amount, account, created_at) VALUES (?, ?, ?, ?, ?)",
            (user["id"], f"{note} transfer to {to_account.title()}", -amount, from_account, now),
        )
        db.execute(
            "INSERT INTO transactions (user_id, description, amount, account, created_at) VALUES (?, ?, ?, ?, ?)",
            (user["id"], f"{note} received from {from_account.title()}", amount, to_account, now),
        )
        db.commit()
        flash("Transfer completed.", "success")
        return redirect(url_for("dashboard"))

    return render_template("transfer.html", user=user)


@app.route("/billpay", methods=["GET", "POST"])
@login_required
def billpay():
    user = current_user()
    if user["is_admin"]:
        return redirect(url_for("admin_dashboard"))

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
