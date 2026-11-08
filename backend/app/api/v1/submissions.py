"""Submission intake endpoint."""

from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, require_permission
from app.documents.config import DocumentSettings
from app.documents.errors import DocumentInputError, DocumentProcessingError
from app.modules.submissions.schemas import CreateSubmissionResponse, CreateTextSubmissionRequest
from app.modules.submissions.services import (
    create_document_submission_with_analysis,
    create_submission_with_analysis,
)
from app.modules.tenancy.schemas import TenantScope

router = APIRouter(tags=["submissions"])


@router.post(
    "/api/v1/organizations/{org_id}/workspaces/{workspace_id}/submissions",
    response_model=CreateSubmissionResponse,
    status_code=201,
)
def create_submission(
    org_id: UUID,
    workspace_id: UUID,
    payload: CreateTextSubmissionRequest,
    db: Session = Depends(get_db),
    scope: TenantScope = Depends(require_permission("submission.create")),
) -> CreateSubmissionResponse:
    if org_id != scope.organization_id or workspace_id != scope.workspace_id:
        raise HTTPException(status_code=403, detail="Tenant scope does not match the requested workspace.")
    try:
        result = create_submission_with_analysis(
            db,
            scope,
            submitter_id=scope.user_id,
            source_type=payload.source_type,
            submitted_text=payload.submitted_text,
        )
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return CreateSubmissionResponse(
        submission_id=result.submission.id,
        version_id=result.version.id,
        current_status=result.submission.current_status,
        analysis_run_id=result.analysis_run.id,
        analysis_status=result.analysis_run.overall_state,
    )


@router.post(
    "/api/v1/organizations/{org_id}/workspaces/{workspace_id}/submissions/documents",
    response_model=CreateSubmissionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_document_submission(
    org_id: UUID,
    workspace_id: UUID,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    scope: TenantScope = Depends(require_permission("submission.create")),
) -> CreateSubmissionResponse:
    if org_id != scope.organization_id or workspace_id != scope.workspace_id:
        await file.close()
        raise HTTPException(status_code=403, detail="Tenant scope does not match the requested workspace.")
    try:
        try:
            settings = DocumentSettings.from_environment()
        except ValueError as exc:
            raise HTTPException(
                status_code=503,
                detail={"error": {"code": "DOCUMENT_CONFIGURATION_INVALID", "message": "Document upload is not configured."}},
            ) from exc
        content = bytearray()
        while block := await file.read(64 * 1024):
            content.extend(block)
            if len(content) > settings.max_upload_bytes:
                raise DocumentInputError(
                    "file_too_large",
                    "The document exceeds the configured upload size limit.",
                    413,
                )
        result = create_document_submission_with_analysis(
            db,
            scope,
            submitter_id=scope.user_id,
            filename=file.filename,
            content=bytes(content),
            settings=settings,
        )
    except DocumentInputError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"error": {"code": exc.code, "message": exc.message}},
        ) from exc
    except DocumentProcessingError as exc:
        raise HTTPException(
            status_code=422,
            detail={"error": {"code": exc.code, "message": exc.message}},
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(
            status_code=503,
            detail={"error": {"code": "DOCUMENT_STORAGE_UNAVAILABLE", "message": "The document could not be stored."}},
        ) from exc
    except HTTPException:
        raise
    finally:
        await file.close()
    return CreateSubmissionResponse(
        submission_id=result.submission.id,
        version_id=result.version.id,
        current_status=result.submission.current_status,
        analysis_run_id=result.analysis_run.id,
        analysis_status=result.analysis_run.overall_state,
        extraction_status="Succeeded",
        extracted_text=result.extracted_text,
    )
