A lightweight shift-scheduling web app for small teams. Managers can register/login, maintain a worker roster, collect availability constraints, generate weekly schedules (current or next week), export to Excel, track attendance, and message workers. Workers can log in, submit constraints, and view their shifts.
Built with Flask, SQLite, and a simple front-end. Schedules are generated using a solver in scheduler.py.


Features:


<Manager>


Register / login (per company)

Add/edit/delete workers

View/search workers (with company_id column)

Define custom shift types (e.g., Morning/Noon/Evening/Night)

View and edit constraints (with search)

Generate schedules for current or next week
(UI popup: choose week; replaces existing schedule for that week/company)

View weekly schedule (highlights current shift in green)

Export schedule to Excel

View company attendance (check-in/out)

Simple message center: view unread/all, mark read, soft delete

Auto-cascade delete: removing a worker removes their constraints


<Worker>


Login as worker only (manager creds can’t log in as worker)

Submit personal constraints (unavailability)

See own attendance (check-in/out)

See personal shifts (if you expose that page to workers)

Friendly greeting by name on pages


Tech Stack


Backend: Python 3, Flask, flask-cors, SQLite3

Frontend: HTML/CSS/JS (vanilla)

Data/Export: pandas, openpyxl

Scheduling:scheduler.py (uses OR-Tools )


.
├─ flask.py
├─ scheduler.py                 # contains solve_shift_schedule(...)
├─ schedule.db                  # auto-created on first run
├─ templates/
│  ├─ index.html                # login/register (manager & worker)
│  ├─ manager.html              # manager dashboard
│  ├─ worker.html               # worker landing
│  ├─ view_schedule.html        # schedule grid (current/next)
│  ├─ view_constraints.html     # read-only constraints + search
│  ├─ edit_constraints.html     # editable constraints + search
│  ├─ workers_list.html         # list/search/edit workers
│  ├─ attendance_report.html
│  └─ add_worker.html
└─ static/
   ├─ styles.css (optional)
   ├─ logo.png
   ├─ atom_bg.gif
   └─ favicon.ico


Setup


1) Prerequisites

Python 3.9+ (3.10/3.11 recommended)

pip

2) Clone & create a virtualenv

git clone https://github.com/MOHAMED541173/constraints_system.git
cd <your-repo>
 
# Windows
python -m venv .venv
.venv\Scripts\activate

# macOS/Linux
python3 -m venv .venv
source .venv/bin/activate

Install dependencies

Create a requirements.txt (if not already present) like this:

Flask>=2.2
flask-cors>=4.0
pandas>=2.1
openpyxl>=3.1
ortools>=9.9 

Then:

pip install -r requirements.txt

Run the app

Simply run:

python flask.py


The server starts at: http://127.0.0.1:5050

On first start, the DB is created and upgraded automatically (init_db() + upgrade_db()).


First Login:


A default manager is created (company #1) if none exists:

Manager ID: 29

Password: 4324

After login:

The app stores company_id, company_name, and manager_id in localStorage.

You’ll see a greeting in the manager UI (we also save manager_name on login).


How to Use


Manager Login (on /)
Choose “מנהל”, enter ID & password.
The app saves company_id etc. to localStorage and redirects to /manager.

Add Workers
From the sidebar → “הוסף עובד”.
You can inline-edit ID/phone/email in “רשימת עובדים”.

Shift Types
From the sidebar → “ניהול משמרות” to add/remove names (Morning/Noon/…).

Constraints
shows a searchable list.“צפייה באילוצים”
lets you delete rows.“עריכה”
Workers submit their constraints via the worker UI (you can add a link on the worker page).

Generate Schedule
In Manager page, click “צור שיבוץ” → choose current or next.
This overwrites existing schedule for that week & company.

View Schedule
Click “📅 צפייה בשיבוץ” on Manager page.
Toggle Current/Next in the schedule page.
The cell matching today + current time slot is highlighted green.

Export to Excel
On the schedule page, click “Excel - יצוא”.
You’ll get schedule_company_<id>_week_<current|next>.xlsx.

Attendance
Managers can view reports; workers can check-in/out via worker UI.

Messages
Manager panel shows unread/all messages, with mark-as-read and soft delete.


Data Model (key tables)


workers

id, name, password, role ('manager'/'worker'), worker_id (TEXT), id_number, phone, email, company_id, company_name

constraints

id, worker_id (FK -> workers.worker_id, ON DELETE CASCADE), day, time

Deleting a worker automatically removes their constraints.

shifts

id, day, time, employee (worker_id), week ('current'|'next'), company_id

messages

id, worker_id, content, timestamp, is_read, is_deleted

attendance

id, worker_id, check_in, check_out

shift_types

id, name

companies

company_id, company_name (unique)


Key Endpoints (selection)


POST /login_manager → { success, manager_id, company_id, company_name, name }

POST /login_worker → { success, name, company_id, company_name } (only role='worker' allowed)

GET /get_workers?company_id=...

POST /add_worker

DELETE /delete_worker/<worker_id>

POST /update_worker_field

GET /api/view_constraints?company_id=...

POST /submit_constraints

GET /api/view_schedule?week=current|next&company_id=...

POST /generate_schedule?week=current|next&company_id=...

GET /export_schedule?week=current|next&company_id=...&format=excel


Deployment Notes:


SQLite is file-based; for multi-user production use, consider Postgres.

Set a strong app.secret_key (env var) in production.

Behind a real server (gunicorn/uwsgi + nginx), disable Flask debug.

For HTTPS, terminate TLS at your reverse proxy.


Troubleshooting


“cannot start a transaction within a transaction”
Fixed in upgrade_db() by committing before rebuild and using executescript.

Foreign keys not cascading
We enable PRAGMA foreign_keys = ON on each connection. If you use external tools, ensure FKs are on.

PyArrow warning from pandas
Harmless. Install with pip install pyarrow if you want.

Login shows wrong company
Clear localStorage in the browser (DevTools → Application → Local Storage).


Contributing


PRs welcome! Please open an issue for feature requests or bugs.


<img width="1186" height="894" alt="image" src="https://github.com/user-attachments/assets/31dc3fb7-5900-45fa-962b-2e746c24b41f" />

<img width="1294" height="894" alt="image" src="https://github.com/user-attachments/assets/07844645-94df-44fb-893a-c61d1cb990d6" />

<img width="1186" height="959" alt="image" src="https://github.com/user-attachments/assets/cdb2c5cd-6f9e-4565-921f-5d956581ac24" />

<img width="261" height="265" alt="image" src="https://github.com/user-attachments/assets/1d737a2d-4215-41a6-8db5-2eecdaf8bf08" />

<img width="2000" height="1125" alt="image" src="https://github.com/user-attachments/assets/b98b224b-ea90-4b1a-ad9a-86fb12835da9" />
