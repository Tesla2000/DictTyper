from __future__ import annotations

import hashlib
import json
import typing
from collections.abc import Container
from collections.abc import Sequence
from types import ModuleType
from typing import Any
from typing import Callable
from typing import Literal
from typing import TypeVar
from typing import Union

import libcst
import typing_extensions
from libcst import Annotation
from libcst import BaseCompoundStatement
from libcst import CSTNode
from libcst import Ellipsis as LibcstEllipsis
from libcst import FunctionDef
from libcst import Import
from libcst import ImportAlias
from libcst import ImportFrom
from libcst import Module
from libcst import Name
from libcst import SimpleStatementLine
from libcst import Subscript
from litellm import completion
from more_itertools import last
from pydantic import create_model

from ..config import Config
from ..consts.dict_typer.transform.dict_namer import HARD_CODED_KEYS_TRUE
from ..consts.dict_typer.transform.dict_namer import RETURN_DICT_EMPTY
from ._transformer import Transformer

T = TypeVar("T", bound=CSTNode)

types = (int, float, str, bool, list, dict, set, tuple, Callable, Any)

type_hints = Literal[*(type.__name__ for type in types)]
imported_types = tuple(type for type in types if type.__module__ != "builtins")


class DictNamer(Transformer):
    def __init__(self, config: Config) -> None:
        super().__init__(config)
        self.modified_returns: dict[FunctionDef, str] = {}
        self.imported_types: set[ModuleType] = set()

    def leave_FunctionDef(
        self, original_node: "FunctionDef", updated_node: "FunctionDef"
    ) -> "FunctionDef":
        if updated_node.returns is None or self.in_cache(updated_node):
            return updated_node
        annotation = updated_node.returns.annotation
        if not (
            isinstance(annotation, Subscript)
            and isinstance(value := annotation.value, Name)
            and value.value == "dict"
            and (
                len(slice := annotation.slice) < 2
                or not isinstance(slice[1].slice.value, LibcstEllipsis)
            )
        ):
            return updated_node
        model = create_model(
            "typed_dict_data",
            typed_dict_name=str,
            typed_dict_keys=list[str],
            typed_dict_type_hints=list[type_hints],
            explanation=str,
        )
        if not json.loads(
            completion(
                "anthropic/claude-3-5-sonnet-20240620",
                messages=[
                    {
                        "role": "user",
                        "content": (
                            HARD_CODED_KEYS_TRUE + Module([original_node]).code
                        ),
                    }
                ],
                temperature=0.0,
                response_format=create_model("CanBeTypedDict", can_be=bool),
            ).choices[0]["message"]["content"]
        )["can_be"]:
            self.save2cache(updated_node)
            return updated_node
        response = json.loads(
            completion(
                "anthropic/claude-3-5-sonnet-20240620",
                messages=[
                    {
                        "role": "user",
                        "content": (
                            RETURN_DICT_EMPTY + Module([original_node]).code
                        ),
                    }
                ],
                temperature=0.0,
                response_format=model,
            ).choices[0]["message"]["content"]
        )
        typed_dict_name = "_" + response["typed_dict_name"].lstrip("_")
        updated_node = updated_node.with_changes(
            returns=Annotation(annotation=Name(typed_dict_name))
        )
        typed_dict_keys = response["typed_dict_keys"]
        typed_dict_type_hints = response["typed_dict_type_hints"]
        assert len(typed_dict_keys) == len(typed_dict_type_hints)
        self.imported_types.update(
            filter(
                imported_types.__contains__,
                (
                    next(
                        imported_type
                        for imported_type in types
                        if imported_type.__name__ == hint
                    )
                    for hint in typed_dict_type_hints
                ),
            )
        )
        self.modified_returns[updated_node] = (
            f"class {typed_dict_name}({typing.TypedDict.__name__}):"
            + "".join(
                map(
                    "\n\t{}: {}".format, typed_dict_keys, typed_dict_type_hints
                )
            )
        )
        return updated_node

    def leave_Module(
        self, original_node: "Module", updated_node: "Module"
    ) -> "Module":
        body = list(updated_node.body)
        if self.modified_returns and not self._is_import_present(
            body,
            (
                typing.__name__,
                typing_extensions.__name__,
            ),
            typing.TypedDict.__name__,
        ):
            body.insert(
                0,
                SimpleStatementLine(
                    [
                        ImportFrom(
                            Name(typing.__name__),
                            [ImportAlias(Name(typing.TypedDict.__name__))],
                        )
                    ]
                ),
            )
        for type_ in self.imported_types:
            if self._is_import_present(
                body, (type_.__module__,), type_.__name__
            ):
                continue
            body.insert(
                0,
                SimpleStatementLine(
                    [
                        ImportFrom(
                            Name(type_.__module__),
                            [ImportAlias(Name(type_.__name__))],
                        )
                    ]
                ),
            )

        updated_node = updated_node.with_changes(body=tuple(body))
        return self._add_typed_dict(original_node, updated_node)

    @staticmethod
    def _is_import_present(
        body: Sequence[Union[SimpleStatementLine, BaseCompoundStatement]],
        module_names: Container[str],
        imported_elem: str,
    ) -> bool:

        def _is_specific_import(
            elem: Union[SimpleStatementLine, BaseCompoundStatement],
        ) -> bool:
            if not isinstance(elem, SimpleStatementLine):
                return False
            import_ = elem.body[0]
            if not isinstance(import_, ImportFrom):
                return False
            return import_.module.value in module_names and any(
                alias.name.value == imported_elem for alias in import_.names
            )

        return any(
            map(
                _is_specific_import,
                body,
            )
        )

    def _add_typed_dict(self, _: T, updated_node: T) -> T:
        if self.modified_returns:
            body = list(updated_node.body)
            for func in filter(
                dict(self.modified_returns).get, updated_node.body
            ):
                body.insert(
                    body.index(func),
                    libcst.parse_statement(self.modified_returns.pop(func)),
                )
            import_index = (
                body.index(
                    last(
                        filter(
                            lambda elem: isinstance(elem, SimpleStatementLine)
                            and isinstance(elem.body[0], (ImportFrom, Import)),
                            body,
                        )
                    )
                )
                + 1
            )
            for value in self.modified_returns.values():
                body.insert(import_index, libcst.parse_statement(value))
            return updated_node.with_changes(body=tuple(body))
        return updated_node

    def save2cache(self, function: FunctionDef) -> None:
        cache = self._get_cache()
        cache[self._get_hash(function)] = True
        self.config.dict_typer_cache.write_text(json.dumps(cache, indent=2))

    def in_cache(self, function: FunctionDef) -> bool:
        return self._get_hash(function) in self._get_cache()

    def _get_cache(self):
        if not self.config.dict_typer_cache.exists():
            return {}
        return json.loads(self.config.dict_typer_cache.read_bytes())

    @staticmethod
    def _get_hash(function: FunctionDef):
        return hashlib.md5(Module([function]).code.encode()).hexdigest()
