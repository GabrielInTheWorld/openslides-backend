from tests.system.action.base import BaseActionTestCase


class TagActionTest(BaseActionTestCase):
    def test_create(self) -> None:
        self.create_model("meeting/577", {"name": "name_YBEqrXqz"})
        response = self.request(
            "tag.create", {"name": "test_Xcdfgee", "meeting_id": 577}
        )
        self.assert_status_code(response, 200)
        model = self.get_model("tag/1")
        self.assertEqual(model.get("name"), "test_Xcdfgee")
        self.assertEqual(model.get("meeting_id"), 577)

    def test_create_empty_data(self) -> None:
        response = self.request("tag.create", {})
        self.assert_status_code(response, 400)
        self.assertIn(
            "data must contain ['name', 'meeting_id'] properties",
            response.json["message"],
        )

    def test_create_wrong_field(self) -> None:
        self.create_model("meeting/577", {"name": "name_YBEqrXqz"})
        response = self.request(
            "tag.create",
            {
                "name": "test_Xcdfgee",
                "meeting_id": 577,
                "wrong_field": "text_AefohteiF8",
            },
        )
        self.assert_status_code(response, 400)
        self.assertIn(
            "data must not contain {'wrong_field'} properties",
            response.json["message"],
        )
