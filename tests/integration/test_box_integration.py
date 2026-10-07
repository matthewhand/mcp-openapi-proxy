import os
import pytest
import requests

BOX_API_KEY = os.getenv("BOX_API_KEY")

skip_box = not BOX_API_KEY or "your_key" in BOX_API_KEY.lower()


def _skip_if_unauthorized(resp):
    if resp.status_code == 401:
        pytest.skip("Box API key is set but unauthorized (401). Skipping test.")


@pytest.mark.skipif(skip_box, reason="No valid BOX_API_KEY set in environment.")
def test_box_get_folder_info():
    folder_id = "0"  # Root folder
    headers = {"Authorization": f"Bearer {BOX_API_KEY}"}
    resp = requests.get(f"https://api.box.com/2.0/folders/{folder_id}", headers=headers)
    _skip_if_unauthorized(resp)
    assert resp.status_code == 200
    data = resp.json()
    assert "id" in data and data["id"] == folder_id
    assert "name" in data
    assert data["type"] == "folder"


@pytest.mark.skipif(skip_box, reason="No valid BOX_API_KEY set in environment.")
def test_box_list_files_and_folders():
    folder_id = "0"  # Root folder
    headers = {"Authorization": f"Bearer {BOX_API_KEY}"}
    resp = requests.get(f"https://api.box.com/2.0/folders/{folder_id}", headers=headers)
    _skip_if_unauthorized(resp)
    assert resp.status_code == 200
    data = resp.json()
    assert "item_collection" in data
    entries = data["item_collection"]["entries"]
    assert isinstance(entries, list)
    # Print the filenames/types for debug
    print("\nBox root folder contents:")
    for entry in entries:
        print(f"  {entry['type']}: {entry['name']} (id: {entry['id']})")
    # Optionally check at least one entry
    if entries:
        entry = entries[0]
        assert "type" in entry
        assert "id" in entry
        assert "name" in entry
