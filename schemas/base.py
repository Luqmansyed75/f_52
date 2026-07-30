"""
schemas/base.py

Defines SchemaBase — the common Pydantic v2 base for all project schemas.

All schemas in this package inherit from SchemaBase. Only schemas that
need to store NumPy arrays (AudioChunk, AudioSegment) override
model_config with arbitrary_types_allowed=True.
"""

from pydantic import BaseModel, ConfigDict


class SchemaBase(BaseModel):
    """
    Common base for all project schemas.

    Configuration
    -------------
    - frozen=False  : fields are mutable by default (can be overridden).
    - populate_by_name=True : allows using field aliases interchangeably
      with Python field names.
    - extra="forbid" : rejects unknown fields, catching typos early.
    """

    model_config = ConfigDict(
        frozen=False,
        populate_by_name=True,
        extra="forbid",
    )
