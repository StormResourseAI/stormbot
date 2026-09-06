"""The validator is hand-rolled, so it needs to earn that decision."""

from __future__ import annotations

import unittest

from stormbot.assurance.schema import UnsupportedSchemaKeyword, validate

PERSON_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["id", "tier"],
    "properties": {
        "id": {"type": "string", "pattern": "^[a-z]+$", "minLength": 2},
        "tier": {"type": "string", "enum": ["low", "high"]},
        "count": {"type": "integer", "minimum": 0},
        "reviewed": {"type": "string", "format": "date"},
        "tags": {"type": "array", "minItems": 1, "uniqueItems": True, "items": {"type": "string"}},
    },
}


class ValidationTests(unittest.TestCase):
    def test_a_valid_document_produces_no_errors(self):
        document = {"id": "governor", "tier": "high", "count": 3, "tags": ["safety"]}

        self.assertEqual(validate(document, PERSON_SCHEMA), [])

    def test_every_error_is_collected_rather_than_only_the_first(self):
        """One CI cycle per typo is a bad trade for the person fixing them."""
        document = {"id": "X", "tier": "medium", "count": -1}

        messages = [str(error) for error in validate(document, PERSON_SCHEMA)]

        self.assertEqual(len(messages), 4)
        self.assertTrue(any("minLength" in m for m in messages))
        self.assertTrue(any("pattern" in m for m in messages))
        self.assertTrue(any("one of" in m for m in messages))
        self.assertTrue(any("minimum" in m for m in messages))

    def test_missing_required_properties_are_reported_by_name(self):
        errors = [str(error) for error in validate({"count": 1}, PERSON_SCHEMA)]

        self.assertTrue(any("'id'" in message for message in errors))
        self.assertTrue(any("'tier'" in message for message in errors))

    def test_unexpected_properties_are_rejected(self):
        errors = validate({"id": "gov", "tier": "low", "surprise": 1}, PERSON_SCHEMA)

        self.assertIn("unexpected property 'surprise'", str(errors[0]))

    def test_errors_are_located_by_path(self):
        errors = validate({"id": "gov", "tier": "low", "tags": ["ok", 7]}, PERSON_SCHEMA)

        self.assertEqual(errors[0].path, ".tags[1]")

    def test_booleans_are_not_accepted_as_integers(self):
        errors = validate({"id": "gov", "tier": "low", "count": True}, PERSON_SCHEMA)

        self.assertIn("expected type integer", str(errors[0]))

    def test_date_format_is_checked(self):
        errors = validate({"id": "gov", "tier": "low", "reviewed": "2026-13-45"}, PERSON_SCHEMA)

        self.assertIn("not a valid date", str(errors[0]))

    def test_duplicate_array_items_are_rejected(self):
        errors = validate({"id": "gov", "tier": "low", "tags": ["a", "a"]}, PERSON_SCHEMA)

        self.assertIn("duplicate", str(errors[0]))

    def test_local_refs_resolve(self):
        schema = {
            "type": "object",
            "properties": {"item": {"$ref": "#/$defs/leaf"}},
            "$defs": {"leaf": {"type": "string", "minLength": 3}},
        }

        self.assertEqual(validate({"item": "abc"}, schema), [])
        self.assertIn("minLength", str(validate({"item": "ab"}, schema)[0]))

    def test_union_types_are_supported_for_nullable_fields(self):
        schema = {"type": "object", "properties": {"base": {"type": ["string", "null"]}}}

        self.assertEqual(validate({"base": None}, schema), [])
        self.assertEqual(validate({"base": "abc"}, schema), [])
        self.assertTrue(validate({"base": 7}, schema))


class UnsupportedKeywordTests(unittest.TestCase):
    def test_an_unimplemented_keyword_raises_instead_of_being_ignored(self):
        """Silently ignoring `anyOf` would validate documents against nothing."""
        schema = {"type": "object", "properties": {"x": {"anyOf": [{"type": "string"}]}}}

        with self.assertRaises(UnsupportedSchemaKeyword) as raised:
            validate({"x": "value"}, schema)

        self.assertIn("anyOf", str(raised.exception))

    def test_remote_refs_are_refused(self):
        schema = {"type": "object", "properties": {"x": {"$ref": "https://example.com/s.json"}}}

        with self.assertRaises(UnsupportedSchemaKeyword):
            validate({"x": "value"}, schema)


if __name__ == "__main__":
    unittest.main()
