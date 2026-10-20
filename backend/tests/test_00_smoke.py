def test_smoke(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200, r.text
    print(r.json())
