import unittest

from check_agent_speed import validate_agent


class AgentSpeedCheckTests(unittest.TestCase):
    def response(self):
        return {"symbol": "TEST", "answer": "Company evidence is available.",
                "toolsUsed": ["company_fundamentals"],
                "timings": {"evidenceMs": 10, "totalMs": 20}}

    def test_profile_requires_correct_company_and_new_fast_path(self):
        data = self.response()
        validate_agent(data, "TEST")
        data["toolsUsed"].append("technical_prediction")
        with self.assertRaises(ValueError):
            validate_agent(data, "TEST")
        with self.assertRaises(ValueError):
            validate_agent(self.response(), "OTHER")

    def test_missing_new_build_timing_fields_fails(self):
        data = self.response()
        data.pop("timings")
        with self.assertRaises(ValueError):
            validate_agent(data, "TEST")

    def test_report_requires_only_report_tool_and_valid_citation(self):
        data = self.response()
        data.update({"toolsUsed": ["company_document_rag"], "answer": "Business evidence [S1 p.4]",
                     "citations": [{"citation": "S1", "page": 4}]})
        validate_agent(data, "TEST", documents=True)
        data["answer"] += " [S99 p.2]"
        with self.assertRaises(ValueError):
            validate_agent(data, "TEST", documents=True)

    def test_missing_report_must_not_accept_generated_answer(self):
        data = self.response()
        data.update({"toolsUsed": ["company_document_rag"], "citations": [], "llmAnswerAccepted": False})
        validate_agent(data, "TEST", documents=True)
        data["llmAnswerAccepted"] = True
        with self.assertRaises(ValueError):
            validate_agent(data, "TEST", documents=True)


if __name__ == "__main__":
    unittest.main()
