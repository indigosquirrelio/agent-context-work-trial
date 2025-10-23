"""
API endpoints for edit version management and conflict resolution.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict, List, Optional, Any

from fastapi import APIRouter, HTTPException, Query, Path as PathParam
from pydantic import BaseModel, Field

from .edit_versioning import (
    EditVersionManager, 
    EditSource, 
    EditType, 
    ConflictResolutionStrategy,
    EditOperation,
    EditVersion,
    EditConflict
)
from .agent import get_edit_version_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/versions", tags=["version_management"])


# Request/Response Models

class EditOperationRequest(BaseModel):
    file_path: str
    source: str  # "user" or "agent"
    edit_type: str  # "search_replace", "full_content", "insert", "delete"
    description: str
    owner: str
    
    # For search/replace operations
    search_text: Optional[str] = None
    replace_text: Optional[str] = None
    
    # For full content operations
    content: Optional[str] = None
    
    # For insert/delete operations
    position: Optional[int] = None
    length: Optional[int] = None
    
    # Metadata
    metadata: Optional[Dict[str, Any]] = None


class EditOperationResponse(BaseModel):
    operation_id: str
    file_path: str
    source: str
    edit_type: str
    timestamp: str
    owner: str
    description: str
    search_text: Optional[str] = None
    replace_text: Optional[str] = None
    content: Optional[str] = None
    position: Optional[int] = None
    length: Optional[int] = None
    metadata: Optional[Dict[str, Any]] = None


class EditVersionResponse(BaseModel):
    version_id: str
    file_path: str
    content: str
    etag: str
    timestamp: str
    source: str
    owner: str
    base_version_id: Optional[str] = None
    edit_operations: List[str] = Field(default_factory=list)
    conflicts: List[str] = Field(default_factory=list)


class EditConflictResponse(BaseModel):
    conflict_id: str
    file_path: str
    user_version_id: str
    agent_version_id: str
    timestamp: str
    resolution_strategy: str
    resolved: bool = False
    resolved_version_id: Optional[str] = None
    resolution_notes: Optional[str] = None


class ConflictResolutionRequest(BaseModel):
    resolution_content: str
    resolution_notes: Optional[str] = None


class FileHistoryResponse(BaseModel):
    file_path: str
    versions: List[Dict[str, Any]] = Field(default_factory=list)


class AggregateEditsRequest(BaseModel):
    file_path: str
    strategy: str = "merge"  # "user_priority", "agent_priority", "merge", "manual"


class AggregateEditsResponse(BaseModel):
    file_path: str
    aggregated_content: str
    conflicts_requiring_manual_resolution: List[str] = Field(default_factory=list)
    strategy_used: str


# API Endpoints

@router.post("/operations", response_model=EditOperationResponse)
async def record_edit_operation(request: EditOperationRequest) -> EditOperationResponse:
    """Record a new edit operation."""
    try:
        version_manager = get_edit_version_manager()
        
        # Convert string enums
        source = EditSource(request.source)
        edit_type = EditType(request.edit_type)
        
        operation = await version_manager.record_edit_operation(
            file_path=request.file_path,
            source=source,
            edit_type=edit_type,
            owner=request.owner,
            description=request.description,
            search_text=request.search_text,
            replace_text=request.replace_text,
            content=request.content,
            position=request.position,
            length=request.length,
            metadata=request.metadata or {}
        )
        
        return EditOperationResponse(
            operation_id=operation.id,
            file_path=operation.file_path,
            source=operation.source.value,
            edit_type=operation.edit_type.value,
            timestamp=operation.timestamp.isoformat(),
            owner=operation.owner,
            description=operation.description,
            search_text=operation.search_text,
            replace_text=operation.replace_text,
            content=operation.content,
            position=operation.position,
            length=operation.length,
            metadata=operation.metadata
        )
        
    except Exception as e:
        logger.error(f"Failed to record edit operation: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to record edit operation: {e}")


@router.post("/versions", response_model=EditVersionResponse)
async def create_edit_version(
    file_path: str,
    content: str,
    source: str,
    owner: str,
    base_version_id: Optional[str] = None,
    edit_operation_ids: Optional[List[str]] = None
) -> EditVersionResponse:
    """Create a new edit version."""
    try:
        version_manager = get_edit_version_manager()
        
        edit_source = EditSource(source)
        
        version = await version_manager.create_edit_version(
            file_path=file_path,
            content=content,
            source=edit_source,
            owner=owner,
            base_version_id=base_version_id,
            edit_operation_ids=edit_operation_ids or []
        )
        
        return EditVersionResponse(
            version_id=version.version_id,
            file_path=version.file_path,
            content=version.content,
            etag=version.etag,
            timestamp=version.timestamp.isoformat(),
            source=version.source.value,
            owner=version.owner,
            base_version_id=version.base_version_id,
            edit_operations=version.edit_operations,
            conflicts=version.conflicts
        )
        
    except Exception as e:
        logger.error(f"Failed to create edit version: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create edit version: {e}")


@router.get("/versions/{file_path:path}", response_model=List[EditVersionResponse])
async def get_versions_for_file(file_path: str) -> List[EditVersionResponse]:
    """Get all versions for a specific file."""
    try:
        version_manager = get_edit_version_manager()
        versions = await version_manager.get_versions_for_file(file_path)
        
        return [
            EditVersionResponse(
                version_id=version.version_id,
                file_path=version.file_path,
                content=version.content,
                etag=version.etag,
                timestamp=version.timestamp.isoformat(),
                source=version.source.value,
                owner=version.owner,
                base_version_id=version.base_version_id,
                edit_operations=version.edit_operations,
                conflicts=version.conflicts
            )
            for version in versions
        ]
        
    except Exception as e:
        logger.error(f"Failed to get versions for file {file_path}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get versions: {e}")


@router.get("/versions/{file_path:path}/latest", response_model=EditVersionResponse)
async def get_latest_version(
    file_path: str,
    source: Optional[str] = Query(None, description="Filter by source: user, agent, or system")
) -> EditVersionResponse:
    """Get the latest version of a file, optionally filtered by source."""
    try:
        version_manager = get_edit_version_manager()
        
        edit_source = EditSource(source) if source else None
        version = await version_manager.get_latest_version(file_path, edit_source)
        
        if not version:
            raise HTTPException(status_code=404, detail=f"No versions found for file {file_path}")
        
        return EditVersionResponse(
            version_id=version.version_id,
            file_path=version.file_path,
            content=version.content,
            etag=version.etag,
            timestamp=version.timestamp.isoformat(),
            source=version.source.value,
            owner=version.owner,
            base_version_id=version.base_version_id,
            edit_operations=version.edit_operations,
            conflicts=version.conflicts
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get latest version for file {file_path}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get latest version: {e}")


@router.post("/aggregate", response_model=AggregateEditsResponse)
async def aggregate_edits(request: AggregateEditsRequest) -> AggregateEditsResponse:
    """Aggregate user and agent edits for a file."""
    try:
        version_manager = get_edit_version_manager()
        
        strategy = ConflictResolutionStrategy(request.strategy)
        
        aggregated_content, conflicts = await version_manager.aggregate_edits(
            request.file_path, 
            strategy
        )
        
        return AggregateEditsResponse(
            file_path=request.file_path,
            aggregated_content=aggregated_content,
            conflicts_requiring_manual_resolution=[c.conflict_id for c in conflicts],
            strategy_used=request.strategy
        )
        
    except Exception as e:
        logger.error(f"Failed to aggregate edits for file {request.file_path}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to aggregate edits: {e}")


@router.get("/conflicts", response_model=List[EditConflictResponse])
async def get_conflicts(
    file_path: Optional[str] = Query(None, description="Filter conflicts by file path"),
    resolved: Optional[bool] = Query(None, description="Filter by resolution status")
) -> List[EditConflictResponse]:
    """Get all conflicts, optionally filtered by file path and resolution status."""
    try:
        version_manager = get_edit_version_manager()
        
        # This would need to be implemented in the version manager
        # For now, we'll return a placeholder
        conflicts = []  # await version_manager.get_conflicts(file_path, resolved)
        
        return [
            EditConflictResponse(
                conflict_id=conflict.conflict_id,
                file_path=conflict.file_path,
                user_version_id=conflict.user_version_id,
                agent_version_id=conflict.agent_version_id,
                timestamp=conflict.timestamp.isoformat(),
                resolution_strategy=conflict.resolution_strategy.value,
                resolved=conflict.resolved,
                resolved_version_id=conflict.resolved_version_id,
                resolution_notes=conflict.resolution_notes
            )
            for conflict in conflicts
        ]
        
    except Exception as e:
        logger.error(f"Failed to get conflicts: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get conflicts: {e}")


@router.post("/conflicts/{conflict_id}/resolve", response_model=EditVersionResponse)
async def resolve_conflict(
    conflict_id: str,
    request: ConflictResolutionRequest
) -> EditVersionResponse:
    """Manually resolve a conflict."""
    try:
        version_manager = get_edit_version_manager()
        
        resolved_version = await version_manager.resolve_conflict(
            conflict_id=conflict_id,
            resolution_content=request.resolution_content,
            resolution_notes=request.resolution_notes
        )
        
        return EditVersionResponse(
            version_id=resolved_version.version_id,
            file_path=resolved_version.file_path,
            content=resolved_version.content,
            etag=resolved_version.etag,
            timestamp=resolved_version.timestamp.isoformat(),
            source=resolved_version.source.value,
            owner=resolved_version.owner,
            base_version_id=resolved_version.base_version_id,
            edit_operations=resolved_version.edit_operations,
            conflicts=resolved_version.conflicts
        )
        
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to resolve conflict {conflict_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to resolve conflict: {e}")


@router.get("/history/{file_path:path}", response_model=FileHistoryResponse)
async def get_file_history(file_path: str) -> FileHistoryResponse:
    """Get complete history for a file."""
    try:
        version_manager = get_edit_version_manager()
        history = await version_manager.get_file_history(file_path)
        
        return FileHistoryResponse(
            file_path=file_path,
            versions=history
        )
        
    except Exception as e:
        logger.error(f"Failed to get file history for {file_path}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get file history: {e}")


@router.post("/cleanup")
async def cleanup_old_versions(
    max_versions_per_file: int = Query(50, description="Maximum versions to keep per file")
) -> Dict[str, str]:
    """Clean up old versions to prevent storage bloat."""
    try:
        version_manager = get_edit_version_manager()
        await version_manager.cleanup_old_versions(max_versions_per_file)
        
        return {"message": f"Cleanup completed. Keeping max {max_versions_per_file} versions per file."}
        
    except Exception as e:
        logger.error(f"Failed to cleanup old versions: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to cleanup old versions: {e}")


@router.post("/files/{file_path:path}/user-edit")
async def record_user_edit(
    file_path: str,
    content: str,
    owner: str = "user",
    description: str = "User edit"
) -> EditVersionResponse:
    """Record a user edit (typically called when user saves in the frontend)."""
    try:
        version_manager = get_edit_version_manager()
        
        # Record the edit operation
        operation = await version_manager.record_edit_operation(
            file_path=file_path,
            source=EditSource.USER,
            edit_type=EditType.FULL_CONTENT,
            owner=owner,
            description=description,
            content=content
        )
        
        # Create version record
        version = await version_manager.create_edit_version(
            file_path=file_path,
            content=content,
            source=EditSource.USER,
            owner=owner,
            edit_operation_ids=[operation.id]
        )
        
        # Check for conflicts
        conflicts = await version_manager.detect_conflicts(file_path)
        
        return EditVersionResponse(
            version_id=version.version_id,
            file_path=version.file_path,
            content=version.content,
            etag=version.etag,
            timestamp=version.timestamp.isoformat(),
            source=version.source.value,
            owner=version.owner,
            base_version_id=version.base_version_id,
            edit_operations=version.edit_operations,
            conflicts=version.conflicts
        )
        
    except Exception as e:
        logger.error(f"Failed to record user edit for {file_path}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to record user edit: {e}")


@router.post("/files/{file_path:path}/unsaved-user-edit")
async def record_unsaved_user_edit(
    file_path: str,
    content: str,
    owner: str = "user",
    description: str = "Unsaved user edit"
) -> Dict[str, str]:
    """Record an unsaved user edit (for real-time collaboration)."""
    try:
        version_manager = get_edit_version_manager()
        
        # Record the edit operation as an unsaved edit
        operation = await version_manager.record_edit_operation(
            file_path=file_path,
            source=EditSource.USER,
            edit_type=EditType.FULL_CONTENT,
            owner=owner,
            description=description,
            content=content,
            metadata={"unsaved": True, "timestamp": datetime.now().isoformat()}
        )
        
        # Store in a special "unsaved edits" cache
        # This could be enhanced with Redis or similar for production
        unsaved_edits_key = f"unsaved_edits_{file_path}"
        
        return {
            "status": "success",
            "operation_id": operation.id,
            "message": f"Unsaved user edit recorded for {file_path}"
        }
        
    except Exception as e:
        logger.error(f"Failed to record unsaved user edit for {file_path}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to record unsaved user edit: {e}")


@router.get("/files/{file_path:path}/unsaved-edits")
async def get_unsaved_edits(file_path: str) -> Dict[str, Any]:
    """Get any unsaved edits for a file."""
    try:
        version_manager = get_edit_version_manager()
        
        # Get operations marked as unsaved
        unsaved_operations = [
            op for op in version_manager._edit_operations.values()
            if op.file_path == file_path and op.metadata.get("unsaved", False)
        ]
        
        return {
            "file_path": file_path,
            "unsaved_operations": [op.to_dict() for op in unsaved_operations]
        }
        
    except Exception as e:
        logger.error(f"Failed to get unsaved edits for {file_path}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get unsaved edits: {e}")


@router.delete("/files/{file_path:path}/unsaved-edits")
async def clear_unsaved_edits(file_path: str) -> Dict[str, str]:
    """Clear unsaved edits for a file (when user saves or discards changes)."""
    try:
        version_manager = get_edit_version_manager()
        
        # Remove unsaved operations for this file
        operations_to_remove = [
            op_id for op_id, op in version_manager._edit_operations.items()
            if op.file_path == file_path and op.metadata.get("unsaved", False)
        ]
        
        for op_id in operations_to_remove:
            del version_manager._edit_operations[op_id]
        
        await version_manager._save_edit_operations()
        
        return {
            "status": "success",
            "message": f"Cleared {len(operations_to_remove)} unsaved edits for {file_path}"
        }
        
    except Exception as e:
        logger.error(f"Failed to clear unsaved edits for {file_path}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to clear unsaved edits: {e}")


@router.post("/files/{file_path:path}/save-before-agent")
async def save_before_agent_operation(
    file_path: str,
    content: Optional[str] = None,
    owner: str = "user",
    description: str = "Save before agent operation"
) -> Dict[str, Any]:
    """Save current file state before agent operations to prevent data loss."""
    try:
        version_manager = get_edit_version_manager()
        
        # If content is provided, use it; otherwise read from file
        if content is None:
            # Read from file if no content provided
            from .file_client import HTTPFileClient
            client = HTTPFileClient.from_env()
            try:
                file_data = await client.read(file_path)
                content = file_data["content"]
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Could not read file content: {e}")
        
        # AUTOMATICALLY SAVE the file to disk
        from .file_client import HTTPFileClient
        client = HTTPFileClient.from_env()
        await client.write(file_path, content)
        
        # Create a backup version record
        backup_version = await version_manager.create_edit_version(
            file_path=file_path,
            content=content,
            source=EditSource.USER,
            owner=owner,
            edit_operation_ids=[]
        )
        
        return {
            "status": "success",
            "backup_version_id": backup_version.version_id,
            "message": f"File automatically saved and backed up before agent operation for {file_path}",
            "timestamp": backup_version.timestamp.isoformat(),
            "file_saved": True
        }
        
    except Exception as e:
        logger.error(f"Failed to save before agent operation for {file_path}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save before agent operation: {e}")


@router.post("/files/{file_path:path}/restore-from-backup")
async def restore_from_backup(
    file_path: str,
    backup_version_id: str
) -> Dict[str, str]:
    """Restore file from a backup version."""
    try:
        version_manager = get_edit_version_manager()
        
        # Find the backup version
        if backup_version_id not in version_manager._edit_versions:
            raise HTTPException(status_code=404, detail=f"Backup version {backup_version_id} not found")
        
        backup_version = version_manager._edit_versions[backup_version_id]
        
        # Write the backup content back to the file
        from .file_client import HTTPFileClient
        client = HTTPFileClient.from_env()
        
        await client.write(file_path, backup_version.content)
        
        return {
            "status": "success",
            "message": f"File {file_path} restored from backup version {backup_version_id}",
            "restored_content": backup_version.content
        }
        
    except Exception as e:
        logger.error(f"Failed to restore from backup for {file_path}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to restore from backup: {e}")
