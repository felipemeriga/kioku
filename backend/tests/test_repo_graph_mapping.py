import unittest

from services.repo_graph.mapping import (
    infer_kind,
    map_edge,
    map_node,
    parse_line,
)


class TestParseLine(unittest.TestCase):
    def test_variants(self):
        self.assertEqual(parse_line("L12"), 12)
        self.assertEqual(parse_line("L12-L20"), 12)
        self.assertEqual(parse_line(42), 42)
        self.assertIsNone(parse_line(None))
        self.assertIsNone(parse_line("no-digits"))


class TestInferKind(unittest.TestCase):
    def test_file_node(self):
        self.assertEqual(
            infer_kind({"label": "audio.rs", "source_file": "player/audio.rs"}),
            "file",
        )

    def test_method_and_function_and_symbol(self):
        self.assertEqual(infer_kind({"label": ".has_audio()"}), "method")
        self.assertEqual(infer_kind({"label": "build_graph()"}), "function")
        self.assertEqual(infer_kind({"label": "Player"}), "symbol")

    def test_empty(self):
        self.assertIsNone(infer_kind({"label": ""}))


class TestMapNode(unittest.TestCase):
    def test_maps_fields(self):
        row = map_node(
            {
                "id": "audio_player_has_audio",
                "label": ".has_audio()",
                "source_file": "player/audio.rs",
                "source_location": "L12",
                "_origin": "ast",
            },
            folder_id="f1",
            user_id="u1",
        )
        self.assertEqual(row["node_id"], "audio_player_has_audio")
        self.assertEqual(row["symbol"], ".has_audio()")
        self.assertEqual(row["kind"], "method")
        self.assertEqual(row["file"], "player/audio.rs")
        self.assertEqual(row["start_line"], 12)
        self.assertEqual(row["origin"], "ast")
        self.assertEqual(row["folder_id"], "f1")

    def test_requires_id_and_file(self):
        self.assertIsNone(map_node({"label": "x"}, folder_id="f", user_id="u"))
        self.assertIsNone(
            map_node({"id": "x"}, folder_id="f", user_id="u")  # no source_file
        )


class TestMapEdge(unittest.TestCase):
    def test_maps_fields_and_owner(self):
        row = map_edge(
            {
                "source": "clip_mode",
                "target": "error_MyError",
                "relation": "references",
                "confidence": "EXTRACTED",
                "source_file": "player/clip_mode.rs",
                "source_location": "L88",
            },
            folder_id="f1",
            user_id="u1",
        )
        self.assertEqual(row["src_node_id"], "clip_mode")
        self.assertEqual(row["dst_node_id"], "error_MyError")
        self.assertEqual(row["relation"], "references")
        self.assertEqual(row["confidence"], "EXTRACTED")
        # edge is owned by the file the reference appears in
        self.assertEqual(row["ref_file"], "player/clip_mode.rs")
        self.assertEqual(row["ref_line"], 88)

    def test_requires_endpoints(self):
        self.assertIsNone(
            map_edge({"source": "a", "relation": "calls"}, folder_id="f", user_id="u")
        )
        self.assertIsNone(map_edge({"source": "a", "target": "b"}, folder_id="f", user_id="u"))


if __name__ == "__main__":
    unittest.main()
