from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
import sqlite3

app = Flask(__name__)
CORS(app)

# ---------- DB INIT ----------
def init_db():
    conn = sqlite3.connect('schedule.db')
    c = conn.cursor()

    # טבלת משמרות
    c.execute('''
        CREATE TABLE IF NOT EXISTS shifts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            day TEXT,
            time TEXT,
            employee TEXT
        )
    ''')

    # טבלת אילוצים
    c.execute('''
        CREATE TABLE IF NOT EXISTS constraints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee TEXT,
            day TEXT,
            time TEXT
        )
    ''')

    conn.commit()
    conn.close()

# ---------- ROUTES ----------

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/worker')
def worker_page():
    return render_template('worker.html')

@app.route('/manager')
def manager_page():
    return render_template('manager.html')

@app.route('/timetable')
def timetable_page():
    return render_template('shift_timetable.html')

# ---------- API: שמירת אילוצים ----------
@app.route('/submit_constraints', methods=['POST'])
def submit_constraints():
    data = request.get_json()
    employee = data.get('employee')
    constraints = data.get('constraints', [])

    if not employee:
        return jsonify({"message": "חסר שם עובד"}), 400

    conn = sqlite3.connect('schedule.db')
    c = conn.cursor()

    # מחיקה קודמת
    c.execute("DELETE FROM constraints WHERE employee = ?", (employee,))
    for item in constraints:
        c.execute("INSERT INTO constraints (employee, day, time) VALUES (?, ?, ?)",
                  (employee, item['day'], item['time']))

    conn.commit()
    conn.close()
    return jsonify({"message": "האילוצים נשמרו בהצלחה!"})

# ---------- API: שמירת שיבוץ ----------
@app.route('/save_schedule', methods=['POST'])
def save_schedule():
    data = request.get_json()
    schedule = data.get('schedule', [])

    conn = sqlite3.connect('schedule.db')
    c = conn.cursor()

    c.execute("DELETE FROM shifts")
    for item in schedule:
        c.execute("INSERT INTO shifts (day, time, employee) VALUES (?, ?, ?)",
                  (item['day'], item['time'], item['employee']))

    conn.commit()
    conn.close()
    return jsonify({"message": "השיבוץ נשמר בהצלחה!"})

# ---------- API: טעינת שיבוץ ----------
@app.route('/load_schedule', methods=['GET'])
def load_schedule():
    conn = sqlite3.connect('schedule.db')
    c = conn.cursor()
    c.execute("SELECT day, time, employee FROM shifts")
    rows = c.fetchall()
    conn.close()

    schedule = [{"day": r[0], "time": r[1], "employee": r[2]} for r in rows]
    return jsonify(schedule)

# ---------- הרצה ----------
if __name__ == '__main__':
    init_db()
    app.run(debug=True,port=5050)