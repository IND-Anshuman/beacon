"""LangChain: a retrieval-augmented answer chain with beacon's template, parser and callback.

Runs offline with LangChain's fake chat model. Swap in ChatOpenAI/ChatAnthropic for real use.
Requires: pip install "llm-beacon[langchain]"
"""

from __future__ import annotations

from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.runnables import RunnableLambda
from pydantic import BaseModel

from beacon.integrations.langchain import BeaconCallbackHandler, BeaconJsonOutputParser, BeaconPromptTemplate


class Answer(BaseModel):
    answer: str
    sources: list[str]
    confidence: float


DOCS = {
    "refunds.md": "Refunds are available within 30 days of purchase.",
    "shipping.md": "Orders ship within 2 business days.",
}


def retrieve(inputs: dict) -> dict:
    # Deterministic "retriever": keyword match, documents in sorted order.
    words = set(inputs["question"].lower().split())
    hits = sorted(name for name, text in DOCS.items() if words & set(text.lower().split()))
    context = "\n".join(f"[{name}] {DOCS[name]}" for name in hits)
    return {"question": inputs["question"], "context": context}


parser = BeaconJsonOutputParser(pydantic_object=Answer)
# Format instructions contain JSON braces, so pass them as a partial variable
# and insert them with {name!raw} (trusted text, not escaped).
prompt = BeaconPromptTemplate(
    template=(
        "Answer using only the context.\n<context>{context}</context>\n"
        "<question>{question}</question>\n\n{format_instructions!raw}"
    ),
    partial_variables={"format_instructions": parser.get_format_instructions()},
)
llm = FakeListChatModel(
    responses=['Here you go:\n```json\n{"answer": "Within 30 days.", "sources": ["refunds.md"], "confidence": 0.9}\n```']
)
handler = BeaconCallbackHandler(schema=Answer.model_json_schema())

chain = RunnableLambda(retrieve) | prompt | llm | parser
answer = chain.invoke({"question": "How many days do I have for refunds?"}, config={"callbacks": [handler]})
print(answer)
print(handler.records[0])
