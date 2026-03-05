import random
import string

from locust import HttpUser, between, task


class SurveyUser(HttpUser):
    wait_time = between(1, 3)
    token = None
    survey_id = None
    survey_fields = []

    def on_start(self):
        # Generate unique email per user to avoid conflicts
        suffix = "".join(random.choices(string.ascii_lowercase, k=8))
        self.email = f"loadtest_{suffix}@example.com"
        self.password = "loadtest123"

        # Register
        self.client.post("/api/v1/auth/register/", json={
            "email": self.email,
            "password": self.password,
            "role": "customer",
        })

        # Login
        resp = self.client.post("/api/v1/auth/login/", json={
            "email": self.email,
            "password": self.password,
        })
        if resp.status_code == 200:
            self.token = resp.json()["access"]

    @property
    def auth_headers(self):
        if self.token:
            return {"Authorization": f"Bearer {self.token}"}
        return {}

    def _ensure_survey(self):
        """Fetch an active survey and its fields for submission."""
        if self.survey_id and self.survey_fields:
            return True
        resp = self.client.get(
            "/api/v1/surveys/?status=published",
            headers=self.auth_headers,
            name="/api/v1/surveys/?status=published",
        )
        if resp.status_code == 200:
            results = resp.json().get("results", [])
            if results:
                self.survey_id = results[0]["id"]
                detail = self.client.get(
                    f"/api/v1/surveys/{self.survey_id}/",
                    headers=self.auth_headers,
                    name="/api/v1/surveys/[id]/",
                )
                if detail.status_code == 200:
                    data = detail.json()
                    self.survey_fields = []
                    for section in data.get("sections", []):
                        for field in section.get("fields", []):
                            self.survey_fields.append(field)
                return bool(self.survey_fields)
        return False

    def _generate_answer(self, field):
        """Generate a plausible answer for a given field definition."""
        ft = field["field_type"]
        if ft == "text" or ft == "textarea":
            return "Load test answer"
        elif ft == "number":
            return random.randint(1, 100)
        elif ft == "email":
            return "loadtest@example.com"
        elif ft == "date":
            return "2026-01-15"
        elif ft in ("dropdown", "radio"):
            options = field.get("options", [])
            return random.choice(options) if options else "option1"
        elif ft == "checkbox":
            options = field.get("options", [])
            if options:
                return random.sample(options, k=min(2, len(options)))
            return []
        return "test"

    @task(1)
    def list_surveys(self):
        self.client.get("/api/v1/surveys/", headers=self.auth_headers)

    @task(3)
    def get_survey_detail(self):
        resp = self.client.get("/api/v1/surveys/", headers=self.auth_headers)
        if resp.status_code == 200:
            results = resp.json().get("results", [])
            if results:
                survey_id = results[0]["id"]
                self.client.get(
                    f"/api/v1/surveys/{survey_id}/",
                    headers=self.auth_headers,
                    name="/api/v1/surveys/[id]/",
                )

    @task(2)
    def submit_response(self):
        if not self._ensure_survey():
            return
        answers = []
        for field in self.survey_fields:
            if field.get("required", False) or random.random() > 0.3:
                answers.append({
                    "field_id": field["id"],
                    "value": self._generate_answer(field),
                })
        self.client.post(
            f"/api/v1/surveys/{self.survey_id}/submit/",
            json={"answers": answers},
            headers=self.auth_headers,
            name="/api/v1/surveys/[id]/submit/",
        )
