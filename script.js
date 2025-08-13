// טעינת השיבוץ מהשרת והצגתו בדף
function loadSchedule() {
    const cid = localStorage.getItem('company_id'); // 🔹 שליפת מזהה חברה
    fetch(`/schedule?company_id=${cid}`)
        .then(response => response.json())
        .then(data => {
            const scheduleDiv = document.getElementById('schedule');
            scheduleDiv.innerHTML = "";

            if (data.length === 0) {
                scheduleDiv.innerHTML = "<p>לא נמצאו משמרות.</p>";
                return;
            }

            data.forEach(worker => {
                const p = document.createElement('p');
                p.className = "worker-shift";
                p.textContent = `עובד ${worker.worker} - משמרות: ${worker.shifts.join(', ')}`;
                scheduleDiv.appendChild(p);
            });
        })
        .catch(error => {
            console.error('שגיאה:', error);
            document.getElementById('schedule').textContent = "שגיאה בטעינת המשמרות.";
        });
}

// טעינת מצב כהה אם הופעל בעבר
document.addEventListener('DOMContentLoaded', () => {
    const darkMode = localStorage.getItem('dark-mode');
    if (darkMode === 'enabled') {
        document.body.classList.add('dark-mode');
    }
});

// החלפת מצב כהה
function toggleDarkMode() {
    const isDark = document.body.classList.toggle('dark-mode');
    localStorage.setItem('dark-mode', isDark ? 'enabled' : 'disabled');
}

function logout() {
    window.location.href = "/logout";
}

// הוספת שורת עובד חדשה בטבלה
function addWorkerRow() {
    const table = document.getElementById("workers-table").getElementsByTagName("tbody")[0];
    const newRow = table.insertRow();
    newRow.innerHTML = `
        <td><input type="text" placeholder="שם עובד" class="name-input" /></td>
        <td><input type="text" placeholder="תעודת זהות" class="id-number-input" /></td>
        <td><input type="text" placeholder="פלאפון" class="phone-input" /></td>
        <td><input type="email" placeholder="אימייל" class="email-input" /></td>
        <td><input type="text" placeholder="0,1,2..." class="shifts-input" /></td>
        <td><button onclick="removeRow(this)">🗑️</button></td>
    `;
}

// הסרת שורת עובד
function removeRow(button) {
    const row = button.parentNode.parentNode;
    row.parentNode.removeChild(row);
}

// שליחת עובדים לשיבוץ מהשרת והצגת התוצאה
function sendWorkersAndGetSchedule() {
    const cid = localStorage.getItem('company_id'); // 🔹 שליפת מזהה חברה
    const rows = document.querySelectorAll("#workers-table tbody tr");
    const workers = [];

    rows.forEach(row => {
        const name = row.cells[0].querySelector("input").value.trim();
        const shiftsRaw = row.cells[1].querySelector("input").value.trim();
        if (!name || !shiftsRaw) return;

        const shifts = shiftsRaw.split(',').map(Number).filter(n => !isNaN(n));
        if (shifts.length === 0) return;

        workers.push({ name, shifts });
    });

    if (workers.length === 0) {
        alert("יש להזין לפחות עובד אחד עם משמרות תקינות.");
        return;
    }

    fetch(`/schedule?company_id=${cid}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ workers })
    })
    .then(res => res.json())
    .then(data => {
        const scheduleDiv = document.getElementById("schedule");
        scheduleDiv.innerHTML = "";
        data.forEach(item => {
            const p = document.createElement("p");
            p.className = "worker-shift";
            p.innerText = `${item.name} ➝ משמרות: ${item.shifts.join(', ')}`;
            scheduleDiv.appendChild(p);
        });
    })
    .catch(err => {
        console.error("שגיאה:", err);
        document.getElementById("schedule").textContent = "שגיאה בטעינת השיבוץ.";
    });
}