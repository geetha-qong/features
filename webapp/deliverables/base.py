"""Abstract base for deliverable generators.

Subclasses must define deliverable_type and file_format as ClassVars, and
implement generate(canonical, template) -> bytes.
"""

from abc import ABC, abstractmethod
from typing import ClassVar

from webapp.deliverables.canonical import JobCanonical
from webapp.deliverables.template import TemplateConfig


class Generator(ABC):
    deliverable_type: ClassVar[str]
    file_format: ClassVar[str]

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if "deliverable_type" not in cls.__dict__:
            raise TypeError(
                f"{cls.__name__} must define class attribute 'deliverable_type'"
            )
        if "file_format" not in cls.__dict__:
            raise TypeError(
                f"{cls.__name__} must define class attribute 'file_format'"
            )

    @abstractmethod
    def generate(self, canonical: JobCanonical, template: TemplateConfig) -> bytes:
        """Render the deliverable as raw bytes (file content)."""
