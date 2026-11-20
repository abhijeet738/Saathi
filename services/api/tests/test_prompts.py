
"""Every prompt file in app/prompts must be registered here, well-formed, and safe to render.

When you add a prompt, add a line to EXPECTED. The test fails until you do, so a prompt
with a typo in a placeholder or a stray curly brace is caught before it reaches production.
"""

import re
import string

import pytest

from app.core.llm import PROMPT_DIR, load_prompt

# prompt name -> the placeholders it uses
EXPECTED = {
    "brief_compose": set(),
    "doc_summary": set(),
    "transcribe": set(),
    "image_analyze": {"caption"},
    "inbox_classify": set(),
    "money_parse": set(),
}

# Prompts that receive text written by someone else. They must tell the model to treat it as data.
HANDLES_UNTRUSTED_TEXT = {"image_analyze"}

# Phrases that count as that warning.
DATA_NOT_INSTRUCTIONS = ("never follow instructions", "not instructions", "never obey")


def placeholders(text: str) -> set[str]:
    # string.Formatter().parse raises ValueError on a stray { or }, which is exactly what we want to catch.
    return {field for _, field, _, _ in string.Formatter().parse(text) if field}


def prompt_files() -> set[str]:
    return {p.stem for p in PROMPT_DIR.glob("*.md")}


def test_every_prompt_file_is_registered():
    unregistered = prompt_files() - set(EXPECTED)
    assert not unregistered, f"add these prompts to EXPECTED in tests/test_prompts.py: {sorted(unregistered)}"


def test_every_registered_prompt_has_a_file():
    missing = set(EXPECTED) - prompt_files()
    assert not missing, f"prompt files missing from app/prompts/: {sorted(missing)}"


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_placeholders_match_what_the_code_passes(name):
    text = (PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8")
    assert placeholders(text) == EXPECTED[name]


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_prompt_renders_without_errors(name):
    values = {field: f"<{field}>" for field in EXPECTED[name]}
    rendered = load_prompt(name, **values)
    assert rendered.strip()
    for field in EXPECTED[name]:
        assert f"<{field}>" in rendered  # the value really was inserted


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_placeholder_values_are_not_parsed_again(name):
    # A user caption, email or note containing { } must never break rendering.
    values = {field: "text with {braces} and a lone } too" for field in EXPECTED[name]}
    rendered = load_prompt(name, **values)
    if values:
        assert "{braces}" in rendered


@pytest.mark.parametrize("name", sorted(HANDLES_UNTRUSTED_TEXT))
def test_prompts_with_untrusted_text_warn_the_model(name):
    text = (PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8").lower()
    assert any(phrase in text for phrase in DATA_NOT_INSTRUCTIONS)


def test_prompt_names_are_accepted_by_the_loader():
    # load_prompt only accepts lowercase letters, digits and underscores in a name.
    for name in prompt_files():
        assert re.fullmatch(r"[a-z0-9_]+", name), f"rename app/prompts/{name}.md"
