import pytest

from app import create_app
from extensions import db
from models.user import User


@pytest.fixture(scope="module")
def app():
    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    return app

@pytest.fixture(scope="module")
def client(app):
    return app.test_client()

def test_profile_view_and_update(client, app):
    email = "profile_idempotent_tester@example.com"
    with app.app_context():
        user = User.query.filter_by(email=email).first()
        if not user:
            user = User(name="Initial Name", email=email)
            db.session.add(user)
        user.name = "Initial Name"
        user.set_password("OldPassword123!")
        db.session.commit()

    # Login with current password
    login_res = client.post("/login", data={"email": email, "password": "OldPassword123!"}, follow_redirects=True)
    assert login_res.status_code == 200

    # 1. View profile page
    res = client.get("/profile")
    assert res.status_code == 200
    assert b"Personal Information" in res.data
    assert b"Change Password" in res.data
    assert b"Initial Name" in res.data

    # 2. Update name
    update_res = client.post("/profile", data={
        "action": "update_name",
        "name": "Updated Name"
    }, follow_redirects=True)
    assert update_res.status_code == 200
    assert b"Profile name updated successfully!" in update_res.data
    assert b"Updated Name" in update_res.data

    # 3. Update password - wrong current password
    bad_pw_res = client.post("/profile", data={
        "action": "update_password",
        "current_password": "WrongPassword",
        "new_password": "NewPassword123!",
        "confirm_password": "NewPassword123!"
    }, follow_redirects=True)
    assert b"Current password is incorrect." in bad_pw_res.data

    # 4. Update password - mismatch
    mismatch_pw_res = client.post("/profile", data={
        "action": "update_password",
        "current_password": "OldPassword123!",
        "new_password": "NewPassword123!",
        "confirm_password": "DifferentPassword!"
    }, follow_redirects=True)
    assert b"New passwords do not match." in mismatch_pw_res.data

    # 5. Update password - success
    good_pw_res = client.post("/profile", data={
        "action": "update_password",
        "current_password": "OldPassword123!",
        "new_password": "NewPassword123!",
        "confirm_password": "NewPassword123!"
    }, follow_redirects=True)
    assert b"Password changed successfully!" in good_pw_res.data

    # Verify new password works on login
    client.get("/logout")
    new_login_res = client.post("/login", data={"email": email, "password": "NewPassword123!"}, follow_redirects=True)
    assert new_login_res.status_code == 200
    assert b"Welcome" in new_login_res.data or b"Dashboard" in new_login_res.data or b"Home" in new_login_res.data
