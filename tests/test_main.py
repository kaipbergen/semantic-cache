def test_query_rejects_empty_prompt(api_client):
    response = api_client.post("/query", json={"prompt": ""})
    assert response.status_code == 400


def test_query_rejects_whitespace_only_prompt(api_client):
    response = api_client.post("/query", json={"prompt": "   \t\n  "})
    assert response.status_code == 400
