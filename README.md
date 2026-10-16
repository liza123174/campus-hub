# Campus Hub

Campus Hub is a student-focused college portal built with Flask, Jinja2, SQLite, HTML, CSS, Bootstrap 5, and vanilla JavaScript. It includes notices, internship and placement listings, student registration/login, profile management, a student Exchange Hub, and Lost & Found reports.

All listings shipped with the project are fictional demo data. They are provided to demonstrate the application and are not official college opportunities.

## Requirements

- Python 3.10 or newer
- pip
- A web browser

## Run locally

From the project folder, create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

On Windows PowerShell, activate it with:

```powershell
.\.venv\Scripts\Activate.ps1
```

Install Flask and start the app:

```bash
python -m pip install -r requirements.txt
python app.py
```

Open <http://127.0.0.1:5000>. The database is created automatically at `instance/campus_hub.db`, and sample rows are only added when the relevant table is empty.

For a stable local session key, set `SECRET_KEY` before starting the app. For example:

```bash
export SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
python app.py
```

In PowerShell:

```powershell
$env:SECRET_KEY = python -c "import secrets; print(secrets.token_hex(32))"
python app.py
```

The app uses a temporary random secret if `SECRET_KEY` is omitted; sessions will be invalidated when the process restarts. `.env.example` documents supported settings, but the project intentionally does not load `.env` files automatically.

## Try the main flows

1. Open `/register` and create a student account using any valid email format. College-domain enforcement is not enabled in this prototype.
2. Visit the dashboard and explore Notices, Internship Hub, and Placement Hub. Search and filters update the displayed records.
3. Open any listing for its detail view. Demo internships intentionally have no application URL, so the UI does not invent or link to a real application.
4. Use **Exchange hub** to post an item. Use a price of `0` for a free item; optionally attach a PNG, JPEG, GIF, or WebP image up to 2 MB. Edit, delete, and availability controls are only available to the owner.
5. Use **Lost & Found** to report an item as Lost or Found. Filter reports and mark your own report resolved when it is no longer active.
6. Use the private contact form on another student's item/report page. Messages are stored in SQLite and shown only to the record owner; account email addresses are never shown as contact details.
7. Visit Profile to update your name or department, then sign out and sign back in.

Run the automated checks with:

```bash
python -m unittest discover -s tests -v
```

## Exchange and Lost & Found data

The `exchange_listings` and `lost_found_reports` tables refer to their student owner through a foreign key. `contact_requests` stores short private messages tied to a listing/report and the two students. Tables and indexes are added using `CREATE TABLE/INDEX IF NOT EXISTS`, which leaves existing student accounts, notices, internships, and placements untouched.

Uploaded images are stored in `static/uploads/`, not in SQLite. The server limits uploads to 2 MB per image, checks file signatures instead of trusting the browser filename, generates a random safe filename, and accepts only PNG, JPEG, GIF, and WebP. A missing image is allowed.

## Project structure

```text
app.py                 Flask routes, SQLite setup, seed data, and validation
templates/             Jinja2 pages and shared layout
static/css/style.css   Responsive visual styles
static/js/main.js      Small client-side enhancements
static/uploads/        Optional user-submitted item images
instance/              Automatically generated local SQLite database
```

## Security and prototype scope

- Passwords are stored as Werkzeug password hashes, not plaintext.
- Forms use a session-based CSRF token and protected pages require a student session.
- Database values are passed through SQLite parameterized queries.
- Community changes require a signed-in student, POST plus CSRF token, and a server-side ownership check. Other students can send a short private contact request without seeing the owner's email address.
- Uploaded files are size-limited, signature-checked, and assigned random filenames; use object storage and malware scanning before operating a public production upload service.
- Set a private, stable `SECRET_KEY` before deployment. Turn off `FLASK_DEBUG` in production and serve through a production WSGI server.
- College-email domain restrictions, email verification, password recovery, admin publishing tools, and production-grade account controls are intentionally out of scope for this student prototype. Add and test those before real deployment.
- Bootstrap and Bootstrap Icons are loaded from public CDNs; an internet connection is needed for those visual assets. The application itself does not call paid APIs or require external services.

## Future containers and cloud deployment

The current app remains a simple Flask application and keeps its existing local port and run behavior. A future Docker image can install `requirements.txt` and run Flask through a production WSGI server rather than debug mode. Mount persistent storage for the SQLite database under `instance/` and for user uploads under `static/uploads/`; container-local files disappear when a container is replaced. For a multi-instance production service, move SQLite and local image storage to managed persistent services (for example, a relational database and object storage) and keep `SECRET_KEY` in the deployment platform's secret configuration. This repository does not create cloud resources or include deployment credentials.
