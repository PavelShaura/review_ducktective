from uuid import (
    UUID,
)

from fastapi import (
    APIRouter,
    HTTPException,
    Response,
    status,
)

from ducktective.api.dependencies import (
    EventPublisherDependency,
)
from ducktective.api.schemas.chat import (
    AttachDocumentRequest,
    ConversationResponse,
    StartConversationRequest,
)
from ducktective.api.security import (
    MemberDependency,
    TenantUnitOfWorkDependency,
)
from ducktective.application.chat.manage import (
    AttachDocument,
    DeleteConversation,
    DetachDocument,
    ListConversations,
    ReadConversation,
    StartConversation,
)
from ducktective.application.exceptions import (
    PermissionDeniedError,
)
from ducktective.core.exceptions import (
    EntityNotFoundError,
    InvariantViolationError,
)
from ducktective.core.types import (
    ConversationId,
    RepositoryId,
)


router = APIRouter(tags=["chat"])


@router.post(
    "/chat/conversations",
    response_model=ConversationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def start_conversation(
    payload: StartConversationRequest,
    response: Response,
    member: MemberDependency,
    unit_of_work: TenantUnitOfWorkDependency,
    event_publisher: EventPublisherDependency,
) -> ConversationResponse:
    """Заводит разговор или возвращает уже начатый пустой.

    Различаются они кодом ответа, а не полем: `201` — завели, `200` —
    вернули прежний. Клиенту это нужно, чтобы объяснить человеку, почему
    после нажатия «новый разговор» он остался там же.
    """
    use_case = StartConversation(unit_of_work, event_publisher)

    try:
        started = await use_case.execute(
            member.tenant_id,
            RepositoryId(payload.repository_id),
            preferred_model=payload.model,
        )
    except EntityNotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except PermissionDeniedError as error:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(error)) from error

    response.status_code = status.HTTP_201_CREATED if started.is_new else status.HTTP_200_OK
    return ConversationResponse.from_view(started.conversation)


@router.get("/chat/conversations", response_model=list[ConversationResponse])
async def list_conversations(
    repository_id: UUID,
    member: MemberDependency,
    unit_of_work: TenantUnitOfWorkDependency,
) -> list[ConversationResponse]:
    views = await ListConversations(unit_of_work).execute(
        member.tenant_id,
        RepositoryId(repository_id),
    )
    return [ConversationResponse.from_view(view) for view in views]


@router.get("/chat/conversations/{conversation_id}", response_model=ConversationResponse)
async def read_conversation(
    conversation_id: UUID,
    member: MemberDependency,
    unit_of_work: TenantUnitOfWorkDependency,
) -> ConversationResponse:
    try:
        view = await ReadConversation(unit_of_work).execute(
            member.tenant_id,
            ConversationId(conversation_id),
        )
    except EntityNotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except PermissionDeniedError as error:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(error)) from error

    return ConversationResponse.from_view(view)


@router.put(
    "/chat/conversations/{conversation_id}/document",
    response_model=ConversationResponse,
)
async def attach_document(
    conversation_id: UUID,
    member: MemberDependency,
    payload: AttachDocumentRequest,
    unit_of_work: TenantUnitOfWorkDependency,
    event_publisher: EventPublisherDependency,
) -> ConversationResponse:
    """Прикладывает документ к разговору.

    Текстом, а не файлом: читает файл браузер, сервер не принимает двоичного
    и не разбирает форматов (D-025). Документ один, поэтому `PUT` —
    приложенный второй заменяет первый.
    """
    try:
        view = await AttachDocument(unit_of_work, event_publisher).execute(
            member.tenant_id,
            ConversationId(conversation_id),
            payload.name,
            payload.text,
        )
    except EntityNotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except PermissionDeniedError as error:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(error)) from error
    except InvariantViolationError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(error)) from error

    return ConversationResponse.from_view(view)


@router.delete(
    "/chat/conversations/{conversation_id}/document",
    response_model=ConversationResponse,
)
async def detach_document(
    conversation_id: UUID,
    member: MemberDependency,
    unit_of_work: TenantUnitOfWorkDependency,
    event_publisher: EventPublisherDependency,
) -> ConversationResponse:
    try:
        view = await DetachDocument(unit_of_work, event_publisher).execute(
            member.tenant_id,
            ConversationId(conversation_id),
        )
    except EntityNotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except PermissionDeniedError as error:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(error)) from error

    return ConversationResponse.from_view(view)


@router.delete("/chat/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: UUID,
    member: MemberDependency,
    unit_of_work: TenantUnitOfWorkDependency,
    event_publisher: EventPublisherDependency,
) -> None:
    try:
        await DeleteConversation(unit_of_work, event_publisher).execute(
            member.tenant_id,
            ConversationId(conversation_id),
        )
    except EntityNotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except PermissionDeniedError as error:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(error)) from error
