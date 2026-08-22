from typing import (
    NewType,
)
from uuid import (
    UUID,
)


TenantId = NewType("TenantId", UUID)
UserId = NewType("UserId", UUID)
RepositoryId = NewType("RepositoryId", UUID)
IndexSnapshotId = NewType("IndexSnapshotId", UUID)
SourceFileId = NewType("SourceFileId", UUID)
CodeSymbolId = NewType("CodeSymbolId", UUID)
SymbolEdgeId = NewType("SymbolEdgeId", UUID)
CodeChunkId = NewType("CodeChunkId", UUID)
EmbeddingModelId = NewType("EmbeddingModelId", UUID)
ReviewRunId = NewType("ReviewRunId", UUID)
ReviewFileId = NewType("ReviewFileId", UUID)
ReviewHunkId = NewType("ReviewHunkId", UUID)
FindingId = NewType("FindingId", UUID)
FindingFeedbackId = NewType("FindingFeedbackId", UUID)
ConversationId = NewType("ConversationId", UUID)
MessageId = NewType("MessageId", UUID)

CommitSha = NewType("CommitSha", str)
ContentHash = NewType("ContentHash", str)
QualifiedName = NewType("QualifiedName", str)
