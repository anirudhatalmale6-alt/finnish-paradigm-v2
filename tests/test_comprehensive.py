"""
Comprehensive test suite for the Finnish Paradigm EdTech platform.
Covers authentication, admin dashboard, security, assessments,
enrollments, bookings, progress tracking, and intervention cases.
"""

import uuid
import sqlite3
import pytest
from fastapi.testclient import TestClient
from backend.app.main import app, DB_PATH, sign_token, rate_limiter

client = TestClient(app)


@pytest.fixture(autouse=True)
def _clear_rate_limiter():
    """Reset the in-memory rate limiter before every test to avoid 429s."""
    rate_limiter._attempts.clear()
    yield
    rate_limiter._attempts.clear()


# ─────────────────────── helpers ───────────────────────

def _unique_email(prefix: str = "user") -> str:
    """Generate a unique email to avoid collisions across test runs."""
    return f"{prefix}_{uuid.uuid4().hex[:10]}@test.example.com"


def register_user(role: str = "learner", email: str | None = None,
                  password: str = "StrongPass123", name: str = "Test User"):
    """Register a user and return the full response JSON + status code."""
    email = email or _unique_email(role)
    r = client.post("/api/auth/register", json={
        "name": name, "email": email, "password": password, "role": role
    })
    return r


def get_auth_headers(role: str = "learner") -> dict:
    """Register a fresh user and return Authorization headers."""
    r = register_user(role=role)
    assert r.status_code == 200, f"Registration failed: {r.text}"
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def get_admin_headers() -> dict:
    """Create a user, promote to admin in the DB, re-login, return headers."""
    email = _unique_email("admin")
    r = register_user(role="learner", email=email)
    assert r.status_code == 200
    # Promote in DB
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE users SET role='admin' WHERE email=?", (email,))
    conn.commit()
    conn.close()
    # Re-login to get a token with the admin role baked in
    r2 = client.post("/api/auth/login", json={"email": email, "password": "StrongPass123"})
    assert r2.status_code == 200
    return {"Authorization": f"Bearer {r2.json()['access_token']}"}


# ═══════════════════════════════════════════════════════
#  AUTHENTICATION TESTS (1-13)
# ═══════════════════════════════════════════════════════

class TestAuthentication:
    """Tests 1-13: registration, login, token validation."""

    # 1. Register learner
    def test_01_register_learner(self):
        r = register_user(role="learner")
        assert r.status_code == 200
        data = r.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["user"]["role"] == "learner"
        assert "id" in data["user"]
        assert "name" in data["user"]
        assert "email" in data["user"]

    # 2. Register teacher
    def test_02_register_teacher(self):
        r = register_user(role="teacher")
        assert r.status_code == 200
        assert r.json()["user"]["role"] == "teacher"

    # 3. Register as "manager" -> downgraded to learner
    def test_03_register_manager_downgraded(self):
        r = register_user(role="manager")
        assert r.status_code == 200
        assert r.json()["user"]["role"] == "learner"

    # 4. Register as "admin" -> downgraded to learner
    def test_04_register_admin_downgraded(self):
        r = register_user(role="admin")
        assert r.status_code == 200
        assert r.json()["user"]["role"] == "learner"

    # 5. Register with existing email -> 409
    def test_05_register_duplicate_email(self):
        email = _unique_email("dup")
        r1 = register_user(email=email)
        assert r1.status_code == 200
        r2 = register_user(email=email)
        assert r2.status_code == 409

    # 6. Login with correct credentials
    def test_06_login_correct(self):
        email = _unique_email("login")
        register_user(email=email)
        r = client.post("/api/auth/login", json={
            "email": email, "password": "StrongPass123"
        })
        assert r.status_code == 200
        data = r.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["user"]["email"] == email

    # 7. Login with wrong password -> 401
    def test_07_login_wrong_password(self):
        email = _unique_email("wrongpw")
        register_user(email=email)
        r = client.post("/api/auth/login", json={
            "email": email, "password": "WrongPassword999"
        })
        assert r.status_code == 401

    # 8. Login with non-existent email -> 401
    def test_08_login_nonexistent_email(self):
        r = client.post("/api/auth/login", json={
            "email": "nobody_exists_here@fake.example.com",
            "password": "Whatever123"
        })
        assert r.status_code == 401

    # 9. /api/auth/me with valid token
    def test_09_me_valid_token(self):
        h = get_auth_headers("learner")
        r = client.get("/api/auth/me", headers=h)
        assert r.status_code == 200
        data = r.json()
        assert "id" in data
        assert "email" in data
        assert "role" in data

    # 10. /api/auth/me without token -> 401
    def test_10_me_no_token(self):
        r = client.get("/api/auth/me")
        assert r.status_code == 401

    # 11. /api/auth/me with invalid token -> 401
    def test_11_me_invalid_token(self):
        r = client.get("/api/auth/me", headers={
            "Authorization": "Bearer totally.invalid.token"
        })
        assert r.status_code == 401

    # 12. Register with short password (<8 chars) -> 422
    def test_12_register_short_password(self):
        r = register_user(password="Short1")
        assert r.status_code == 422

    # 13. Register with invalid email -> 422
    def test_13_register_invalid_email(self):
        r = client.post("/api/auth/register", json={
            "name": "Bad Email", "email": "not-an-email",
            "password": "StrongPass123", "role": "learner"
        })
        assert r.status_code == 422


# ═══════════════════════════════════════════════════════
#  ADMIN ROUTE PROTECTION TESTS (14-23)
# ═══════════════════════════════════════════════════════

class TestAdminRouteProtection:
    """Tests 14-23: ensure admin endpoints reject unauthorized access."""

    # 14. /api/admin/summary no auth -> 401
    def test_14_admin_summary_no_auth(self):
        r = client.get("/api/admin/summary")
        assert r.status_code == 401

    # 15. /api/admin/summary as learner -> 403
    def test_15_admin_summary_as_learner(self):
        h = get_auth_headers("learner")
        r = client.get("/api/admin/summary", headers=h)
        assert r.status_code == 403

    # 16. /api/admin/summary as teacher -> 403
    def test_16_admin_summary_as_teacher(self):
        h = get_auth_headers("teacher")
        r = client.get("/api/admin/summary", headers=h)
        assert r.status_code == 403

    # 17. /api/admin/summary as admin -> 200
    def test_17_admin_summary_as_admin(self):
        h = get_admin_headers()
        r = client.get("/api/admin/summary", headers=h)
        assert r.status_code == 200

    # 18. /api/admin/bookings as non-admin -> 403
    def test_18_admin_bookings_non_admin(self):
        h = get_auth_headers("learner")
        r = client.get("/api/admin/bookings", headers=h)
        assert r.status_code == 403

    # 19. /api/admin/enrollments as non-admin -> 403
    def test_19_admin_enrollments_non_admin(self):
        h = get_auth_headers("teacher")
        r = client.get("/api/admin/enrollments", headers=h)
        assert r.status_code == 403

    # 20. /api/admin/users as admin -> 200 + no password_hash
    def test_20_admin_users_no_password_hash(self):
        h = get_admin_headers()
        r = client.get("/api/admin/users", headers=h)
        assert r.status_code == 200
        users = r.json()
        assert isinstance(users, list)
        assert len(users) > 0
        for user in users:
            assert "password_hash" not in user, \
                "password_hash must not be exposed in admin user listing"

    # 21. /api/admin/item-bank POST as non-admin -> 403
    def test_21_admin_item_bank_post_non_admin(self):
        h = get_auth_headers("teacher")
        r = client.post("/api/admin/item-bank", json={
            "course_id": "fcfp", "difficulty": 1, "skill": "test",
            "question": "Q?", "options": ["A", "B"], "correct": "A",
            "explanation": "Because."
        }, headers=h)
        assert r.status_code == 403

    # 22. /api/admin/intervention-cases POST as non-admin -> 403
    def test_22_admin_intervention_cases_non_admin(self):
        h = get_auth_headers("learner")
        r = client.post("/api/admin/intervention-cases", json={
            "student_code": "S001", "class_group": "3A",
            "risk_level": "high", "concern": "Attendance",
            "evidence": "Missed 5 days", "tier": 2
        }, headers=h)
        assert r.status_code == 403

    # 23. /api/stripe/readiness as non-admin -> 403
    def test_23_stripe_readiness_non_admin(self):
        h = get_auth_headers("learner")
        r = client.get("/api/stripe/readiness", headers=h)
        assert r.status_code == 403


# ═══════════════════════════════════════════════════════
#  ITEM BANK SECURITY (24-25)
# ═══════════════════════════════════════════════════════

class TestItemBankSecurity:
    """Tests 24-25: learners must not see correct answers."""

    # 24. Learner sees items but NOT the 'correct' field
    def test_24_item_bank_learner_no_correct(self):
        h = get_auth_headers("learner")
        r = client.get("/api/item-bank", headers=h)
        assert r.status_code == 200
        items = r.json()
        assert len(items) > 0
        for item in items:
            assert "correct" not in item, \
                "Learners must NOT see the 'correct' field in item-bank"

    # 25. Admin sees items WITH the 'correct' field
    def test_25_item_bank_admin_has_correct(self):
        h = get_admin_headers()
        r = client.get("/api/item-bank", headers=h)
        assert r.status_code == 200
        items = r.json()
        assert len(items) > 0
        for item in items:
            assert "correct" in item, \
                "Admins must see the 'correct' field in item-bank"


# ═══════════════════════════════════════════════════════
#  ENROLLMENT TESTS (26-28)
# ═══════════════════════════════════════════════════════

class TestEnrollments:
    """Tests 26-28: enrollment logic."""

    # 26. Enroll in valid course
    def test_26_enroll_valid_course(self):
        h = get_auth_headers("learner")
        r = client.post("/api/enrollments", json={"course_id": "fcfp"}, headers=h)
        assert r.status_code == 200
        assert r.json()["status"] == "enrolled"
        assert r.json()["course_id"] == "fcfp"

    # 27. Enroll in non-existent course -> 404
    def test_27_enroll_nonexistent_course(self):
        h = get_auth_headers("learner")
        r = client.post("/api/enrollments", json={"course_id": "nonexistent_xyz"}, headers=h)
        assert r.status_code == 404

    # 28. Enroll without auth -> 401
    def test_28_enroll_no_auth(self):
        r = client.post("/api/enrollments", json={"course_id": "fcfp"})
        assert r.status_code == 401


# ═══════════════════════════════════════════════════════
#  ASSESSMENT SESSION TESTS (29-31)
# ═══════════════════════════════════════════════════════

class TestAssessmentSessions:
    """Tests 29-31: adaptive assessment flow."""

    # 29. Start assessment -> session_id and next_item
    def test_29_start_assessment(self):
        h = get_auth_headers("learner")
        r = client.post("/api/assessment/start", json={
            "learner_name": "Tester", "course_id": "fcfp"
        }, headers=h)
        assert r.status_code == 200
        data = r.json()
        assert "session_id" in data
        assert data["session_id"] > 0
        assert "next_item" in data
        assert data["next_item"] is not None
        assert "question" in data["next_item"]
        assert "options" in data["next_item"]

    # 30. Answer a question -> feedback + ability score
    def test_30_answer_question(self):
        h = get_auth_headers("learner")
        start = client.post("/api/assessment/start", json={
            "learner_name": "Tester", "course_id": "fcfp"
        }, headers=h).json()
        item = start["next_item"]
        r = client.post("/api/assessment/answer", json={
            "session_id": start["session_id"],
            "item_id": item["id"],
            "selected": item["options"][0]
        }, headers=h)
        assert r.status_code == 200
        data = r.json()
        assert "correct" in data  # True or False
        assert isinstance(data["correct"], bool)
        assert "explanation" in data
        assert "ability" in data
        assert isinstance(data["ability"], (int, float))

    # 31. Access another user's session -> 403
    def test_31_access_other_users_session(self):
        # User A starts a session
        h_a = get_auth_headers("learner")
        start = client.post("/api/assessment/start", json={
            "learner_name": "User A", "course_id": "fcfp"
        }, headers=h_a).json()
        session_id = start["session_id"]

        # User B tries to get next item for User A's session
        h_b = get_auth_headers("learner")
        r = client.get(f"/api/assessment/{session_id}/next", headers=h_b)
        assert r.status_code == 403


# ═══════════════════════════════════════════════════════
#  BOOKING TESTS (32-33)
# ═══════════════════════════════════════════════════════

class TestBookings:
    """Tests 32-33: booking creation."""

    # 32. Create a booking
    def test_32_create_booking(self):
        r = client.post("/api/bookings", json={
            "name": "Test Booker",
            "email": "booker@example.com",
            "organisation": "Test School",
            "audience": "Teachers",
            "preferred_date": "2026-07-01",
            "message": "Interested in workshop"
        })
        assert r.status_code == 200
        data = r.json()
        assert "id" in data
        assert data["status"] == "booked"

    # 33. Create booking with invalid email -> 422
    def test_33_booking_invalid_email(self):
        r = client.post("/api/bookings", json={
            "name": "Bad Email",
            "email": "not-valid",
            "organisation": "",
            "audience": "Teachers",
            "preferred_date": "2026-07-01",
            "message": ""
        })
        assert r.status_code == 422


# ═══════════════════════════════════════════════════════
#  PROGRESS TRACKING (34-35)
# ═══════════════════════════════════════════════════════

class TestProgressTracking:
    """Tests 34-35: lesson progress."""

    # 34. Mark lesson progress
    def test_34_mark_progress(self):
        h = get_auth_headers("learner")
        r = client.post("/api/my/progress", json={
            "course_id": "fcfp",
            "lesson_id": "module_1_lesson_1",
            "completed": True
        }, headers=h)
        assert r.status_code == 200
        assert r.json()["status"] == "saved"

    # 35. Get progress
    def test_35_get_progress(self):
        h = get_auth_headers("learner")
        # Mark something first
        client.post("/api/my/progress", json={
            "course_id": "fcfp",
            "lesson_id": "module_1_lesson_1",
            "completed": True
        }, headers=h)
        r = client.get("/api/my/progress", headers=h)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        assert data[0]["course_id"] == "fcfp"


# ═══════════════════════════════════════════════════════
#  ADMIN DASHBOARD DATA (36-40)
# ═══════════════════════════════════════════════════════

class TestAdminDashboard:
    """Tests 36-40: admin summary, users, intervention cases."""

    # 36. Admin summary has all expected keys
    def test_36_admin_summary_keys(self):
        h = get_admin_headers()
        r = client.get("/api/admin/summary", headers=h)
        assert r.status_code == 200
        data = r.json()
        expected_keys = {
            "bookings", "enrollments", "items",
            "assessment_sessions", "users", "open_cases", "orders"
        }
        assert expected_keys.issubset(set(data.keys())), \
            f"Missing keys: {expected_keys - set(data.keys())}"
        # All values should be non-negative integers
        for key in expected_keys:
            assert isinstance(data[key], int) and data[key] >= 0

    # 37. Admin can list users (no password hashes)
    def test_37_admin_list_users(self):
        h = get_admin_headers()
        r = client.get("/api/admin/users", headers=h)
        assert r.status_code == 200
        users = r.json()
        assert isinstance(users, list)
        assert len(users) >= 1
        for u in users:
            assert "password_hash" not in u
            assert "id" in u
            assert "email" in u
            assert "role" in u

    # 38. Admin can create intervention case
    def test_38_admin_create_intervention_case(self):
        h = get_admin_headers()
        r = client.post("/api/admin/intervention-cases", json={
            "student_code": "STU-001",
            "class_group": "4B",
            "risk_level": "high",
            "concern": "Repeated absences and declining grades",
            "evidence": "Missed 7 of last 10 sessions, IVF red 5 times",
            "tier": 2,
            "assigned_to": "Ms. Johnson"
        }, headers=h)
        assert r.status_code == 200
        data = r.json()
        assert "id" in data
        assert data["status"] == "open"

    # 39. Admin can list intervention cases
    def test_39_admin_list_intervention_cases(self):
        h = get_admin_headers()
        # Create one first
        client.post("/api/admin/intervention-cases", json={
            "student_code": "STU-002",
            "class_group": "3A",
            "risk_level": "medium",
            "concern": "Reading below benchmark",
            "evidence": "Tier 1 support not improving results",
            "tier": 1
        }, headers=h)
        r = client.get("/api/admin/intervention-cases", headers=h)
        assert r.status_code == 200
        cases = r.json()
        assert isinstance(cases, list)
        assert len(cases) >= 1
        # Verify case structure
        case = cases[0]
        assert "student_code" in case
        assert "status" in case
        assert "tier" in case

    # 40. Admin can close intervention case
    def test_40_admin_close_intervention_case(self):
        h = get_admin_headers()
        # Create a case
        create_r = client.post("/api/admin/intervention-cases", json={
            "student_code": "STU-CLOSE",
            "class_group": "5C",
            "risk_level": "low",
            "concern": "Minor attention issues",
            "evidence": "IVF yellow twice",
            "tier": 1
        }, headers=h)
        case_id = create_r.json()["id"]
        # Close it
        r = client.patch(f"/api/admin/intervention-cases/{case_id}/close", headers=h)
        assert r.status_code == 200
        assert r.json()["status"] == "closed"
