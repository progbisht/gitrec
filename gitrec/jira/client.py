import requests
import json
from typing import Dict, Any, Optional, List
from base64 import b64encode


class JiraClient:
    def __init__(self, base_url: str, email: Optional[str] = None, api_token: Optional[str] = None, personal_token: Optional[str] = None):
        self.base_url = base_url.rstrip("/")
        self.headers = {
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        if personal_token:
            self.headers["Authorization"] = f"Bearer {personal_token}"
        elif email and api_token:
            auth_str = f"{email}:{api_token}"
            encoded = b64encode(auth_str.encode()).decode("ascii")
            self.headers["Authorization"] = f"Basic {encoded}"

    def test_connection(self) -> Dict[str, Any]:
        resp = requests.get(f"{self.base_url}/rest/api/3/myself", headers=self.headers)
        if resp.status_code != 200:
            # Fallback to Jira REST v2
            resp = requests.get(f"{self.base_url}/rest/api/2/myself", headers=self.headers)
        resp.raise_for_status()
        return resp.json()

    def get_project(self, project_key: str) -> Dict[str, Any]:
        resp = requests.get(f"{self.base_url}/rest/api/2/project/{project_key}", headers=self.headers)
        resp.raise_for_status()
        return resp.json()

    def create_issue(self, fields: Dict[str, Any], use_v3: bool = True) -> Dict[str, Any]:
        url = f"{self.base_url}/rest/api/3/issue" if use_v3 else f"{self.base_url}/rest/api/2/issue"
        resp = requests.post(url, headers=self.headers, json={"fields": fields})
        resp.raise_for_status()
        return resp.json()

    def update_issue(self, issue_key: str, fields: Dict[str, Any], use_v3: bool = True) -> Dict[str, Any]:
        url = f"{self.base_url}/rest/api/3/issue/{issue_key}" if use_v3 else f"{self.base_url}/rest/api/2/issue/{issue_key}"
        resp = requests.put(url, headers=self.headers, json={"fields": fields})
        resp.raise_for_status()
        return {"key": issue_key, "status": "updated"}

    def get_transitions(self, issue_key: str) -> List[Dict[str, Any]]:
        url = f"{self.base_url}/rest/api/3/issue/{issue_key}/transitions"
        resp = requests.get(url, headers=self.headers)
        if resp.status_code != 200:
            resp = requests.get(f"{self.base_url}/rest/api/2/issue/{issue_key}/transitions", headers=self.headers)
        if resp.status_code == 200:
            return resp.json().get("transitions", [])
        return []

    def transition_issue(self, issue_key: str, transition_id: str) -> bool:
        url = f"{self.base_url}/rest/api/3/issue/{issue_key}/transitions"
        resp = requests.post(url, headers=self.headers, json={"transition": {"id": transition_id}})
        if resp.status_code not in [200, 204]:
            resp = requests.post(f"{self.base_url}/rest/api/2/issue/{issue_key}/transitions", headers=self.headers, json={"transition": {"id": transition_id}})
        return resp.status_code in [200, 204]

    def create_remote_link(self, issue_key: str, url: str, title: str, summary: Optional[str] = None, icon_url: Optional[str] = None) -> bool:
        """Link a GitHub PR, branch, or commit as a native Jira Remote Issue Link / Development link."""
        link_url = f"{self.base_url}/rest/api/3/issue/{issue_key}/remotelink"
        payload = {
            "object": {
                "url": url,
                "title": title,
                "summary": summary or title,
                "icon": {
                    "url16x16": icon_url or "https://github.githubassets.com/favicons/favicon.png",
                    "title": "GitHub"
                }
            }
        }
        try:
            resp = requests.post(link_url, headers=self.headers, json=payload, timeout=10)
            if resp.status_code not in [200, 201]:
                resp = requests.post(f"{self.base_url}/rest/api/2/issue/{issue_key}/remotelink", headers=self.headers, json=payload, timeout=10)
            return resp.status_code in [200, 201]
        except Exception:
            return False



