from flask import Flask, request, jsonify, render_template, redirect, session, send_file
from flask_cors import CORS
from datetime import datetime, timedelta
from scheduler import solve_shift_schedule
import sqlite3
import pandas as pd
import io

# =============================================================================
# App setup
# =============================================================================

app = Flask(__name__)
CORS(app)
app.secret_key = "change-me-please"


# =============================================================================
# DB helpers
# =============================================================================

def connect():
    """Open SQLite with FK enforcement ON for this connection + Row dicts."""
    conn = sqlite3.connect('schedule.db')
    conn.execute('PRAGMA foreign_keys = ON')
    conn.row_factory = sqlite3.Row
    return conn

def get_company_id_from_request():
    """Priority: session -> querystring -> JSON body."""
    cid = session.get('company_id')
    if cid:
        return cid
    cid = request.args.get('company_id')
    if cid:
        return cid
    data = request.get_json(silent=True) or {}
    return data.get('company_id')

def _get_company_id_for_manager(manager_id: str):
    """Bring company_id for a manager, or None."""
    if not manager_id:
        return None
    conn = connect()
    try:
        c = conn.cursor()
        c.execute(
            "SELECT company_id FROM workers WHERE worker_id = ? AND role = 'manager'",
            (manager_id,)
        )
        row = c.fetchone()
        return row[0] if row and row[0] is not None else None
    finally:
        conn.close()


# =============================================================================
# DB init + upgrade (with FK CASCADE migration for constraints)
# =============================================================================

def init_db():
    conn = connect()
    c = conn.cursor()

    # shifts
    c.execute('''
        CREATE TABLE IF NOT EXISTS shifts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            day TEXT,
            time TEXT,
            employee TEXT,
            week TEXT,
            company_id INTEGER
        )
    ''')

    # workers
    c.execute('''
        CREATE TABLE IF NOT EXISTS workers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            password TEXT,
            role TEXT,
            worker_id TEXT,
            id_number TEXT,
            phone TEXT,
            email TEXT,
            company_id INTEGER,
            company_name TEXT
        )
    ''')

    # constraints (new table includes FK; upgrade_db will rebuild older ones)
    c.execute('''
        CREATE TABLE IF NOT EXISTS constraints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            worker_id TEXT NOT NULL,
            day TEXT,
            time TEXT,
            FOREIGN KEY (worker_id) REFERENCES workers(worker_id) ON DELETE CASCADE
        )
    ''')

    # messages
    c.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            worker_id TEXT,
            content TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # attendance
    c.execute('''
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            worker_id TEXT,
            check_in TEXT,
            check_out TEXT
        )
    ''')

    # shift_times (optional)
    c.execute('''
        CREATE TABLE IF NOT EXISTS shift_times (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            worker_id TEXT,
            check_in TEXT,
            check_out TEXT
        )
    ''')

    # companies
    c.execute('''
        CREATE TABLE IF NOT EXISTS companies (
            company_id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_name TEXT NOT NULL UNIQUE
        )
    ''')

    # shift_types
    c.execute('''
        CREATE TABLE IF NOT EXISTS shift_types (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL
        )
    ''')

    # default companies
    count = c.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
    if count == 0:
        c.executemany(
            "INSERT INTO companies (company_name) VALUES (?)",
            [('מסעדה',), ('שמירה',), ('בית חולים',)]
        )

    # default manager (company 1)
    exists = c.execute("SELECT 1 FROM workers WHERE role='manager' AND worker_id='10' LIMIT 1").fetchone()
    if not exists:
        c.execute("""
            INSERT INTO workers (name, password, role, worker_id, company_id, company_name)
            VALUES (?, ?, ?, ?, ?, ?)
        """, ("adam", "4324", "manager", "10", 1, 'מסעדה'))

    conn.commit()
    conn.close()


def upgrade_db():
    """Add columns/indexes safely and rebuild constraints with FK CASCADE if needed."""
    conn = connect()
    c = conn.cursor()

    # workers: add columns if missing
    for col, typ in {
        "id_number": "TEXT",
        "phone": "TEXT",
        "email": "TEXT",
        "company_id": "TEXT",
        "company_name": "TEXT",
    }.items():
        try:
            c.execute(f"ALTER TABLE workers ADD COLUMN {col} {typ}")
        except sqlite3.OperationalError:
            pass

    # shifts: add columns if missing
    for col, typ in {"company_id": "TEXT", "week": "TEXT"}.items():
        try:
            c.execute(f"ALTER TABLE shifts ADD COLUMN {col} {typ}")
        except sqlite3.OperationalError:
            pass

    # messages: add flags if missing
    try: c.execute("ALTER TABLE messages ADD COLUMN is_read INTEGER DEFAULT 0")
    except sqlite3.OperationalError: pass
    try: c.execute("ALTER TABLE messages ADD COLUMN is_deleted INTEGER DEFAULT 0")
    except sqlite3.OperationalError: pass
    c.execute("UPDATE messages SET is_read=0 WHERE is_read IS NULL")
    c.execute("UPDATE messages SET is_deleted=0 WHERE is_deleted IS NULL")

    # indexes
    c.execute("CREATE INDEX IF NOT EXISTS idx_workers_company_id ON workers(company_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_workers_role_company ON workers(role, company_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_shifts_week_company ON shifts(week, company_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_messages_worker ON messages(worker_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_messages_flags ON messages(is_read, is_deleted)")

    # one-time migration: ensure constraints has FK with CASCADE
        # ---- ONE-TIME MIGRATION: rebuild constraints with FK + CASCADE ----
    try:
        # Check if constraints already has a foreign key defined
        has_fk = False
        for _ in c.execute("PRAGMA foreign_key_list(constraints)"):
            has_fk = True
            break

        if not has_fk:
            # Finish any implicit transaction before we do manual DDL
            conn.commit()

            # Temporarily disable FK checks during table rebuild
            c.execute("PRAGMA foreign_keys=OFF")

            # Do the rebuild in one script (no nested BEGIN)
            c.executescript("""
                CREATE TABLE IF NOT EXISTS constraints_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    worker_id TEXT NOT NULL,
                    day TEXT,
                    time TEXT,
                    FOREIGN KEY (worker_id) REFERENCES workers(worker_id) ON DELETE CASCADE
                );

                INSERT INTO constraints_new (id, worker_id, day, time)
                SELECT c.id, c.worker_id, c.day, c.time
                FROM constraints c
                WHERE EXISTS (SELECT 1 FROM workers w WHERE w.worker_id = c.worker_id);

                DROP TABLE constraints;
                ALTER TABLE constraints_new RENAME TO constraints;
                CREATE INDEX IF NOT EXISTS idx_constraints_worker ON constraints(worker_id);
            """)

            conn.commit()
            c.execute("PRAGMA foreign_keys=ON")
    except sqlite3.OperationalError:
        # Fresh DB or older schema edge-cases: safe to ignore
        pass

    conn.commit()
    conn.close()



# =============================================================================
# Page routes (templates only)
# =============================================================================

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/manager')
def manager():
    return render_template('manager.html')

@app.route('/worker')
def worker():
    return render_template('worker.html')

@app.route('/workers_list')
def workers_list():
    return render_template('workers_list.html')

@app.route('/shift_timer')
def shift_timer():
    return render_template("shift_timer.html")

@app.route('/constraints')
def constraints_page():
    return render_template('view_constraints.html', is_manager=True)

@app.route("/attendance_report")
def attendance_report():
    return render_template("attendance_report.html")

@app.route('/view_schedule')
def view_schedule():
    week = request.args.get('week', 'current')
    return render_template("view_schedule.html", week=week)

@app.route('/add_worker_form', methods=['GET'])
def add_worker_form():
    return render_template('add_worker.html')


# =============================================================================
# Utility endpoints
# =============================================================================

@app.route('/get_week_dates')
def get_week_dates():
    week = request.args.get('week', 'current')  # 'current' or 'next'
    today = datetime.now().date()
    # start from last Sunday (Hebrew week)
    start_of_week = today - timedelta(days=(today.weekday() + 1) % 7)
    if week == 'next':
        start_of_week += timedelta(days=7)
    week_dates = [(start_of_week + timedelta(days=i)).strftime('%d/%m') for i in range(7)]
    return jsonify(week_dates)

@app.route('/debug_constraints')
def debug_constraints():
    conn = connect()
    rows = conn.execute("SELECT * FROM constraints").fetchall()
    conn.close()
    return "<br>".join(str(dict(row)) for row in rows)


# =============================================================================
# Auth / Register
# =============================================================================

@app.route('/register_manager', methods=['POST'])
def register_manager():
    data = request.get_json() or {}
    name = (data.get('name') or '').strip()
    password = data.get('password') or ''
    company_name = (data.get('company_name') or '').strip()

    if not name or not password or not company_name:
        return jsonify({"success": False, "message": "שם, סיסמה ושם חברה – חובה"}), 400

    conn = connect()
    c = conn.cursor()

    # ensure company_id
    try:
        c.execute("SELECT company_id FROM companies WHERE company_name = ?", (company_name,))
        row = c.fetchone()
        if row:
            company_id = row[0]
        else:
            c.execute("INSERT INTO companies (company_name) VALUES (?)", (company_name,))
            company_id = c.lastrowid
    except sqlite3.OperationalError:
        # fallback if companies table missing
        max_cid = c.execute("SELECT MAX(COALESCE(company_id,0)) FROM workers").fetchone()[0] or 0
        company_id = max_cid + 1

    # next worker_id
    max_id = c.execute("SELECT MAX(CAST(worker_id AS INTEGER)) FROM workers").fetchone()[0]
    new_worker_id = str((int(max_id) if max_id is not None else 9) + 1)

    c.execute("""
        INSERT INTO workers (name, password, role, worker_id, company_id, company_name)
        VALUES (?, ?, 'manager', ?, ?, ?)
    """, (name, password, new_worker_id, company_id, company_name))

    conn.commit()
    conn.close()

    return jsonify({
        "success": True,
        "manager_id": new_worker_id,
        "company_id": company_id,
        "company_name": company_name
    }), 201


@app.route('/login_manager', methods=['POST'])
def login_manager():
    data = request.get_json() or {}
    worker_id = data.get('worker_id')
    password  = data.get('password')

    if not worker_id or not password:
        return jsonify(success=False, message='חסרים פרטים'), 400

    conn = connect()
    c = conn.cursor()
    c.execute("""
        SELECT worker_id, name, company_id, company_name
        FROM workers
        WHERE worker_id = ? AND password = ? AND role = 'manager'
    """, (worker_id, password))
    row = c.fetchone()
    conn.close()

    if not row:
        return jsonify(success=False, message="פרטי התחברות שגויים"), 401

    session['manager_id'] = row[0]
    session['manager_name'] = row[1] 
    session['company_id'] = row[2]
    session['company_name'] = row[3]

    return jsonify(
        success=True,
        manager_id=row[0],
        name=row[1],  
        company_id=row[2], 
        company_name=row[3])


@app.route('/login_worker', methods=['POST'])
def login_worker():
    data = request.get_json() or {}
    worker_id = (data.get('worker_id') or '').strip()
    password  = (data.get('password')  or '').strip()

    if not worker_id or not password:
        return jsonify(success=False, message='חסרים פרטים'), 400

    conn = connect()
    c = conn.cursor()
    # allow only role='worker'
    c.execute("""
        SELECT password, company_id, company_name, name
        FROM workers
        WHERE worker_id = ? AND role = 'worker'
    """, (worker_id,))
    row = c.fetchone()
    conn.close()

    if not row:
        return jsonify({"success": False, "message": "לא נמצא עובד עם מזהה זה"}), 404

    db_password, company_id, company_name, worker_name = row
    if db_password != password:
        return jsonify({"success": False, "message": "סיסמה שגויה"}), 401

    return jsonify({
        "success": True,
        "message": "התחברות הצליחה",
        "company_id": company_id,
        "company_name": company_name,
        "name": worker_name or ""
    }), 200


# =============================================================================
# Workers CRUD
# =============================================================================

@app.route('/add_worker', methods=['POST'])
def add_worker():
    data = request.get_json() or {}
    name = (data.get('name') or '').strip()
    password = data.get('password') or ''
    role = (data.get('role') or 'worker').strip().lower()
    id_number = data.get('id_number') or ''
    phone = data.get('phone') or ''
    email = data.get('email') or ''

    if not name or role not in ('worker', 'manager'):
        return jsonify({"message": "שם חובה ותפקיד חייב להיות worker או manager"}), 400

    company_id = session.get('company_id') or data.get('company_id')
    company_name = session.get('company_name') or data.get('company_name')
    if not company_id:
        return jsonify({"message": "חסרים פרטי חברה. התחבר/י מחדש או שלח/י company_id ו company_name בבקשה."}), 400

    conn = connect()
    c = conn.cursor()

    # If a manager is logged in, trust their company data
    manager_id = session.get('manager_id')
    if manager_id:
        c.execute("""
            SELECT company_id, company_name
            FROM workers
            WHERE worker_id = ? AND role = 'manager'
            LIMIT 1
        """, (manager_id,))
        row = c.fetchone()
        if row:
            company_id, company_name = row[0], row[1]

    # next worker_id
    max_id = c.execute("SELECT MAX(CAST(worker_id AS INTEGER)) FROM workers").fetchone()[0]
    new_worker_id = str((int(max_id) if max_id is not None else 9) + 1)

    c.execute("""
        INSERT INTO workers
            (name, password, role, worker_id, id_number, phone, email, company_id, company_name)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (name, password, role, new_worker_id, id_number, phone, email, str(company_id), company_name))

    conn.commit()
    conn.close()

    return jsonify({
        "message": f"{'מנהל' if role=='manager' else 'עובד'} נוסף בהצלחה",
        "worker_id": new_worker_id,
        "company_id": company_id,
        "company_name": company_name
    }), 201


@app.route('/get_workers', methods=['GET'])
def get_workers():
    cid = get_company_id_from_request()
    if not cid:
        return jsonify([]), 200

    conn = connect()
    c = conn.cursor()
    c.execute("""
        SELECT worker_id, name, role, id_number, phone, email, company_id
        FROM workers
        WHERE company_id = ?
        ORDER BY CAST(worker_id AS INTEGER)
    """, (cid,))
    rows = c.fetchall()
    conn.close()

    return jsonify([
        {
            "worker_id": r["worker_id"],
            "name": r["name"],
            "role": r["role"],
            "id_number": r["id_number"],
            "phone": r["phone"],
            "email": r["email"],
            "company_id": r["company_id"],
        } for r in rows
    ])


@app.route('/delete_worker/<worker_id>', methods=['DELETE'])
def delete_worker(worker_id):
    conn = connect()
    c = conn.cursor()
    c.execute("DELETE FROM workers WHERE worker_id = ?", (worker_id,))
    conn.commit()
    conn.close()
    return jsonify({"message": f"עובד עם מזהה {worker_id} נמחק בהצלחה"})


@app.route('/update_worker_field', methods=['POST'])
def update_worker_field():
    data = request.get_json() or {}
    worker_id = data.get('worker_id')
    field = data.get('field')
    value = data.get('value')

    if field not in ['id_number', 'phone', 'email']:
        return jsonify({"error": "Invalid field"}), 400

    conn = connect()
    c = conn.cursor()
    c.execute(f"UPDATE workers SET {field} = ? WHERE worker_id = ?", (value, worker_id))
    conn.commit()
    conn.close()
    return jsonify({"message": "עודכן בהצלחה"})


# =============================================================================
# Messages
# =============================================================================

@app.route('/send_message', methods=['POST'])
def send_message():
    data = request.get_json() or {}
    worker_id = data.get('worker_id')
    content   = data.get('content')

    if not worker_id or not content:
        return jsonify({'success': False, 'message': 'שדות חסרים'}), 400

    try:
        conn = connect()
        c = conn.cursor()
        c.execute("""
            INSERT INTO messages (worker_id, content, timestamp, is_read, is_deleted)
            VALUES (?, ?, datetime('now', 'localtime'), 0, 0)
        """, (worker_id, content))
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except sqlite3.IntegrityError:
        return jsonify({'success': False, 'message': 'שגיאה בשליחה למסד הנתונים'}), 500


@app.route('/get_messages', methods=['GET'])
def get_messages():
    company_id = request.args.get('company_id')
    show = (request.args.get('show') or 'unread').lower()  # 'unread' or 'all'

    conn = connect()
    c = conn.cursor()

    base_sql = """
        SELECT m.id, m.worker_id, m.content, m.timestamp, w.name, m.is_read, m.is_deleted
        FROM messages m
        LEFT JOIN workers w ON m.worker_id = w.worker_id
    """
    where, params = [], []

    if company_id:
        where.append("w.company_id = ?")
        params.append(company_id)
    where.append("m.is_deleted = 0")
    if show != 'all':
        where.append("m.is_read = 0")

    if where:
        base_sql += " WHERE " + " AND ".join(where)
    base_sql += " ORDER BY m.timestamp DESC"

    rows = c.execute(base_sql, params).fetchall()
    conn.close()

    return jsonify([
        {
            "id": r[0],
            "worker_id": r[1],
            "content": r[2],
            "timestamp": r[3],
            "name": r[4] or "לא ידוע",
            "is_read": bool(r[5]),
            "is_deleted": bool(r[6]),
        } for r in rows
    ])


@app.route('/get_messages_by_worker/<worker_id>')
def get_messages_by_worker(worker_id):
    include_deleted = request.args.get('include_deleted', '0') == '1'
    conn = connect()
    c = conn.cursor()
    if include_deleted:
        c.execute("""
            SELECT id, worker_id, content, timestamp,
                   COALESCE(is_read, 0), COALESCE(is_deleted, 0)
            FROM messages
            WHERE worker_id = ?
            ORDER BY datetime(timestamp) DESC
        """, (worker_id,))
    else:
        c.execute("""
            SELECT id, worker_id, content, timestamp,
                   COALESCE(is_read, 0), COALESCE(is_deleted, 0)
            FROM messages
            WHERE worker_id = ? AND COALESCE(is_deleted, 0) = 0
            ORDER BY datetime(timestamp) DESC
        """, (worker_id,))
    rows = c.fetchall()
    conn.close()

    return jsonify([
        {
            "id": r[0],
            "worker_id": r[1],
            "content": r[2],
            "timestamp": r[3],
            "is_read": bool(r[4]),
            "is_deleted": bool(r[5]),
        } for r in rows
    ])


@app.route('/get_my_messages/<worker_id>')
def get_my_messages(worker_id):
    conn = connect()
    rows = conn.execute("""
        SELECT id, content, timestamp
        FROM messages
        WHERE worker_id = ? AND is_read = 0 AND is_deleted = 0
        ORDER BY timestamp DESC
    """, (worker_id,)).fetchall()
    conn.close()
    return jsonify([{'id': r[0], 'content': r[1], 'timestamp': r[2]} for r in rows])

@app.route('/mark_message_read/<int:message_id>', methods=['POST'])
def mark_message_read(message_id):
    conn = connect()
    conn.execute("UPDATE messages SET is_read = 1 WHERE id = ?", (message_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/delete_message/<int:message_id>', methods=['DELETE'])
def delete_message(message_id):
    conn = connect()
    conn.execute("UPDATE messages SET is_deleted = 1 WHERE id = ?", (message_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


# =============================================================================
# Attendance
# =============================================================================

@app.route('/all_attendance')
def all_attendance():
    company_id = request.args.get('company_id')
    conn = connect()
    c = conn.cursor()
    if company_id:
        c.execute("""
            SELECT a.worker_id, w.name, a.check_in, a.check_out
            FROM attendance a
            JOIN workers w ON a.worker_id = w.worker_id
            WHERE w.company_id = ?
            ORDER BY a.check_in DESC
        """, (company_id,))
    else:
        c.execute("""
            SELECT a.worker_id, w.name, a.check_in, a.check_out
            FROM attendance a
            JOIN workers w ON a.worker_id = w.worker_id
            ORDER BY a.check_in DESC
        """)
    data = c.fetchall()
    conn.close()
    return jsonify([
        {"worker_id": row[0], "name": row[1], "check_in": row[2], "check_out": row[3]}
        for row in data
    ])

@app.route('/get_attendance')
def get_attendance():
    cid = get_company_id_from_request()
    if not cid:
        return jsonify([]), 200
    conn = connect()
    rows = conn.execute('''
        SELECT w.worker_id, w.name, a.check_in, a.check_out
        FROM attendance a
        JOIN workers w ON a.worker_id = w.worker_id
        WHERE w.company_id = ?
        ORDER BY a.check_in DESC
    ''', (cid,)).fetchall()
    conn.close()
    return jsonify([
        {'worker_id': r[0], 'name': r[1], 'check_in': r[2], 'check_out': r[3]}
        for r in rows
    ])

@app.route('/check_in', methods=['POST'])
def check_in():
    data = request.get_json() or {}
    worker_id = data.get("worker_id")
    if not worker_id:
        return jsonify({"message": "חסר worker_id"}), 400
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = connect()
    conn.execute("INSERT INTO attendance (worker_id, check_in) VALUES (?, ?)", (worker_id, now))
    conn.commit()
    conn.close()
    return jsonify({"message": "התחלת המשמרת בשעה: " + now})

@app.route('/check_out', methods=['POST'])
def check_out():
    data = request.get_json() or {}
    worker_id = data.get('worker_id')
    if not worker_id:
        return jsonify({"message": "חסר worker_id"}), 400
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = connect()
    c = conn.cursor()
    c.execute("""
        SELECT id FROM attendance
        WHERE worker_id = ? AND check_out IS NULL
        ORDER BY check_in DESC LIMIT 1
    """, (worker_id,))
    row = c.fetchone()

    if row:
        c.execute("UPDATE attendance SET check_out = ? WHERE id = ?", (now, row[0]))
        conn.commit()
        conn.close()
        return jsonify({"message": "יציאה נרשמה בהצלחה!"})
    else:
        conn.close()
        return jsonify({"message": "לא נמצאה משמרת פתוחה!"}), 400


@app.route('/my_shifts/<worker_id>')
def get_my_shifts(worker_id):
    conn = connect()
    rows = conn.execute("SELECT check_in, check_out FROM attendance WHERE worker_id = ?", (worker_id,)).fetchall()
    conn.close()
    return jsonify([{"check_in": r[0], "check_out": r[1]} for r in rows])


# =============================================================================
# Constraints (API + page)
# =============================================================================

@app.route('/submit_constraints', methods=['POST'])
def submit_constraints():
    data = request.get_json() or {}
    worker_id = data.get('employee')
    constraints = data.get('constraints', [])

    if not worker_id:
        return jsonify({"message": "חסר מזהה עובד"}), 400

    conn = connect()
    c = conn.cursor()
    c.execute("DELETE FROM constraints WHERE worker_id = ?", (worker_id,))
    for item in constraints:
        c.execute(
            "INSERT INTO constraints (worker_id, day, time) VALUES (?, ?, ?)",
            (worker_id, item['day'], item['time'])
        )
    conn.commit()
    conn.close()
    return jsonify({"message": "האילוצים נשמרו בהצלחה!"})

@app.route('/view_constraints', methods=['GET'])
def view_constraints():
    company_id = request.args.get('company_id')
    conn = connect()
    c = conn.cursor()
    if company_id:
        c.execute("""
            SELECT c.worker_id, w.name, c.day, c.time
            FROM constraints c
            JOIN workers w ON c.worker_id = w.worker_id
            WHERE w.company_id = ?
        """, (company_id,))
    else:
        c.execute("""
            SELECT c.worker_id, w.name, c.day, c.time
            FROM constraints c
            JOIN workers w ON c.worker_id = w.worker_id
        """)
    rows = c.fetchall()
    conn.close()
    return jsonify([{"worker_id": r[0], "name": r[1], "day": r[2], "time": r[3]} for r in rows])

@app.route('/api/view_constraints')
def view_constraints_api():
    cid = get_company_id_from_request()
    if not cid:
        return jsonify([]), 200

    conn = connect()
    rows = conn.execute("""
        SELECT c.worker_id, w.name, c.day, c.time
        FROM constraints AS c
        JOIN workers    AS w ON c.worker_id = w.worker_id
        WHERE w.company_id = ?
    """, (cid,)).fetchall()
    conn.close()

    day_order  = ['ראשון', 'שני', 'שלישי', 'רביעי', 'חמישי', 'שישי', 'שבת']
    time_order = ['בוקר', 'צהריים', 'ערב', 'לילה']

    def sort_key(r):
        d_idx = day_order.index(r[2]) if r[2] in day_order else 999
        t_idx = time_order.index(r[3]) if r[3] in time_order else 999
        return (d_idx, t_idx, r[1])

    rows = sorted(rows, key=sort_key)
    return jsonify([{"worker_id": r[0], "name": r[1], "day": r[2], "time": r[3]} for r in rows])

@app.route('/edit_constraints')
def edit_constraints():
    company_id = request.args.get('company_id')
    conn = connect()
    c = conn.cursor()

    if company_id:
        c.execute("""
            SELECT c.rowid, c.worker_id, w.name, c.day, c.time
            FROM constraints AS c
            JOIN workers    AS w ON c.worker_id = w.worker_id
            WHERE w.company_id = ?
            ORDER BY c.day, c.time, w.name
        """, (company_id,))
    else:
        c.execute("""
            SELECT c.rowid, c.worker_id, w.name, c.day, c.time
            FROM constraints AS c
            JOIN workers    AS w ON c.worker_id = w.worker_id
            ORDER BY c.day, c.time, w.name
        """)

    rows = c.fetchall()
    conn.close()

    constraints = [
        {"rowid": r[0], "worker_id": r[1], "name": r[2], "day": r[3], "time": r[4]}
        for r in rows
    ]
    return render_template("edit_constraints.html", constraints=constraints)

@app.route('/delete_constraint', methods=['POST'])
def delete_constraint():
    rowid = request.form.get("rowid")
    if rowid:
        conn = connect()
        conn.execute("DELETE FROM constraints WHERE rowid = ?", (rowid,))
        conn.commit()
        conn.close()
    return redirect("/edit_constraints")


# =============================================================================
# Schedule (API + generate/export)
# =============================================================================

@app.route('/api/view_schedule')
def view_schedule_api():
    cid = get_company_id_from_request()
    week = request.args.get('week', 'current')
    if not cid:
        return jsonify([])

    conn = connect()
    rows = conn.execute("""
        SELECT s.employee, w.name, s.day, s.time
        FROM shifts s
        JOIN workers w ON s.employee = w.worker_id
        WHERE s.week = ? AND s.company_id = ?
    """, (week, cid)).fetchall()
    conn.close()

    day_order = ['ראשון','שני','שלישי','רביעי','חמישי','שישי','שבת']
    time_order = ['בוקר','צהריים','ערב','לילה']
    rows = sorted(rows, key=lambda x: (day_order.index(x[2]), time_order.index(x[3])))

    return jsonify([{"worker_id":r[0], "name":r[1], "day":r[2], "time":r[3]} for r in rows])

@app.route('/generate_schedule', methods=['POST'])
def generate_schedule():
    week = request.args.get('week', 'current')
    company_id = get_company_id_from_request()
    if not company_id:
        return jsonify({"message": "חסר company_id (נסו להתחבר מחדש / להעביר ?company_id=)"}), 400

    conn = connect()
    c = conn.cursor()

    # company workers
    c.execute("""
        SELECT worker_id
        FROM workers
        WHERE role = 'worker' AND company_id = ?
    """, (company_id,))
    employees = [r[0] for r in c.fetchall()]
    if not employees:
        conn.close()
        return jsonify({"message": "אין עובדים לשיבוץ עבור החברה הזו"}), 400

    days = ['ראשון', 'שני', 'שלישי', 'רביעי', 'חמישי', 'שישי', 'שבת']

    # shift types (dynamic) – fallback defaults
    try:
        c.execute("SELECT name FROM shift_types ORDER BY id")
        time_slots = [row[0] for row in c.fetchall()] or ['בוקר', 'צהריים', 'ערב', 'לילה']
    except sqlite3.OperationalError:
        time_slots = ['בוקר', 'צהריים', 'ערב', 'לילה']

    # constraints for this company
    c.execute("""
        SELECT c.worker_id, c.day, c.time
        FROM constraints AS c
        JOIN workers    AS w ON c.worker_id = w.worker_id
        WHERE w.company_id = ?
    """, (company_id,))
    unavailable = [(row[0], row[1], row[2]) for row in c.fetchall()]

    # coverage: 2 for morning/noon, 1 for others
    heavier = {'בוקר', 'צהריים'}
    coverage = {(d, t): (2 if t in heavier else 1) for d in days for t in time_slots}

    # soft max shifts per worker
    max_shifts = {e: 20 for e in employees}

    schedule = solve_shift_schedule(employees, days, time_slots, unavailable, coverage, max_shifts)
    if not schedule:
        conn.close()
        return jsonify({"message": "לא ניתן ליצור שיבוץ עם האילוצים הנתונים"}), 400

    # replace existing rows for this week+company
    c.execute("DELETE FROM shifts WHERE week = ? AND company_id = ?", (week, company_id))
    schedule_data = []
    for e, d, t in schedule:
        c.execute(
            "INSERT INTO shifts (day, time, employee, week, company_id) VALUES (?, ?, ?, ?, ?)",
            (d, t, e, week, company_id)
        )
        schedule_data.append({"employee": e, "day": d, "time": t, "week": week, "company_id": company_id})

    conn.commit()
    conn.close()
    return jsonify({"message": f"שיבוץ {week} נוצר בהצלחה!", "schedule": schedule_data}), 201


@app.route('/save_schedule', methods=['POST'])
def save_schedule():
    """Legacy generic save (kept; not used by your UI)."""
    data = request.get_json() or {}
    schedule = data.get('schedule', [])
    conn = connect()
    c = conn.cursor()
    c.execute("DELETE FROM shifts")
    for item in schedule:
        c.execute("INSERT INTO shifts (day, time, employee) VALUES (?, ?, ?)",
                  (item['day'], item['time'], item['employee']))
    conn.commit()
    conn.close()
    return jsonify({"message": "השיבוץ נשמר בהצלחה!"})

@app.route('/load_schedule', methods=['GET'])
def load_schedule():
    conn = connect()
    rows = conn.execute("SELECT day, time, employee FROM shifts").fetchall()
    conn.close()
    return jsonify([{"day": r[0], "time": r[1], "employee": r[2]} for r in rows])

@app.route('/export_schedule')
def export_schedule():
    """Export schedule to Excel filtered by week and company (if provided)."""
    week = request.args.get('week')
    company_id = request.args.get('company_id') or (
        session.get('manager_id') and _get_company_id_for_manager(session.get('manager_id'))
    )
    export_format = request.args.get('format', 'excel').lower()
    if export_format != 'excel':
        return jsonify({"message": "פורמט לא נתמך. אפשרי: excel"}), 400

    conn = connect()
    try:
        sql = """
            SELECT
                s.employee,
                w.name AS employee_name,
                s.day,
                s.time,
                s.week,
                s.company_id
            FROM shifts s
            LEFT JOIN workers w ON s.employee = w.worker_id
        """
        where, params = [], []
        if week:
            where.append("s.week = ?")
            params.append(week)
        if company_id:
            where.append("s.company_id = ?")
            params.append(company_id)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY s.week, s.day, s.time, s.employee"

        df = pd.read_sql_query(sql, conn, params=params)
    finally:
        conn.close()

    # ensure columns
    expected_cols = ['employee', 'employee_name', 'day', 'time', 'week', 'company_id']
    for col in expected_cols:
        if col not in df.columns:
            df[col] = ""
    df = df[expected_cols]

    filename = "_".join([
        "schedule",
        f"company_{company_id}" if company_id else "company_all",
        f"week_{week}" if week else "week_all"
    ]) + ".xlsx"

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Schedule", index=False)
    output.seek(0)

    return send_file(
        output,
        as_attachment=True,
        download_name=filename,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )


# =============================================================================
# Shift types
# =============================================================================

@app.route('/get_shift_types', methods=['GET'])
def get_shift_types():
    conn = connect()
    rows = conn.execute("SELECT id, name FROM shift_types").fetchall()
    conn.close()
    return jsonify([{"id": r[0], "name": r[1]} for r in rows])

@app.route('/add_shift_type', methods=['POST'])
def add_shift_type():
    data = request.get_json() or {}
    name = data.get('name')
    if not name:
        return jsonify({"error": "Missing shift name"}), 400
    conn = connect()
    conn.execute("INSERT INTO shift_types (name) VALUES (?)", (name,))
    conn.commit()
    conn.close()
    return jsonify({"message": "Shift type added successfully"})

@app.route('/delete_shift_type/<int:shift_id>', methods=['DELETE'])
def delete_shift_type(shift_id):
    conn = connect()
    conn.execute("DELETE FROM shift_types WHERE id = ?", (shift_id,))
    conn.commit()
    conn.close()
    return jsonify({"message": "Shift type deleted successfully"})


# =============================================================================
# Main
# =============================================================================

if __name__ == '__main__':
    init_db()
    upgrade_db()
    app.run(debug=True, port=5050)
