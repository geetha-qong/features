"""Map (deliverable_type, file_format) -> Generator subclass.

Concrete generators register themselves at import time. The router uses
the registry to look up which generator to instantiate for a given request.
"""

from typing import Dict, Tuple, Type

from webapp.deliverables.base import Generator


class UnknownGenerator(KeyError):
    pass


class GeneratorRegistry:
    def __init__(self) -> None:
        self._registry: Dict[Tuple[str, str], Type[Generator]] = {}

    def register(self, generator_cls: Type[Generator]) -> None:
        key = (generator_cls.deliverable_type, generator_cls.file_format)
        if key in self._registry:
            raise ValueError(f"{key[0]}/{key[1]} is already registered")
        self._registry[key] = generator_cls

    def resolve(self, deliverable_type: str, file_format: str) -> Type[Generator]:
        key = (deliverable_type, file_format)
        if key not in self._registry:
            raise UnknownGenerator(f"{deliverable_type}/{file_format}")
        return self._registry[key]


REGISTRY = GeneratorRegistry()
