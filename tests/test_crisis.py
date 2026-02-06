"""Tests for crisis keyword detection — a safety-critical feature."""


# Extract the crisis check logic from main.py so it can be tested independently.
# The keywords and matching logic are inline in the main loop, so we replicate them here.
CRISIS_KEYWORDS = ["suicide", "kill myself", "want to die", "end it all", "self harm"]


def is_crisis_input(user_input: str) -> bool:
    """Replicates the crisis detection logic from main.py."""
    return any(k in user_input.lower() for k in CRISIS_KEYWORDS)


class TestCrisisDetection:
    """Verify that crisis keywords are reliably detected."""

    def test_exact_keyword_match(self):
        assert is_crisis_input("suicide") is True
        assert is_crisis_input("kill myself") is True
        assert is_crisis_input("want to die") is True
        assert is_crisis_input("end it all") is True
        assert is_crisis_input("self harm") is True

    def test_keyword_in_sentence(self):
        assert is_crisis_input("I'm thinking about suicide") is True
        assert is_crisis_input("I want to kill myself today") is True
        assert is_crisis_input("I just want to die") is True
        assert is_crisis_input("I want to end it all right now") is True
        assert is_crisis_input("thinking about self harm") is True

    def test_case_insensitive(self):
        assert is_crisis_input("SUICIDE") is True
        assert is_crisis_input("Kill Myself") is True
        assert is_crisis_input("WANT TO DIE") is True
        assert is_crisis_input("Self Harm") is True

    def test_non_crisis_input_not_flagged(self):
        assert is_crisis_input("I'm stuck on this task") is False
        assert is_crisis_input("I feel rejected") is False
        assert is_crisis_input("I'm worried about failing") is False
        assert is_crisis_input("This task is killing me") is False  # "killing" != "kill myself"
        assert is_crisis_input("I'm dying of boredom") is False  # "dying" != "want to die"
        assert is_crisis_input("") is False

    def test_empty_and_whitespace(self):
        assert is_crisis_input("") is False
        assert is_crisis_input("   ") is False

    def test_keywords_match_main_py(self):
        """Verify our test keywords match what main.py actually uses."""
        import ast
        import os

        main_path = os.path.join(os.path.dirname(__file__), "..", "adhd_os", "main.py")
        with open(main_path) as f:
            tree = ast.parse(f.read())

        # Find the CRISIS_KEYWORDS assignment
        found_keywords = None
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "CRISIS_KEYWORDS":
                        found_keywords = ast.literal_eval(node.value)

        assert found_keywords is not None, "Could not find CRISIS_KEYWORDS in main.py"
        assert found_keywords == CRISIS_KEYWORDS, (
            f"Test keywords {CRISIS_KEYWORDS} don't match main.py keywords {found_keywords}"
        )
