from collections import defaultdict
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple, Type, cast

import fastjsonschema

from ..models.base import Model, model_registry
from ..models.fields import (
    BaseGenericRelationField,
    BaseRelationField,
    BaseTemplateField,
    BaseTemplateRelationField,
)
from ..services.auth.interface import AuthenticationService
from ..services.datastore.interface import DatastoreService
from ..services.media.interface import MediaService
from ..services.permission.interface import PermissionService
from ..shared.exceptions import (
    ActionException,
    PermissionDenied,
    RequiredFieldsException,
)
from ..shared.interfaces.event import Event, EventType, ListFields
from ..shared.interfaces.logging import LoggingModule
from ..shared.interfaces.services import Services
from ..shared.interfaces.write_request import WriteRequest
from ..shared.patterns import FullQualifiedField, FullQualifiedId
from ..shared.typing import ModelMap
from .relations.relation_manager import RelationManager
from .relations.typing import FieldUpdateElement, ListUpdateElement
from .util.typing import ActionData, ActionResultElement, ActionResults


class SchemaProvider(type):
    """
    Metaclass to provide pre-compiled JSON schemas for faster validation.
    """

    def __new__(cls, name, bases, attrs):  # type: ignore
        schema = attrs.get("schema")
        if schema is not None:
            attrs["schema_validator"] = fastjsonschema.compile(schema)
        return super().__new__(cls, name, bases, attrs)


def native(method: Callable) -> Callable:
    setattr(method, "_native", True)
    return method


class BaseAction:  # pragma: no cover
    """
    Abstract base class for an action.
    """

    services: Services
    permission: PermissionService
    datastore: DatastoreService
    auth: AuthenticationService
    media: MediaService

    name: str
    model: Model
    user_id: int


class Action(BaseAction, metaclass=SchemaProvider):
    """
    Base class for an action.
    """

    schema: Dict
    schema_validator: Callable[[Dict[str, Any]], None]
    is_singular: bool = False
    internal: bool = False
    relation_manager: RelationManager

    modified_relation_fields: Dict[FullQualifiedField, Any]

    write_requests: List[WriteRequest]

    def __init__(
        self,
        services: Services,
        datastore: DatastoreService,
        relation_manager: RelationManager,
        logging: LoggingModule,
        additional_relation_models: ModelMap = {},
    ) -> None:
        self.services = services
        self.permission = services.permission()
        self.auth = services.authentication()
        self.media = services.media()
        self.datastore = datastore
        self.relation_manager = relation_manager
        self.additional_relation_models = additional_relation_models
        self.logging = logging
        self.logger = logging.getLogger(__name__)
        self.modified_relation_fields = {}
        self.write_requests = []

    def perform(
        self, payload: ActionData, user_id: int, internal: bool = False
    ) -> Tuple[Optional[WriteRequest], ActionResults]:
        """
        Entrypoint to perform the action.
        """
        self.user_id = user_id
        self.index = 0
        for element in payload:
            self.validate_payload_element(element)
            self.index += 1
        self.index = -1

        # perform permission not for internal actions
        if not internal:
            self.check_permissions(payload)

        instances = self.get_updated_instances(payload)
        results: ActionResults = []
        for instance in instances:
            # only increment index if the instances which are iterated here are the
            # same as the ones from the payload (meaning get_updated_instances was
            # not overridden)
            if hasattr(self.get_updated_instances, "_native"):
                self.index += 1

            instance = self.base_update_instance(instance)

            relation_updates = self.handle_relation_updates(instance)
            self.write_requests.extend(relation_updates)

            write_request = self.create_write_requests(instance)
            self.write_requests.extend(write_request)

            result = self.create_action_result_element(instance)
            results.append(result)

        final_write_request = self.process_write_requests()
        return (final_write_request, results)

    def check_permissions(self, payload: ActionData) -> None:
        """
        Checks permission by requesting permission service.
        """
        if not self.permission.is_allowed(self.name, self.user_id, list(payload)):
            raise PermissionDenied(
                f"You are not allowed to perform action {self.name}."
            )

    @native
    def get_updated_instances(self, payload: ActionData) -> ActionData:
        """
        By default this does nothing. Override in subclasses to adjust the updates
        to all instances of the payload. You can only update instances of the model
        of this action.
        If needed, this can also be used to do additional validation on the whole
        payload.
        """
        yield from payload

    def validate_payload_element(self, instance: Dict[str, Any]) -> None:
        """
        Validates one instance of the action payload according to schema class attribute.
        """
        try:
            type(self).schema_validator(instance)
        except fastjsonschema.JsonSchemaException as exception:
            raise ActionException(exception.message)

    def base_update_instance(self, instance: Dict[str, Any]) -> Dict[str, Any]:
        """
        Updates one instance of the payload. This can be overridden by custom
        action classes.
        """
        return self.update_instance(instance)

    def update_instance(self, instance: Dict[str, Any]) -> Dict[str, Any]:
        """
        Updates one instance of the payload. This can be overridden by custom
        action classes. Meant to be called inside base_update_instance.
        """
        return instance

    def handle_relation_updates(
        self,
        instance: Dict[str, Any],
    ) -> Iterable[WriteRequest]:
        """
        Creates write request elements (with update events) for all relations.
        """
        relation_updates = self.relation_manager.get_relation_updates(
            self.model, instance, self.name, self.additional_relation_models
        )
        fields: Optional[Dict[str, Any]]
        for fqfield, data in relation_updates.items():
            list_fields: Optional[ListFields] = None
            if data["type"] in ("add", "remove"):
                data = cast(FieldUpdateElement, data)
                fields = {fqfield.field: data["value"]}
                if data["type"] == "add":
                    info_text = f"Object attached to {fqfield.collection}"
                else:
                    info_text = f"Object attachment to {fqfield.collection} reset"
            elif data["type"] == "list_update":
                data = cast(ListUpdateElement, data)
                info_text = "Object updated"
                fields = None
                list_fields_tmp = {}
                if data["add"]:
                    list_fields_tmp["add"] = {fqfield.field: data["add"]}
                if data["remove"]:
                    list_fields_tmp["remove"] = {fqfield.field: data["remove"]}
                list_fields = cast(ListFields, list_fields_tmp)
            yield self.build_write_request(
                EventType.Update,
                FullQualifiedId(fqfield.collection, fqfield.id),
                info_text,
                fields,
                list_fields,
            )

    def build_write_request(
        self,
        type: EventType,
        fqid: FullQualifiedId,
        information: str,
        fields: Optional[Dict[str, Any]] = None,
        list_fields: Optional[ListFields] = None,
    ) -> WriteRequest:
        """
        Helper function to create a WriteRequest.
        """
        event = Event(
            type=type,
            fqid=fqid,
        )
        if fields:
            event["fields"] = fields
        if list_fields:
            event["list_fields"] = list_fields
        return WriteRequest(
            events=[event],
            information={fqid: [information]},
            user_id=self.user_id,
            locked_fields={},
        )

    def create_write_requests(self, instance: Dict[str, Any]) -> Iterable[WriteRequest]:
        """
        Creates write requests for one instance of the current model.
        """
        raise NotImplementedError

    def create_action_result_element(
        self, instance: Dict[str, Any]
    ) -> Optional[ActionResultElement]:
        """
        Create an ActionResponseResultsElement describing the result of this action.
        Defaults to None (to be overridden in subclasses).
        """
        return None

    def process_write_requests(
        self,
    ) -> Optional[WriteRequest]:
        """
        Merge all temporarily created write requests to one single write request which
        is returned by this action.
        """
        # merge all actual write requests
        write_request = merge_write_requests(self.write_requests)
        if write_request:
            # sort events: create - update - delete
            events_by_type: Dict[EventType, List[Event]] = defaultdict(list)
            for event in write_request.events:
                events_by_type[event["type"]].append(event)
            write_request.events = []
            for type in (EventType.Create, EventType.Update, EventType.Delete):
                write_request.events.extend(events_by_type[type])

            # Get locked_fields and reset them in datastore
            write_request.locked_fields = self.datastore.locked_fields
            self.datastore.locked_fields = {}
        return write_request

    def validate_required_fields(self, write_request: WriteRequest) -> None:
        """
        Validate required fields with the events of one WriteRequest.
        Precondition: Events are sorted create/update/delete-events
        Not implemented: required RelationListFields of all types raise a NotImplementedError, if there exist
        one, during getting required_fields from model.
        """
        fdict: Dict[FullQualifiedId, Dict[str, Any]] = {}
        for event in write_request.events:
            if fdict.get(event["fqid"]):
                if event["type"] == EventType.Delete:
                    fdict[event["fqid"]]["type"] = EventType.Delete
                else:
                    fdict[event["fqid"]]["fields"].update(event.get("fields", {}))
            else:
                fdict[event["fqid"]] = {
                    "type": event["type"],
                    "fields": event.get("fields", {}),
                }

        for fqid, v in fdict.items():
            type_ = v["type"]
            instance = v["fields"]
            required_fields = []
            if type_ == EventType.Create:
                required_fields = [
                    field.own_field_name
                    for field in model_registry[fqid.collection]().get_required_fields()
                    if field.own_field_name not in instance
                    or (
                        field.own_field_name in instance
                        and not instance[field.own_field_name]
                    )
                ]
                fqid_str = f"Creation of {fqid}"
            elif type_ == EventType.Update:
                required_fields = [
                    field.own_field_name
                    for field in model_registry[fqid.collection]().get_required_fields()
                    if field.own_field_name in instance
                    and not instance[field.own_field_name]
                ]
                fqid_str = f"Update of {fqid}"
            if required_fields:
                raise RequiredFieldsException(fqid_str, required_fields)

    def validate_fields(self, instance: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validates all model fields according to the model definition.
        """
        for field_name in instance:
            if self.model.has_field(field_name):
                field = self.model.get_field(field_name)
                instance[field_name] = field.validate(instance[field_name])
        return instance

    def validate_relation_fields(self, instance: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validates all relation fields according to the model definition.
        """
        for field in self.model.get_relation_fields():
            if field.equal_fields:
                if field.own_field_name in instance:
                    fields = [field.own_field_name]
                elif isinstance(field, BaseTemplateRelationField):
                    fields = [
                        instance_field
                        for instance_field, replacement in self.get_structured_fields_in_instance(
                            field, instance
                        )
                    ]
                else:
                    continue
                for instance_field in fields:
                    self.check_equal_fields(field, instance, instance_field)
        return instance

    def check_equal_fields(
        self,
        field: BaseRelationField,
        instance: Dict[str, Any],
        instance_field: str,
        additional_equal_fields: List[str] = [],
    ) -> None:
        """
        Asserts that all fields given in field.equal_fields + additional_equal_fields
        are the same in instance and the model referenced by the name instance_field
        of the given field.
        """
        fqids = self.get_field_value_as_fqid_list(field, instance[instance_field])
        equal_fields = field.equal_fields + additional_equal_fields
        for fqid in fqids:
            related_model = self.fetch_model(fqid, equal_fields)
            for equal_field_name in equal_fields:
                if instance.get(equal_field_name) != related_model.get(
                    equal_field_name
                ):
                    raise ActionException(
                        f"The relation {field.own_field_name} requires the following "
                        f"fields to be equal:\n"
                        f"{field.own_collection}/{instance.get('id', '<new>')}/{equal_field_name}: "
                        f"{str(instance.get(equal_field_name))}\n"
                        f"{fqid}/{equal_field_name}: "
                        f"{str(related_model.get(equal_field_name))}"
                    )

    def get_structured_fields_in_instance(
        self, field: BaseTemplateField, instance: Dict[str, Any]
    ) -> List[Tuple[str, str]]:
        """
        Finds the given field in the given instance and returns the names as well as
        the used replacements of it.
        """
        structured_fields: List[Tuple[str, str]] = []
        for instance_field in instance:
            replacement = field.try_get_replacement(instance_field)
            if replacement:
                structured_fields.append((instance_field, replacement))
        return structured_fields

    def get_field_value_as_fqid_list(
        self, field: BaseRelationField, value: Any
    ) -> List[FullQualifiedId]:
        """ Transforms the given value to an Fqid List. """
        if not isinstance(value, list):
            if value is None:
                value = []
            else:
                value = [value]
        if not isinstance(field, BaseGenericRelationField):
            assert (
                len(field.to) == 1
            )  # non-generic fields can only have one target collection
            value = [FullQualifiedId(field.get_target_collection(), id) for id in value]
        return value

    def fetch_model(
        self, fqid: FullQualifiedId, mapped_fields: List[str] = []
    ) -> Dict[str, Any]:
        """
        Helper method to retrieve an instance from datastore or
        additional_relation_models dictionary.
        """
        if fqid in self.additional_relation_models:
            additional_model = self.additional_relation_models[fqid]
            if mapped_fields:
                return {field: additional_model.get(field) for field in mapped_fields}
            else:
                return additional_model
        else:
            return self.datastore.get(fqid, mapped_fields, lock_result=True)

    def execute_other_action(
        self,
        ActionClass: Type["Action"],
        payload: ActionData,
        additional_relation_models: ModelMap = {},
    ) -> Tuple[Optional[WriteRequest], ActionResults]:
        """
        Executes the given action class as a dependent action with the given payload
        and the given addtional relation models. Merges its own additional relation
        models into it.
        The action is fully executed and created WriteRequests are appended to
        this action.
        """
        action = ActionClass(
            self.services,
            self.datastore,
            self.relation_manager,
            self.logging,
            {
                **self.datastore.additional_relation_models,
                **self.additional_relation_models,
                **additional_relation_models,
            },
        )
        write_request, action_results = action.perform(
            payload, self.user_id, internal=True
        )
        if write_request:
            self.write_requests.append(write_request)
        return write_request, action_results


def merge_write_requests(
    write_requests: Iterable[WriteRequest],
) -> Optional[WriteRequest]:
    """
    Merges the given write request elements to one big write request element.
    """
    events: List[Event] = []
    information: Dict[FullQualifiedId, List[str]] = {}
    user_id: Optional[int] = None
    for element in write_requests:
        events.extend(element.events)
        for fqid, info_text in element.information.items():
            if information.get(fqid) is None:
                information[fqid] = info_text
            else:
                information[fqid].extend(info_text)
        if user_id is None:
            user_id = element.user_id
        else:
            if user_id != element.user_id:
                raise ValueError(
                    "You can not merge two write request elements of different users."
                )
    if events:
        if user_id is None:
            raise ValueError("At least one of the given user ids must not be None.")
        return WriteRequest(
            events=events, information=information, user_id=user_id, locked_fields={}
        )
    else:
        return None
