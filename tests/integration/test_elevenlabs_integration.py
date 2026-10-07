import os
import pytest
import requests

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")


@pytest.mark.skipif(
    not ELEVENLABS_API_KEY, reason="No ELEVENLABS_API_KEY set in environment."
)
def test_elevenlabs_get_voices():
    """
    Test the ElevenLabs /v1/voices endpoint to list available voices.
    Skips if ELEVENLABS_API_KEY is not set.
    """
    headers = {"xi-api-key": ELEVENLABS_API_KEY}
    resp = requests.get("https://api.elevenlabs.io/v1/voices", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "voices" in data
    assert isinstance(data["voices"], list)
    print(f"Available voices: {[v['name'] for v in data['voices']]}")
