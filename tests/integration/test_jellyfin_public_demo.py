import requests


def test_jellyfin_public_system_info():
    resp = requests.get("https://demo.jellyfin.org/stable/System/Info/Public")
    assert resp.status_code == 200
    data = resp.json()
    assert "ServerName" in data
    assert data["ServerName"] == "Stable Demo"
    assert "Version" in data


def test_jellyfin_public_users():
    resp = requests.get("https://demo.jellyfin.org/stable/Users/Public")
    assert resp.status_code == 200
    users = resp.json()
    assert isinstance(users, list)
    assert any(u.get("Name") == "demo" for u in users)
