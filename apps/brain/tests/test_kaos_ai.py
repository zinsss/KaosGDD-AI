import unittest

from kaos_brain.kaos_ai import (
    DisabledKaosAIPlanner,
    KAOSAI_PLAN_SYSTEM_PROMPT,
    KaosAIError,
    parse_kaosai_plan_response,
)


class KaosAITests(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_planner_returns_no_plan(self) -> None:
        planner = DisabledKaosAIPlanner()

        self.assertIsNone(await planner.plan("hello", context={}))

    def test_plan_prompt_forbids_direct_tool_access(self) -> None:
        self.assertIn("cannot call tools", KAOSAI_PLAN_SYSTEM_PROMPT)
        self.assertIn("Do not produce shell", KAOSAI_PLAN_SYSTEM_PROMPT)
        self.assertIn("task.update_due", KAOSAI_PLAN_SYSTEM_PROMPT)
        self.assertIn("memo.search", KAOSAI_PLAN_SYSTEM_PROMPT)

    def test_parse_strict_plan_json(self) -> None:
        plan = parse_kaosai_plan_response(
            '{"intent":"memo.search","scope":"personal","parameters":{"query":"rustdesk"}}'
        )

        self.assertEqual(plan["intent"], "memo.search")
        self.assertEqual(plan["parameters"]["query"], "rustdesk")

    def test_parse_json_fence_from_provider(self) -> None:
        plan = parse_kaosai_plan_response(
            '```json\n{"intent":"today.get","scope":"personal","parameters":{}}\n```'
        )

        self.assertEqual(plan["intent"], "today.get")

    def test_clarify_plan_requires_question(self) -> None:
        plan = parse_kaosai_plan_response(
            '{"intent":"clarify","scope":"personal","parameters":{"question":"어떤 메모인가요?"}}'
        )

        self.assertEqual(plan["intent"], "clarify")
        with self.assertRaisesRegex(KaosAIError, "kaosai_clarify_question_required"):
            parse_kaosai_plan_response('{"intent":"clarify","scope":"personal","parameters":{}}')

    def test_rejects_invalid_or_non_object_json(self) -> None:
        with self.assertRaisesRegex(KaosAIError, "invalid_kaosai_json"):
            parse_kaosai_plan_response("not json")
        with self.assertRaisesRegex(KaosAIError, "kaosai_plan_must_be_object"):
            parse_kaosai_plan_response("[]")
        with self.assertRaisesRegex(KaosAIError, "kaosai_parameters_required"):
            parse_kaosai_plan_response('{"intent":"memo.search","parameters":[]}')


if __name__ == "__main__":
    unittest.main()
