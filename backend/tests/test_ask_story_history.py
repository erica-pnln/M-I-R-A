import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app import main


class FakeQuery:
    def __init__(self, table, database):
        self.table_name = table
        self.database = database
        self.filters = []
        self.inserted = None

    def select(self, *_columns):
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def maybe_single(self):
        return self

    def insert(self, rows):
        self.inserted = rows
        self.database.inserts.append((self.table_name, rows))
        return self

    def execute(self):
        if self.table_name == "conversations":
            return SimpleNamespace(data={"id": "story-conversation"})
        return SimpleNamespace(data=[])


class FakeDatabase:
    def __init__(self):
        self.queries = []
        self.inserts = []

    def table(self, name):
        query = FakeQuery(name, self)
        self.queries.append(query)
        return query


class AskStoryHistoryTests(unittest.TestCase):
    def test_story_turn_requires_and_filters_story_conversations(self):
        database = FakeDatabase()
        article = {"id": "article-1", "title": "Selected article"}

        with patch.object(main, "sb", database):
            conversation_id = main._save_story_turn(
                "user-1",
                "story-conversation",
                article,
                "Question",
                "Answer",
            )

        self.assertEqual(conversation_id, "story-conversation")
        self.assertIn(("kind", "story"), database.queries[0].filters)
        self.assertIn(("user_id", "user-1"), database.queries[0].filters)
        self.assertEqual(database.inserts[0][0], "messages")
        self.assertEqual(len(database.inserts[0][1]), 2)

    def test_anonymous_story_turn_is_not_persisted(self):
        with patch.object(main, "sb") as database:
            result = main._save_story_turn(
                None,
                None,
                {"id": "article-1", "title": "Selected article"},
                "Question",
                "Answer",
            )

        self.assertIsNone(result)
        database.table.assert_not_called()


if __name__ == "__main__":
    unittest.main()
