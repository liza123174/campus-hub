import os
import re
import secrets
import sqlite3
import uuid
import math
from datetime import date, datetime
from functools import wraps
from pathlib import Path

from flask import (
    Flask,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    current_app,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash


BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = Path(os.environ.get("DATABASE_PATH", BASE_DIR / "instance" / "campus_hub.db"))
EXCHANGE_CATEGORIES = (
    "Books",
    "Notes and Study Material",
    "Electronics",
    "Lab Equipment",
    "Stationery",
    "Hostel Essentials",
    "Other",
)
LOST_FOUND_CATEGORIES = (
    "ID Cards",
    "Books and Notes",
    "Electronics",
    "Bags and Accessories",
    "Keys",
    "Clothing",
    "Other",
)
MAX_IMAGE_BYTES = 2 * 1024 * 1024
IMAGE_SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"\xff\xd8\xff", ".jpg"),
    (b"GIF87a", ".gif"),
    (b"GIF89a", ".gif"),
)

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY") or secrets.token_hex(32),
    MAX_CONTENT_LENGTH=MAX_IMAGE_BYTES + 128 * 1024,
    UPLOAD_FOLDER=BASE_DIR / "static" / "uploads",
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("FLASK_ENV") == "production",
)


def get_db():
    """Open one SQLite connection per request."""
    if "db" not in g:
        DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
        g.db = sqlite3.connect(DATABASE_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            department TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS notices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            category TEXT NOT NULL,
            published_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS internships (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            company TEXT NOT NULL,
            location TEXT NOT NULL,
            work_mode TEXT NOT NULL,
            category TEXT NOT NULL,
            duration TEXT NOT NULL,
            eligibility TEXT NOT NULL,
            deadline TEXT NOT NULL,
            application_url TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS placements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company TEXT NOT NULL,
            role TEXT NOT NULL,
            eligibility TEXT NOT NULL,
            location TEXT NOT NULL,
            deadline TEXT NOT NULL,
            drive_date TEXT NOT NULL,
            description TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS exchange_listings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
            title TEXT NOT NULL CHECK(length(title) BETWEEN 1 AND 100),
            description TEXT NOT NULL CHECK(length(description) BETWEEN 1 AND 2000),
            category TEXT NOT NULL,
            price REAL NOT NULL CHECK(price >= 0),
            image_filename TEXT,
            status TEXT NOT NULL DEFAULT 'available'
                CHECK(status IN ('available', 'sold', 'exchanged')),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS lost_found_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
            item_name TEXT NOT NULL CHECK(length(item_name) BETWEEN 1 AND 100),
            description TEXT NOT NULL CHECK(length(description) BETWEEN 1 AND 2000),
            category TEXT NOT NULL,
            location TEXT NOT NULL CHECK(length(location) BETWEEN 1 AND 120),
            incident_date TEXT NOT NULL,
            report_type TEXT NOT NULL CHECK(report_type IN ('Lost', 'Found')),
            image_filename TEXT,
            status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'resolved')),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS contact_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_type TEXT NOT NULL CHECK(entity_type IN ('exchange', 'lost_found')),
            entity_id INTEGER NOT NULL,
            sender_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
            recipient_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
            message TEXT NOT NULL CHECK(length(message) BETWEEN 1 AND 500),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_exchange_status_created
            ON exchange_listings(status, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_lost_found_status_created
            ON lost_found_reports(status, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_contact_requests_recipient
            ON contact_requests(recipient_id, entity_type, entity_id);
        """
    )
    seed_sample_data(db)
    db.commit()


def seed_sample_data(db):
    """Insert the demo catalog once, so restarting never duplicates it."""
    if db.execute("SELECT COUNT(*) FROM notices").fetchone()[0] == 0:
        db.executemany(
            """INSERT INTO notices (title, description, category, published_at)
               VALUES (?, ?, ?, ?)""",
            [
                (
                    "Fall semester registration is now open",
                    "Course registration for the fall semester is open through the student portal. "
                    "Please review your degree plan with your academic adviser before submitting your selections.",
                    "Academics",
                    "2026-10-10",
                ),
                (
                    "Innovation Week: project showcase",
                    "Student teams are invited to present prototypes and research posters during Innovation Week. "
                    "Submit your team name and project summary to the Student Activities Office by October 24.",
                    "Events",
                    "2026-10-08",
                ),
                (
                    "Library extended hours during midterms",
                    "The main library will remain open until midnight from October 20 through October 31. "
                    "Group study rooms can be reserved online.",
                    "Campus",
                    "2026-10-04",
                ),
                (
                    "Career services resume review appointments",
                    "Career Services has opened additional 20-minute resume review appointments for students "
                    "preparing for internship and placement applications.",
                    "Career",
                    "2026-10-02",
                ),
            ],
        )
    if db.execute("SELECT COUNT(*) FROM internships").fetchone()[0] == 0:
        db.executemany(
            """INSERT INTO internships
               (title, company, location, work_mode, category, duration, eligibility, deadline, application_url, description)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    "Software Engineering Intern (Demo)",
                    "Northstar Labs (Demo)",
                    "Boston, MA",
                    "Hybrid",
                    "Software",
                    "12 weeks",
                    "Undergraduate students studying Computer Science or a related field; basic Python or Java experience.",
                    "2026-11-15",
                    "",
                    "Contribute to a supervised student-facing product team. The sample listing is for demonstration; "
                    "contact your campus career office to verify current opportunities.",
                ),
                (
                    "Data Analytics Intern (Demo)",
                    "Harbor Research Group (Demo)",
                    "Remote",
                    "Remote",
                    "Data",
                    "10 weeks",
                    "Students comfortable with spreadsheets and introductory statistics. SQL coursework is helpful.",
                    "2026-11-22",
                    "",
                    "Support research analysts with data cleaning, exploratory analysis, and clear written summaries. "
                    "This is a fictional demo opportunity with no live application link.",
                ),
                (
                    "Communications Intern (Demo)",
                    "Campus Commons Studio (Demo)",
                    "Cambridge, MA",
                    "On-site",
                    "Communications",
                    "8 weeks",
                    "Open to all majors with writing samples and an interest in community storytelling.",
                    "2026-12-01",
                    "",
                    "Help prepare event communications and student stories alongside a small communications team. "
                    "This fictional listing is included to demonstrate filters and detail pages.",
                ),
            ],
        )
    if db.execute("SELECT COUNT(*) FROM placements").fetchone()[0] == 0:
        db.executemany(
            """INSERT INTO placements
               (company, role, eligibility, location, deadline, drive_date, description)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    "Pioneer Systems (Demo)",
                    "Graduate Software Associate",
                    "Bachelor's students graduating in 2027; minimum 3.0 GPA and familiarity with one programming language.",
                    "Boston, MA",
                    "2026-11-05",
                    "2026-11-18",
                    "A sample campus recruiting drive featuring an information session, coding exercise, and interviews. "
                    "The employer and dates are illustrative only.",
                ),
                (
                    "Evergreen Consulting (Demo)",
                    "Business Analyst, Early Career",
                    "Students graduating in 2027 from any major; strong communication and analytical skills.",
                    "New York, NY",
                    "2026-11-12",
                    "2026-11-25",
                    "A fictional opportunity for students interested in research, client problem-solving, and business analysis.",
                ),
                (
                    "BluePeak Health (Demo)",
                    "Technology Rotational Associate",
                    "Computer Science, Information Systems, or related majors graduating in 2027.",
                    "Remote",
                    "2026-12-03",
                    "2026-12-10",
                    "A demonstration listing for a sample early-career technology program. Check with Career Services "
                    "before acting on any opportunity.",
                ),
            ],
        )


def csrf_token():
    token = session.get("_csrf_token")
    if token is None:
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    return token


@app.context_processor
def inject_template_values():
    student = None
    if session.get("student_id"):
        student = get_db().execute(
            "SELECT id, name, email, department FROM students WHERE id = ?",
            (session["student_id"],),
        ).fetchone()
    return {"current_student": student, "csrf_token": csrf_token, "today": date.today().isoformat()}


@app.before_request
def protect_post_requests():
    if request.method == "POST":
        submitted = request.form.get("csrf_token", "")
        expected = session.get("_csrf_token", "")
        if not expected or not secrets.compare_digest(submitted, expected):
            abort(400, description="The form expired or its security token was invalid. Please try again.")


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if not session.get("student_id"):
            flash("Please sign in to access your student dashboard.", "info")
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped_view


def email_is_valid(email):
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email))


@app.route("/")
def home():
    return redirect(url_for("dashboard") if session.get("student_id") else url_for("login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if session.get("student_id"):
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        department = request.form.get("department", "").strip()
        password = request.form.get("password", "")
        errors = []
        if not name or len(name) > 80:
            errors.append("Enter a name of 1 to 80 characters.")
        if not email_is_valid(email) or len(email) > 254:
            errors.append("Enter a valid email address.")
        if not department or len(department) > 80:
            errors.append("Enter a department of 1 to 80 characters.")
        if len(password) < 8:
            errors.append("Your password must be at least 8 characters long.")
        if errors:
            for error in errors:
                flash(error, "danger")
            return render_template("register.html", form=request.form)
        try:
            cursor = get_db().execute(
                "INSERT INTO students (name, email, password_hash, department) VALUES (?, ?, ?, ?)",
                (name, email, generate_password_hash(password), department),
            )
            get_db().commit()
        except sqlite3.IntegrityError:
            flash("An account with that email already exists. Please sign in instead.", "warning")
            return render_template("register.html", form=request.form)
        session.clear()
        session["student_id"] = cursor.lastrowid
        flash("Your student account is ready. Welcome to Campus Hub!", "success")
        return redirect(url_for("dashboard"))
    return render_template("register.html", form={})


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("student_id"):
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        student = get_db().execute(
            "SELECT id, password_hash FROM students WHERE email = ?",
            (email,),
        ).fetchone()
        if student is None or not check_password_hash(student["password_hash"], password):
            flash("The email or password was not recognized.", "danger")
            return render_template("login.html", email=email)
        session.clear()
        session["student_id"] = student["id"]
        flash("Welcome back!", "success")
        return redirect(url_for("dashboard"))
    return render_template("login.html", email="")


@app.route("/logout", methods=["POST"])
@login_required
def logout():
    session.clear()
    flash("You have been signed out.", "info")
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    db = get_db()
    return render_template(
        "dashboard.html",
        notice_count=db.execute("SELECT COUNT(*) FROM notices").fetchone()[0],
        internship_count=db.execute("SELECT COUNT(*) FROM internships WHERE deadline >= ?", (today_iso(),)).fetchone()[0],
        placement_count=db.execute("SELECT COUNT(*) FROM placements WHERE deadline >= ?", (today_iso(),)).fetchone()[0],
        exchange_count=db.execute(
            "SELECT COUNT(*) FROM exchange_listings WHERE status = 'available'"
        ).fetchone()[0],
        lost_found_count=db.execute(
            "SELECT COUNT(*) FROM lost_found_reports WHERE status = 'active'"
        ).fetchone()[0],
        notices=db.execute("SELECT * FROM notices ORDER BY published_at DESC, id DESC LIMIT 3").fetchall(),
        internships=db.execute(
            "SELECT * FROM internships WHERE deadline >= ? ORDER BY deadline LIMIT 3",
            (today_iso(),),
        ).fetchall(),
        placements=db.execute(
            "SELECT * FROM placements WHERE drive_date >= ? ORDER BY drive_date LIMIT 3",
            (today_iso(),),
        ).fetchall(),
        recent_exchange=db.execute(
            """SELECT l.*, s.name AS seller_name FROM exchange_listings l
               JOIN students s ON s.id = l.student_id
               WHERE l.status = 'available' ORDER BY l.created_at DESC, l.id DESC LIMIT 3"""
        ).fetchall(),
        recent_lost_found=db.execute(
            """SELECT r.*, s.name AS reporter_name FROM lost_found_reports r
               JOIN students s ON s.id = r.student_id
               WHERE r.status = 'active' ORDER BY r.created_at DESC, r.id DESC LIMIT 3"""
        ).fetchall(),
    )


def today_iso():
    return date.today().isoformat()


@app.route("/notices")
@login_required
def notices():
    search = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    query = "SELECT * FROM notices WHERE 1 = 1"
    params = []
    if search:
        query += " AND title LIKE ?"
        params.append(f"%{search}%")
    if category:
        query += " AND category = ?"
        params.append(category)
    query += " ORDER BY published_at DESC, id DESC"
    db = get_db()
    categories = db.execute("SELECT DISTINCT category FROM notices ORDER BY category").fetchall()
    items = db.execute(query, params).fetchall()
    return render_template("notices.html", notices=items, categories=categories, search=search, selected_category=category)


@app.route("/notices/<int:notice_id>")
@login_required
def notice_detail(notice_id):
    notice = get_db().execute("SELECT * FROM notices WHERE id = ?", (notice_id,)).fetchone()
    if notice is None:
        abort(404)
    return render_template("notice_detail.html", notice=notice)


@app.route("/internships")
@login_required
def internships():
    search = request.args.get("q", "").strip()
    location = request.args.get("location", "").strip()
    work_mode = request.args.get("work_mode", "").strip()
    category = request.args.get("category", "").strip()
    query = "SELECT * FROM internships WHERE deadline >= ?"
    params = [today_iso()]
    if search:
        query += " AND (title LIKE ? OR company LIKE ?)"
        params.extend((f"%{search}%", f"%{search}%"))
    for field, value in (("location", location), ("work_mode", work_mode), ("category", category)):
        if value:
            query += f" AND {field} = ?"
            params.append(value)
    query += " ORDER BY deadline, id"
    db = get_db()
    items = db.execute(query, params).fetchall()
    return render_template(
        "internships.html",
        internships=items,
        search=search,
        selected_location=location,
        selected_work_mode=work_mode,
        selected_category=category,
        locations=db.execute("SELECT DISTINCT location FROM internships ORDER BY location").fetchall(),
        work_modes=db.execute("SELECT DISTINCT work_mode FROM internships ORDER BY work_mode").fetchall(),
        categories=db.execute("SELECT DISTINCT category FROM internships ORDER BY category").fetchall(),
    )


@app.route("/internships/<int:internship_id>")
@login_required
def internship_detail(internship_id):
    internship = get_db().execute("SELECT * FROM internships WHERE id = ?", (internship_id,)).fetchone()
    if internship is None:
        abort(404)
    return render_template("internship_detail.html", internship=internship)


@app.route("/placements")
@login_required
def placements():
    search = request.args.get("q", "").strip()
    location = request.args.get("location", "").strip()
    query = "SELECT * FROM placements WHERE deadline >= ?"
    params = [today_iso()]
    if search:
        query += " AND (company LIKE ? OR role LIKE ?)"
        params.extend((f"%{search}%", f"%{search}%"))
    if location:
        query += " AND location = ?"
        params.append(location)
    query += " ORDER BY drive_date, id"
    db = get_db()
    items = db.execute(query, params).fetchall()
    return render_template(
        "placements.html",
        placements=items,
        search=search,
        selected_location=location,
        locations=db.execute("SELECT DISTINCT location FROM placements ORDER BY location").fetchall(),
    )


@app.route("/placements/<int:placement_id>")
@login_required
def placement_detail(placement_id):
    placement = get_db().execute("SELECT * FROM placements WHERE id = ?", (placement_id,)).fetchone()
    if placement is None:
        abort(404)
    return render_template("placement_detail.html", placement=placement)


@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    db = get_db()
    student = db.execute(
        "SELECT id, name, email, department FROM students WHERE id = ?",
        (session["student_id"],),
    ).fetchone()
    if student is None:
        session.clear()
        return redirect(url_for("login"))
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        department = request.form.get("department", "").strip()
        if not name or len(name) > 80:
            flash("Enter a name of 1 to 80 characters.", "danger")
        elif not department or len(department) > 80:
            flash("Enter a department of 1 to 80 characters.", "danger")
        else:
            db.execute(
                "UPDATE students SET name = ?, department = ? WHERE id = ?",
                (name, department, student["id"]),
            )
            db.commit()
            flash("Your profile has been updated.", "success")
            return redirect(url_for("profile"))
        student = {"id": student["id"], "email": student["email"], "name": name, "department": department}
    return render_template("profile.html", student=student)


def parse_optional_image():
    """Return image bytes and a type-derived extension, or a readable validation error."""
    uploaded = request.files.get("image")
    if uploaded is None or not uploaded.filename:
        return None, None, None
    data = uploaded.stream.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        return None, None, "Images must be 2 MB or smaller."
    extension = next(
        (extension for signature, extension in IMAGE_SIGNATURES if data.startswith(signature)),
        None,
    )
    if extension is None and len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        extension = ".webp"
    if extension is None:
        return None, None, "Choose a valid PNG, JPEG, GIF, or WebP image."
    return data, extension, None


def save_uploaded_image(data, extension):
    filename = f"{uuid.uuid4().hex}{extension}"
    upload_folder = Path(current_app.config["UPLOAD_FOLDER"])
    upload_folder.mkdir(parents=True, exist_ok=True)
    (upload_folder / filename).write_bytes(data)
    return filename


def remove_uploaded_image(filename):
    if not filename or not re.fullmatch(r"[a-f0-9]{32}\.(png|jpg|gif|webp)", filename):
        return
    image_path = Path(current_app.config["UPLOAD_FOLDER"]) / filename
    if image_path.is_file():
        image_path.unlink()


def valid_date(value):
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return False
    return parsed.isoformat() == value and parsed <= date.today()


def owned_record(table, record_id):
    if table not in {"exchange_listings", "lost_found_reports"}:
        raise ValueError("Unsupported owner-controlled table.")
    record = get_db().execute(
        f"SELECT * FROM {table} WHERE id = ?",
        (record_id,),
    ).fetchone()
    if record is None:
        abort(404)
    if record["student_id"] != session["student_id"]:
        abort(403)
    return record


def record_contact_requests(entity_type, entity_id):
    return get_db().execute(
        """SELECT cr.message, cr.created_at, s.name AS sender_name
           FROM contact_requests cr JOIN students s ON s.id = cr.sender_id
           WHERE cr.entity_type = ? AND cr.entity_id = ? AND cr.recipient_id = ?
           ORDER BY cr.created_at DESC, cr.id DESC""",
        (entity_type, entity_id, session["student_id"]),
    ).fetchall()


def save_contact_request(entity_type, entity_id):
    if entity_type == "exchange":
        record = get_db().execute(
            "SELECT student_id, status FROM exchange_listings WHERE id = ?",
            (entity_id,),
        ).fetchone()
        if record is None:
            abort(404)
        if record["status"] != "available":
            flash("This listing is no longer available for contact.", "warning")
            return redirect(url_for("exchange_detail", listing_id=entity_id))
        detail_endpoint = "exchange_detail"
        id_name = "listing_id"
    else:
        record = get_db().execute(
            "SELECT student_id, status FROM lost_found_reports WHERE id = ?",
            (entity_id,),
        ).fetchone()
        if record is None:
            abort(404)
        if record["status"] != "active":
            flash("This report has already been resolved.", "warning")
            return redirect(url_for("lost_found_detail", report_id=entity_id))
        detail_endpoint = "lost_found_detail"
        id_name = "report_id"
    recipient_id = record["student_id"]
    if recipient_id == session["student_id"]:
        abort(403)
    message = request.form.get("message", "").strip()
    if not message or len(message) > 500:
        flash("Write a message of 1 to 500 characters.", "danger")
        return redirect(url_for(detail_endpoint, **{id_name: entity_id}))
    db = get_db()
    db.execute(
        """INSERT INTO contact_requests
           (entity_type, entity_id, sender_id, recipient_id, message)
           VALUES (?, ?, ?, ?, ?)""",
        (entity_type, entity_id, session["student_id"], recipient_id, message),
    )
    db.commit()
    flash("Your contact request was sent privately to the student who posted this.", "success")
    return redirect(url_for(detail_endpoint, **{id_name: entity_id}))


@app.route("/exchange")
@login_required
def exchange_hub():
    search = request.args.get("q", "").strip()[:100]
    category = request.args.get("category", "").strip()
    price_filter = request.args.get("price", "").strip()
    query = """SELECT l.*, s.name AS seller_name FROM exchange_listings l
               JOIN students s ON s.id = l.student_id WHERE l.status = 'available'"""
    params = []
    if search:
        query += " AND (l.title LIKE ? OR l.description LIKE ?)"
        params.extend((f"%{search}%", f"%{search}%"))
    if category in EXCHANGE_CATEGORIES:
        query += " AND l.category = ?"
        params.append(category)
    if price_filter == "free":
        query += " AND l.price = 0"
    elif price_filter == "priced":
        query += " AND l.price > 0"
    query += " ORDER BY l.created_at DESC, l.id DESC"
    listings = get_db().execute(query, params).fetchall()
    return render_template(
        "exchange.html",
        listings=listings,
        categories=EXCHANGE_CATEGORIES,
        search=search,
        selected_category=category,
        selected_price=price_filter,
    )


@app.route("/exchange/new", methods=["GET", "POST"])
@login_required
def exchange_create():
    form = request.form if request.method == "POST" else {}
    errors = []
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        category = request.form.get("category", "").strip()
        price_value = request.form.get("price", "").strip()
        try:
            price = float(price_value)
            if not math.isfinite(price) or price < 0 or price > 1000000:
                raise ValueError
        except ValueError:
            price = 0
            errors.append("Enter a price from 0 to 1,000,000. Use 0 for a free item.")
        if not title or len(title) > 100:
            errors.append("Enter an item title of 1 to 100 characters.")
        if not description or len(description) > 2000:
            errors.append("Enter a description of 1 to 2,000 characters.")
        if category not in EXCHANGE_CATEGORIES:
            errors.append("Choose a valid category.")
        image_data, image_extension, image_error = parse_optional_image()
        if image_error:
            errors.append(image_error)
        if not errors:
            image_filename = save_uploaded_image(image_data, image_extension) if image_data else None
            db = get_db()
            db.execute(
                """INSERT INTO exchange_listings
                   (student_id, title, description, category, price, image_filename)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (session["student_id"], title, description, category, price, image_filename),
            )
            db.commit()
            flash("Your exchange listing has been posted.", "success")
            return redirect(url_for("exchange_hub"))
        for error in errors:
            flash(error, "danger")
    return render_template("exchange_form.html", listing=None, form=form, categories=EXCHANGE_CATEGORIES)


@app.route("/exchange/<int:listing_id>")
@login_required
def exchange_detail(listing_id):
    db = get_db()
    listing = db.execute(
        """SELECT l.*, s.name AS seller_name FROM exchange_listings l
           JOIN students s ON s.id = l.student_id WHERE l.id = ?""",
        (listing_id,),
    ).fetchone()
    if listing is None:
        abort(404)
    contact_requests = record_contact_requests("exchange", listing_id) if listing["student_id"] == session["student_id"] else []
    return render_template("exchange_detail.html", listing=listing, contact_requests=contact_requests)


@app.route("/exchange/<int:listing_id>/edit", methods=["GET", "POST"])
@login_required
def exchange_edit(listing_id):
    listing = owned_record("exchange_listings", listing_id)
    form = request.form if request.method == "POST" else dict(listing)
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        category = request.form.get("category", "").strip()
        price_value = request.form.get("price", "").strip()
        status = request.form.get("status", "").strip()
        errors = []
        try:
            price = float(price_value)
            if not math.isfinite(price) or price < 0 or price > 1000000:
                raise ValueError
        except ValueError:
            price = 0
            errors.append("Enter a price from 0 to 1,000,000. Use 0 for a free item.")
        if not title or len(title) > 100:
            errors.append("Enter an item title of 1 to 100 characters.")
        if not description or len(description) > 2000:
            errors.append("Enter a description of 1 to 2,000 characters.")
        if category not in EXCHANGE_CATEGORIES:
            errors.append("Choose a valid category.")
        if status not in {"available", "sold", "exchanged"}:
            errors.append("Choose a valid listing status.")
        image_data, image_extension, image_error = parse_optional_image()
        if image_error:
            errors.append(image_error)
        if not errors:
            image_filename = (
                save_uploaded_image(image_data, image_extension)
                if image_data
                else listing["image_filename"]
            )
            db = get_db()
            db.execute(
                """UPDATE exchange_listings SET title = ?, description = ?, category = ?,
                   price = ?, status = ?, image_filename = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND student_id = ?""",
                (title, description, category, price, status, image_filename, listing_id, session["student_id"]),
            )
            db.commit()
            if image_data:
                remove_uploaded_image(listing["image_filename"])
            flash("Your exchange listing was updated.", "success")
            return redirect(url_for("exchange_detail", listing_id=listing_id))
        for error in errors:
            flash(error, "danger")
    return render_template("exchange_form.html", listing=listing, form=form, categories=EXCHANGE_CATEGORIES)


@app.route("/exchange/<int:listing_id>/delete", methods=["POST"])
@login_required
def exchange_delete(listing_id):
    listing = owned_record("exchange_listings", listing_id)
    db = get_db()
    db.execute("DELETE FROM contact_requests WHERE entity_type = 'exchange' AND entity_id = ?", (listing_id,))
    db.execute(
        "DELETE FROM exchange_listings WHERE id = ? AND student_id = ?",
        (listing_id, session["student_id"]),
    )
    db.commit()
    remove_uploaded_image(listing["image_filename"])
    flash("Your exchange listing was deleted.", "success")
    return redirect(url_for("exchange_hub"))


@app.route("/exchange/<int:listing_id>/status", methods=["POST"])
@login_required
def exchange_status(listing_id):
    owned_record("exchange_listings", listing_id)
    status = request.form.get("status", "").strip()
    if status not in {"available", "sold", "exchanged"}:
        flash("Choose a valid listing status.", "danger")
        return redirect(url_for("exchange_detail", listing_id=listing_id))
    get_db().execute(
        """UPDATE exchange_listings SET status = ?, updated_at = CURRENT_TIMESTAMP
           WHERE id = ? AND student_id = ?""",
        (status, listing_id, session["student_id"]),
    )
    get_db().commit()
    flash("Listing availability was updated.", "success")
    return redirect(url_for("exchange_detail", listing_id=listing_id))


@app.route("/lost-found")
@login_required
def lost_found_hub():
    search = request.args.get("q", "").strip()[:100]
    category = request.args.get("category", "").strip()
    report_type = request.args.get("type", "").strip()
    status = request.args.get("status", "active").strip()
    query = """SELECT r.*, s.name AS reporter_name FROM lost_found_reports r
               JOIN students s ON s.id = r.student_id WHERE 1 = 1"""
    params = []
    if search:
        query += " AND (r.item_name LIKE ? OR r.description LIKE ? OR r.location LIKE ?)"
        params.extend((f"%{search}%", f"%{search}%", f"%{search}%"))
    if category in LOST_FOUND_CATEGORIES:
        query += " AND r.category = ?"
        params.append(category)
    if report_type in {"Lost", "Found"}:
        query += " AND r.report_type = ?"
        params.append(report_type)
    if status in {"active", "resolved"}:
        query += " AND r.status = ?"
        params.append(status)
    else:
        status = "all"
    query += " ORDER BY r.created_at DESC, r.id DESC"
    reports = get_db().execute(query, params).fetchall()
    return render_template(
        "lost_found.html",
        reports=reports,
        categories=LOST_FOUND_CATEGORIES,
        search=search,
        selected_category=category,
        selected_type=report_type,
        selected_status=status,
    )


@app.route("/lost-found/new", methods=["GET", "POST"])
@login_required
def lost_found_create():
    form = request.form if request.method == "POST" else {}
    if request.method == "POST":
        item_name = request.form.get("item_name", "").strip()
        description = request.form.get("description", "").strip()
        category = request.form.get("category", "").strip()
        location = request.form.get("location", "").strip()
        incident_date = request.form.get("incident_date", "").strip()
        report_type = request.form.get("report_type", "").strip()
        errors = []
        if not item_name or len(item_name) > 100:
            errors.append("Enter an item name of 1 to 100 characters.")
        if not description or len(description) > 2000:
            errors.append("Enter a description of 1 to 2,000 characters.")
        if category not in LOST_FOUND_CATEGORIES:
            errors.append("Choose a valid category.")
        if not location or len(location) > 120:
            errors.append("Enter a location of 1 to 120 characters.")
        if not valid_date(incident_date):
            errors.append("Choose a valid date that is not in the future.")
        if report_type not in {"Lost", "Found"}:
            errors.append("Choose whether the item was lost or found.")
        image_data, image_extension, image_error = parse_optional_image()
        if image_error:
            errors.append(image_error)
        if not errors:
            image_filename = save_uploaded_image(image_data, image_extension) if image_data else None
            db = get_db()
            db.execute(
                """INSERT INTO lost_found_reports
                   (student_id, item_name, description, category, location, incident_date,
                    report_type, image_filename)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (session["student_id"], item_name, description, category, location, incident_date, report_type, image_filename),
            )
            db.commit()
            flash(f"Your {report_type.lower()} item report was posted.", "success")
            return redirect(url_for("lost_found_hub"))
        for error in errors:
            flash(error, "danger")
    return render_template(
        "lost_found_form.html",
        report=None,
        form=form,
        categories=LOST_FOUND_CATEGORIES,
        today=today_iso(),
    )


@app.route("/lost-found/<int:report_id>")
@login_required
def lost_found_detail(report_id):
    db = get_db()
    report = db.execute(
        """SELECT r.*, s.name AS reporter_name FROM lost_found_reports r
           JOIN students s ON s.id = r.student_id WHERE r.id = ?""",
        (report_id,),
    ).fetchone()
    if report is None:
        abort(404)
    contact_requests = record_contact_requests("lost_found", report_id) if report["student_id"] == session["student_id"] else []
    return render_template("lost_found_detail.html", report=report, contact_requests=contact_requests)


@app.route("/lost-found/<int:report_id>/edit", methods=["GET", "POST"])
@login_required
def lost_found_edit(report_id):
    report = owned_record("lost_found_reports", report_id)
    form = request.form if request.method == "POST" else dict(report)
    if request.method == "POST":
        item_name = request.form.get("item_name", "").strip()
        description = request.form.get("description", "").strip()
        category = request.form.get("category", "").strip()
        location = request.form.get("location", "").strip()
        incident_date = request.form.get("incident_date", "").strip()
        report_type = request.form.get("report_type", "").strip()
        errors = []
        if not item_name or len(item_name) > 100:
            errors.append("Enter an item name of 1 to 100 characters.")
        if not description or len(description) > 2000:
            errors.append("Enter a description of 1 to 2,000 characters.")
        if category not in LOST_FOUND_CATEGORIES:
            errors.append("Choose a valid category.")
        if not location or len(location) > 120:
            errors.append("Enter a location of 1 to 120 characters.")
        if not valid_date(incident_date):
            errors.append("Choose a valid date that is not in the future.")
        if report_type not in {"Lost", "Found"}:
            errors.append("Choose whether the item was lost or found.")
        image_data, image_extension, image_error = parse_optional_image()
        if image_error:
            errors.append(image_error)
        if not errors:
            image_filename = (
                save_uploaded_image(image_data, image_extension)
                if image_data
                else report["image_filename"]
            )
            db = get_db()
            db.execute(
                """UPDATE lost_found_reports SET item_name = ?, description = ?, category = ?,
                   location = ?, incident_date = ?, report_type = ?, image_filename = ?,
                   updated_at = CURRENT_TIMESTAMP WHERE id = ? AND student_id = ?""",
                (
                    item_name, description, category, location, incident_date, report_type,
                    image_filename, report_id, session["student_id"],
                ),
            )
            db.commit()
            if image_data:
                remove_uploaded_image(report["image_filename"])
            flash("Your lost and found report was updated.", "success")
            return redirect(url_for("lost_found_detail", report_id=report_id))
        for error in errors:
            flash(error, "danger")
    return render_template(
        "lost_found_form.html",
        report=report,
        form=form,
        categories=LOST_FOUND_CATEGORIES,
        today=today_iso(),
    )


@app.route("/lost-found/<int:report_id>/delete", methods=["POST"])
@login_required
def lost_found_delete(report_id):
    report = owned_record("lost_found_reports", report_id)
    db = get_db()
    db.execute("DELETE FROM contact_requests WHERE entity_type = 'lost_found' AND entity_id = ?", (report_id,))
    db.execute(
        "DELETE FROM lost_found_reports WHERE id = ? AND student_id = ?",
        (report_id, session["student_id"]),
    )
    db.commit()
    remove_uploaded_image(report["image_filename"])
    flash("Your lost and found report was deleted.", "success")
    return redirect(url_for("lost_found_hub"))


@app.route("/lost-found/<int:report_id>/status", methods=["POST"])
@login_required
def lost_found_status(report_id):
    owned_record("lost_found_reports", report_id)
    status = request.form.get("status", "").strip()
    if status not in {"active", "resolved"}:
        flash("Choose a valid report status.", "danger")
        return redirect(url_for("lost_found_detail", report_id=report_id))
    get_db().execute(
        """UPDATE lost_found_reports SET status = ?, updated_at = CURRENT_TIMESTAMP
           WHERE id = ? AND student_id = ?""",
        (status, report_id, session["student_id"]),
    )
    get_db().commit()
    flash("Report status was updated.", "success")
    return redirect(url_for("lost_found_detail", report_id=report_id))


@app.route("/community/contact/<entity_type>/<int:entity_id>", methods=["POST"])
@login_required
def community_contact(entity_type, entity_id):
    if entity_type not in {"exchange", "lost_found"}:
        abort(404)
    return save_contact_request(entity_type, entity_id)


@app.errorhandler(400)
@app.errorhandler(403)
@app.errorhandler(404)
@app.errorhandler(413)
def handle_http_error(error):
    return render_template("error.html", error=error), error.code


with app.app_context():
    init_db()


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1")