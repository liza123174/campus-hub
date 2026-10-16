import re
import tempfile
import unittest
from io import BytesIO
from pathlib import Path

import app as campus


class CommunityModuleTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_database_path = campus.DATABASE_PATH
        self.original_upload_folder = campus.app.config["UPLOAD_FOLDER"]
        campus.DATABASE_PATH = Path(self.temp_dir.name) / "test_campus_hub.db"
        campus.app.config["UPLOAD_FOLDER"] = Path(self.temp_dir.name) / "uploads"
        campus.app.config.update(TESTING=True, SECRET_KEY="test-secret", MAX_CONTENT_LENGTH=campus.MAX_IMAGE_BYTES + 128 * 1024)
        with campus.app.app_context():
            campus.init_db()
        self.client = campus.app.test_client()
        self.register("owner@example.edu", "Listing Owner")

    def tearDown(self):
        campus.DATABASE_PATH = self.original_database_path
        campus.app.config["UPLOAD_FOLDER"] = self.original_upload_folder
        self.temp_dir.cleanup()

    def csrf_token(self, _page):
        response = self.client.get("/dashboard")
        if response.status_code != 200:
            response = self.client.get("/register")
        self.assertEqual(response.status_code, 200)
        match = re.search(rb'name="csrf_token" value="([^"]+)"', response.data)
        self.assertIsNotNone(match)
        return match.group(1).decode()

    def post_form(self, page, data, **kwargs):
        data = dict(data)
        data["csrf_token"] = self.csrf_token(page)
        return self.client.post(page, data=data, **kwargs)

    def register(self, email, name):
        return self.post_form(
            "/register",
            {
                "name": name,
                "email": email,
                "department": "Computer Science",
                "password": "test-password-123",
            },
        )

    def exchange_data(self, **overrides):
        data = {
            "title": "Calculus textbook",
            "description": "Good condition, latest edition.",
            "category": "Books",
            "price": "0",
        }
        data.update(overrides)
        return data

    def report_data(self, **overrides):
        data = {
            "item_name": "Blue water bottle",
            "description": "Found beside the main library entrance.",
            "category": "Other",
            "location": "Main library entrance",
            "incident_date": "2026-10-15",
            "report_type": "Found",
        }
        data.update(overrides)
        return data

    def switch_to_student(self, email, name):
        self.post_form("/logout", {})
        with campus.app.app_context():
            exists = campus.get_db().execute(
                "SELECT 1 FROM students WHERE email = ?",
                (email,),
            ).fetchone()
        if exists:
            self.post_form("/login", {"email": email, "password": "test-password-123"})
        else:
            self.register(email, name)

    def test_existing_dashboard_and_modules_still_render(self):
        for path in (
            "/dashboard", "/notices", "/internships", "/placements", "/profile",
            "/exchange", "/lost-found",
        ):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)
        dashboard = self.client.get("/dashboard").data
        self.assertIn(b"Recent exchange listings", dashboard)
        self.assertIn(b"Recent lost", dashboard)

    def test_registration_login_logout_and_protected_access(self):
        self.assertEqual(self.client.get("/register").status_code, 302)
        self.post_form("/logout", {})
        self.assertEqual(self.client.get("/dashboard").status_code, 302)
        failed_login = self.post_form(
            "/login",
            {"email": "owner@example.edu", "password": "incorrect-password"},
        )
        self.assertEqual(failed_login.status_code, 200)
        successful_login = self.post_form(
            "/login",
            {"email": "owner@example.edu", "password": "test-password-123"},
        )
        self.assertEqual(successful_login.status_code, 302)
        self.assertEqual(self.client.get("/dashboard").status_code, 200)

    def test_exchange_create_search_filter_edit_status_and_delete(self):
        response = self.post_form("/exchange/new", self.exchange_data())
        self.assertEqual(response.status_code, 302)
        listing_id = self._single_id("exchange_listings")

        self.assertIn(b"Calculus textbook", self.client.get("/exchange?q=Calculus").data)
        self.assertIn(b"Calculus textbook", self.client.get("/exchange?category=Books&price=free").data)
        self.assertNotIn(b"Calculus textbook", self.client.get("/exchange?price=priced").data)

        response = self.post_form(
            f"/exchange/{listing_id}/edit",
            self.exchange_data(title="Updated textbook", price="12.50", status="available"),
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn(b"Updated textbook", self.client.get(f"/exchange/{listing_id}").data)

        self.assertEqual(
            self.post_form(f"/exchange/{listing_id}/status", {"status": "sold"}).status_code,
            302,
        )
        self.assertNotIn(b"Updated textbook", self.client.get("/exchange").data)
        self.assertEqual(
            self.post_form(f"/exchange/{listing_id}/delete", {}).status_code,
            302,
        )
        self.assertEqual(self.client.get(f"/exchange/{listing_id}").status_code, 404)

    def test_listing_ownership_and_csrf_are_enforced(self):
        self.post_form("/exchange/new", self.exchange_data())
        listing_id = self._single_id("exchange_listings")
        self.switch_to_student("other@example.edu", "Other Student")
        self.assertEqual(self.client.get(f"/exchange/{listing_id}/edit").status_code, 403)
        self.assertEqual(
            self.post_form(f"/exchange/{listing_id}/delete", {}).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(f"/exchange/{listing_id}/status", data={"status": "sold"}).status_code,
            400,
        )

    def test_lost_and_found_reports_filter_edit_resolve_and_delete(self):
        self.post_form("/lost-found/new", self.report_data())
        report_id = self._single_id("lost_found_reports")
        self.assertIn(b"Blue water bottle", self.client.get("/lost-found?q=water&type=Found").data)
        self.assertEqual(self.client.get("/lost-found?status=resolved").data.count(b"Blue water bottle"), 0)

        response = self.post_form(
            f"/lost-found/{report_id}/edit",
            self.report_data(item_name="Green water bottle", report_type="Lost"),
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn(b"Green water bottle", self.client.get(f"/lost-found/{report_id}").data)

        self.assertEqual(
            self.post_form(f"/lost-found/{report_id}/status", {"status": "resolved"}).status_code,
            302,
        )
        self.assertIn(b"Green water bottle", self.client.get("/lost-found?status=resolved").data)
        self.assertEqual(self.post_form(f"/lost-found/{report_id}/delete", {}).status_code, 302)
        self.assertEqual(self.client.get(f"/lost-found/{report_id}").status_code, 404)

    def test_lost_report_and_status_validation_and_ownership(self):
        response = self.post_form("/lost-found/new", self.report_data(report_type="Found"))
        self.assertEqual(response.status_code, 302)
        report_id = self._single_id("lost_found_reports")
        self.switch_to_student("other@example.edu", "Other Student")
        self.assertEqual(self.client.get(f"/lost-found/{report_id}/edit").status_code, 403)
        self.switch_to_student("owner@example.edu", "Listing Owner")
        self.assertEqual(
            self.post_form(f"/lost-found/{report_id}/status", {"status": "deleted"}).status_code,
            302,
        )
        self.assertEqual(self.client.get(f"/lost-found/{report_id}").status_code, 200)

    def test_invalid_forms_and_missing_records_are_handled(self):
        invalid_exchange = self.post_form(
            "/exchange/new",
            self.exchange_data(title="", category="not-a-category", price="-1"),
            follow_redirects=True,
        )
        self.assertIn(b"valid category", invalid_exchange.data)
        invalid_report = self.post_form(
            "/lost-found/new",
            self.report_data(category="not-a-category", incident_date="2099-01-01"),
            follow_redirects=True,
        )
        self.assertIn(b"valid category", invalid_report.data)
        self.assertEqual(self.client.get("/exchange/99999").status_code, 404)
        self.assertEqual(self.client.get("/lost-found/99999").status_code, 404)

    def test_private_contact_request_does_not_show_email(self):
        self.post_form("/exchange/new", self.exchange_data())
        listing_id = self._single_id("exchange_listings")
        self.switch_to_student("other@example.edu", "Other Student")
        response = self.post_form(
            f"/community/contact/exchange/{listing_id}",
            {"message": "Is the book still available?"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertNotIn(b"owner@example.edu", self.client.get(f"/exchange/{listing_id}").data)
        self.switch_to_student("owner@example.edu", "Listing Owner")
        detail = self.client.get(f"/exchange/{listing_id}").data
        self.assertIn(b"Is the book still available?", detail)
        self.assertIn(b"Other Student", detail)
        self.assertNotIn(b"other@example.edu", detail)

    def test_image_signatures_and_optional_images(self):
        self.post_form("/exchange/new", self.exchange_data())
        listing_id = self._single_id("exchange_listings")
        fake_image = (BytesIO(b"not an image"), "bad.png", "image/png")
        response = self.post_form(
            f"/exchange/{listing_id}/edit",
            {**self.exchange_data(title="Bad image test", status="available"), "image": fake_image},
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        self.assertIn(b"valid PNG, JPEG, GIF, or WebP image", response.data)
        good_image = (BytesIO(b"\x89PNG\r\n\x1a\nsmall demo"), "photo.png", "image/png")
        response = self.post_form(
            f"/exchange/{listing_id}/edit",
            {**self.exchange_data(title="Image attached", status="available"), "image": good_image},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 302)
        with campus.app.app_context():
            listing = campus.get_db().execute(
                "SELECT image_filename FROM exchange_listings WHERE id = ?",
                (listing_id,),
            ).fetchone()
        self.assertRegex(listing["image_filename"], r"^[a-f0-9]{32}\.png$")

    def test_database_initialization_is_repeat_safe(self):
        with campus.app.app_context():
            db = campus.get_db()
            db.execute(
                "INSERT INTO exchange_listings (student_id, title, description, category, price) VALUES (?, ?, ?, ?, ?)",
                (1, "Saved listing", "Existing data stays.", "Books", 0),
            )
            db.commit()
            campus.init_db()
            count = db.execute("SELECT COUNT(*) FROM exchange_listings").fetchone()[0]
            self.assertEqual(count, 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM notices").fetchone()[0], 4)

    def _single_id(self, table):
        with campus.app.app_context():
            return campus.get_db().execute(f"SELECT id FROM {table} ORDER BY id DESC LIMIT 1").fetchone()["id"]


if __name__ == "__main__":
    unittest.main()
