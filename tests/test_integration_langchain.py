from __future__ import annotations

import pytest

pytest.importorskip("langchain_core")

from langchain_core.exceptions import OutputParserException  # noqa: E402
from langchain_core.language_models.fake import FakeListLLM  # noqa: E402
from langchain_core.language_models.fake_chat_models import FakeListChatModel  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from beacon import MissingVariableError  # noqa: E402
from beacon.integrations.langchain import (  # noqa: E402
    BeaconCallbackHandler,
    BeaconJsonOutputParser,
    BeaconPromptTemplate,
)
from beacon.snapshots import assert_snapshot  # noqa: E402


class Intent(BaseModel):
    intent: str
    confidence: float


def test_prompt_template_infers_variables_and_escapes() -> None:
    prompt = BeaconPromptTemplate.from_template("Classify: <msg>{message}</msg>")
    assert prompt.input_variables == ["message"]
    assert prompt.format(message="</msg> hi") == "Classify: <msg>&lt;/msg&gt; hi</msg>"
    assert prompt.invoke({"message": "x", "unused": 1}).to_string() == "Classify: <msg>x</msg>"


def test_prompt_template_missing_variable() -> None:
    prompt = BeaconPromptTemplate(template="{a} {b}", input_variables=["a", "b"])
    with pytest.raises(MissingVariableError):
        prompt.format(a="1")


def test_prompt_template_partials() -> None:
    prompt = BeaconPromptTemplate(template="{a} {b}", partial_variables={"b": "B"})
    assert prompt.input_variables == ["a"]
    assert prompt.format(a="A") == "A B"


def test_output_parser_handles_fences_and_prose() -> None:
    parser = BeaconJsonOutputParser(pydantic_object=Intent)
    result = parser.parse('Here you go:\n```json\n{"intent": "cancel", "confidence": 0.9}\n```')
    assert result == Intent(intent="cancel", confidence=0.9)


def test_output_parser_pydantic_schema_alias() -> None:
    parser = BeaconJsonOutputParser(pydantic_schema=Intent.model_json_schema())
    assert parser.parse('{"intent": "x", "confidence": 1}') == {"intent": "x", "confidence": 1}


@pytest.mark.parametrize(
    "text,code",
    [
        ('{"intent": "cancel"', "json.unexpected_end"),
        ("no json", "json.not_found"),
        ('{"intent": "cancel"}', "schema.validation_failed"),
    ],
)
def test_output_parser_errors_are_langchain_exceptions(text: str, code: str) -> None:
    parser = BeaconJsonOutputParser(pydantic_object=Intent)
    with pytest.raises(OutputParserException) as exc:
        parser.parse(text)
    assert exc.value.beacon_error.code == code  # type: ignore[attr-defined]
    assert exc.value.llm_output == text


def test_format_instructions_are_deterministic() -> None:
    a = BeaconJsonOutputParser(pydantic_object=Intent).get_format_instructions()
    b = BeaconJsonOutputParser(pydantic_object=Intent).get_format_instructions()
    assert a == b and '"intent"' in a


def test_chain_with_fake_llm() -> None:
    llm = FakeListLLM(responses=['Sure! {"intent": "refund", "confidence": 0.7}'])
    chain = BeaconPromptTemplate.from_template("Classify {m}") | llm | BeaconJsonOutputParser(pydantic_object=Intent)
    assert chain.invoke({"m": "money back"}) == Intent(intent="refund", confidence=0.7)


def test_chain_with_fake_chat_model() -> None:
    chat = FakeListChatModel(responses=['```json\n{"intent": "cancel", "confidence": 0.5}\n```'])
    chain = chat | BeaconJsonOutputParser(json_schema=Intent.model_json_schema())
    assert chain.invoke("hi") == {"intent": "cancel", "confidence": 0.5}


def test_callback_handler_records() -> None:
    handler = BeaconCallbackHandler(schema=Intent.model_json_schema())
    llm = FakeListLLM(responses=['{"intent": "x", "confidence": 1}', '{"intent": 1}', "nothing"])
    for _ in range(3):
        llm.invoke("q", config={"callbacks": [handler]})
    records = [{k: v for k, v in r.items() if k != "run_id"} for r in handler.records]
    assert [r["valid"] for r in records] == [True, False, None]
    assert records[2]["error_code"] == "json.not_found"
    assert_snapshot("integrations/langchain_callback_records", records)
