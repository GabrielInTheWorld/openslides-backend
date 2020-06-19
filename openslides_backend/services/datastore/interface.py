from enum import Enum
from typing import Any, Dict, List, Sequence, Tuple

from mypy_extensions import TypedDict
from typing_extensions import Protocol

from ...shared.filters import Filter
from ...shared.patterns import Collection, FullQualifiedId
from .commands import GetManyRequest

PartialModel = Dict[str, Any]
Found = TypedDict("Found", {"exists": bool})
Count = TypedDict("Count", {"count": int})
Aggregate = Dict[str, Any]  # TODO: This interface seams to be wrong.


class DeletedModelsBehaviour(Enum):
    NO_DELETED = 1
    ONLY_DELETED = 2
    ALL_MODELS = 3


class Datastore(Protocol):
    """
    Datastore defines the interface to the datastore.
    """

    # The key of this dictionary is a stringified FullQualifiedId or FullQualifiedField
    locked_fields: Dict[str, int]

    def get(
        self,
        fqid: FullQualifiedId,
        mapped_fields: List[str] = None,
        position: int = None,
        get_deleted_models: int = None,
        lock_result: bool = False,
    ) -> PartialModel:
        ...

    def get_many(
        self,
        get_many_requests: List[GetManyRequest],
        mapped_fields: List[str] = None,
        position: int = None,
        get_deleted_models: int = None,
        lock_result: bool = False,
    ) -> Dict[Collection, Dict[int, PartialModel]]:
        ...

    def get_all(
        self,
        collection: Collection,
        mapped_fields: List[str] = None,
        get_deleted_models: int = None,
        lock_result: bool = False,
    ) -> List[PartialModel]:
        ...

    def filter(
        self,
        collection: Collection,
        filter: Filter,
        meeting_id: int = None,
        mapped_fields: List[str] = None,
        lock_result: bool = False,
    ) -> List[PartialModel]:
        ...

    def exists(
        self, collection: Collection, filter: Filter, lock_result: bool = False
    ) -> Found:
        ...

    def count(
        self, collection: Collection, filter: Filter, lock_result: bool = False
    ) -> Count:
        ...

    def min(
        self, collection: Collection, filter: Filter, field: str, type: str = None
    ) -> Aggregate:
        ...

    def max(
        self, collection: Collection, filter: Filter, field: str, type: str = None
    ) -> Aggregate:
        ...

    def reserve_ids(self, collection: Collection, amount: int) -> Sequence[int]:
        ...

    def reserve_id(self, collection: Collection) -> int:
        ...


class Engine(Protocol):
    """
    Engine defines the interface to the engine used by the datastore. This will
    be the HTTPEngine per default
    """

    def retrieve(self, endpoint: str, data: str) -> Tuple[bytes, int]:
        ...
