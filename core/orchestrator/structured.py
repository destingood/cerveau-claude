"""JSON answers of the models, validated by Pydantic, with one repair turn.

The error sent back to the model names the faulty fields and the rule they break, never the
values themselves: an invalid value may come from a page (R5) or hold a pseudonym.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from pydantic import BaseModel, ValidationError

Invoke = Callable[[Sequence[BaseMessage]], Awaitable[AIMessage]]

MAX_ERRORS = 3
REPAIR = (
    "Ta réponse n'est pas un objet JSON valide pour le format demandé ({error}). "
    "Réponds de nouveau uniquement par l'objet JSON corrigé, sans texte autour."
)


class StructuredOutputError(Exception):
    def __init__(self, what: str, error: str) -> None:
        self.what = what
        self.error = error
        super().__init__(f"{what} : sortie JSON invalide après réparation ({error})")


def message_text(message: BaseMessage) -> str:
    """The text blocks of a message, joined; tool calls and thinking blocks are left out."""
    content = message.content
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text", "")))
    return "".join(parts)


def parse_json[T: BaseModel](text: str, model: type[T]) -> T:
    """Validates the outermost ``{…}`` of ``text`` (models sometimes add a sentence or a fence)."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("aucun objet JSON")
    return model.model_validate_json(text[start : end + 1])


def short_error(exc: ValueError) -> str:
    if isinstance(exc, ValidationError):
        items = [
            f"{'.'.join(str(part) for part in error['loc']) or 'objet'} : {error['msg']}"
            for error in exc.errors(include_url=False, include_input=False)[:MAX_ERRORS]
        ]
        return " ; ".join(items)
    return str(exc)[:200]


async def ask_json[T: BaseModel](
    invoke: Invoke, messages: Sequence[BaseMessage], model: type[T], *, what: str
) -> T:
    """Asks for ``model`` as JSON; one repair turn, then ``StructuredOutputError``."""
    reply = await invoke(messages)
    try:
        return parse_json(message_text(reply), model)
    except ValueError as exc:
        error = short_error(exc)
    repair = [*messages, reply, HumanMessage(REPAIR.format(error=error))]
    second = await invoke(repair)
    try:
        return parse_json(message_text(second), model)
    except ValueError as exc:
        raise StructuredOutputError(what, short_error(exc)) from None
