from __future__ import annotations

import asyncio
import hashlib
import logging
import tempfile
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple, Any, Dict

from .file_locks import get_lock_manager, FileLockedError, FileConflictError

logger = logging.getLogger(__name__)


@dataclass
class AtomicOperationResult:
    """Result of an atomic file operation."""
    success: bool
    file_path: str
    content: str
    etag: str
    version: int
    error: Optional[str] = None
    conflict_resolved: bool = False


class AtomicFileOperations:
    """Provides atomic file operations with conflict resolution."""
    
    def __init__(self, workspace_root: Path, encoding: str = "utf-8"):
        self.workspace_root = workspace_root
        self.encoding = encoding
        self.lock_manager = get_lock_manager()
    
    def _etag_for_content(self, content: str) -> str:
        """Generate ETag for content."""
        return hashlib.sha256(content.encode(self.encoding)).hexdigest()
    
    def _read_file_atomic(self, file_path: Path) -> Tuple[str, str]:
        """Atomically read a file and return content + ETag."""
        try:
            raw_content = file_path.read_bytes()
            content = raw_content.decode(self.encoding)
            etag = hashlib.sha256(raw_content).hexdigest()
            return content, etag
        except FileNotFoundError:
            raise FileNotFoundError(f"File {file_path} not found")
        except UnicodeDecodeError as e:
            raise ValueError(f"Invalid encoding for file {file_path}: {e}")
    
    def _write_file_atomic(self, file_path: Path, content: str, backup: bool = True) -> str:
        """Atomically write a file using temporary file + rename."""
        try:
            # Ensure parent directory exists
            file_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Create backup if requested
            if backup and file_path.exists():
                backup_path = file_path.with_suffix(f"{file_path.suffix}.backup.{int(time.time())}")
                file_path.rename(backup_path)
                logger.debug(f"Created backup: {backup_path}")
            
            # Write to temporary file first
            with tempfile.NamedTemporaryFile(
                mode='w',
                encoding=self.encoding,
                dir=file_path.parent,
                delete=False,
                prefix=f".tmp_{file_path.name}."
            ) as temp_file:
                temp_file.write(content)
                temp_path = Path(temp_file.name)
            
            # Atomic rename (this is atomic on most filesystems)
            temp_path.rename(file_path)
            
            # Generate ETag for the written content
            etag = self._etag_for_content(content)
            logger.debug(f"Atomically wrote {file_path} (ETag: {etag[:8]}...)")
            return etag
            
        except Exception as e:
            # Clean up temp file if it exists
            if 'temp_path' in locals() and temp_path.exists():
                temp_path.unlink()
            raise e
    
    @asynccontextmanager
    async def atomic_read_modify_write(
        self,
        file_path: str,
        owner: str,
        operation_type: str = "read_modify_write",
        context: Optional[str] = None,
        timeout: Optional[float] = None
    ):
        """Context manager for atomic read-modify-write operations."""
        resolved_path = (self.workspace_root / file_path).resolve()
        
        # Ensure path is within workspace
        if not str(resolved_path).startswith(str(self.workspace_root)):
            raise ValueError(f"Path {file_path} is outside workspace")
        
        # Acquire lock
        async with self.lock_manager.acquire_lock(
            file_path=file_path,
            owner=owner,
            operation_type=operation_type,
            context=context,
            timeout=timeout
        ):
            try:
                # Read current content
                if resolved_path.exists():
                    content, etag = self._read_file_atomic(resolved_path)
                else:
                    content, etag = "", ""
                
                # Check for conflicts if we have a previous version
                current_version = self.lock_manager.get_file_version(file_path)
                if current_version and current_version.etag != etag:
                    raise FileConflictError(
                        f"File {file_path} was modified by {current_version.owner} "
                        f"since last read (ETag mismatch: {current_version.etag} vs {etag})"
                    )
                
                # Yield the current content for modification
                yield content, etag
                
            except Exception as e:
                logger.error(f"Error in atomic read-modify-write for {file_path}: {e}")
                raise
    
    async def atomic_write(
        self,
        file_path: str,
        content: str,
        owner: str,
        expected_etag: Optional[str] = None,
        context: Optional[str] = None
    ) -> AtomicOperationResult:
        """Atomically write content to a file with conflict detection."""
        resolved_path = (self.workspace_root / file_path).resolve()
        
        # Ensure path is within workspace
        if not str(resolved_path).startswith(str(self.workspace_root)):
            return AtomicOperationResult(
                success=False,
                file_path=file_path,
                content=content,
                etag="",
                version=0,
                error=f"Path {file_path} is outside workspace"
            )
        
        try:
            async with self.lock_manager.acquire_lock(
                file_path=file_path,
                owner=owner,
                operation_type="write",
                context=context
            ):
                # Check for conflicts if expected ETag provided
                if expected_etag and resolved_path.exists():
                    current_content, current_etag = self._read_file_atomic(resolved_path)
                    if current_etag != expected_etag:
                        return AtomicOperationResult(
                            success=False,
                            file_path=file_path,
                            content=content,
                            etag=current_etag,
                            version=0,
                            error=f"Conflict detected: expected ETag {expected_etag}, got {current_etag}",
                            conflict_resolved=False
                        )
                
                # Write content atomically
                etag = self._write_file_atomic(resolved_path, content)
                
                # Update version tracking
                version = self.lock_manager.update_file_version(
                    file_path=file_path,
                    content=content,
                    etag=etag,
                    owner=owner
                )
                
                logger.info(f"Successfully wrote {file_path} (v{version.version}) by {owner}")
                
                return AtomicOperationResult(
                    success=True,
                    file_path=file_path,
                    content=content,
                    etag=etag,
                    version=version.version
                )
                
        except FileLockedError as e:
            return AtomicOperationResult(
                success=False,
                file_path=file_path,
                content=content,
                etag="",
                version=0,
                error=f"File locked: {e}"
            )
        except FileConflictError as e:
            return AtomicOperationResult(
                success=False,
                file_path=file_path,
                content=content,
                etag="",
                version=0,
                error=f"Conflict detected: {e}",
                conflict_resolved=False
            )
        except Exception as e:
            return AtomicOperationResult(
                success=False,
                file_path=file_path,
                content=content,
                etag="",
                version=0,
                error=f"Write failed: {e}"
            )
    
    async def atomic_read(
        self,
        file_path: str,
        owner: str,
        context: Optional[str] = None
    ) -> Tuple[str, str, int]:
        """Atomically read a file and return content, ETag, and version."""
        resolved_path = (self.workspace_root / file_path).resolve()
        
        # Ensure path is within workspace
        if not str(resolved_path).startswith(str(self.workspace_root)):
            raise ValueError(f"Path {file_path} is outside workspace")
        
        async with self.lock_manager.acquire_lock(
            file_path=file_path,
            owner=owner,
            operation_type="read",
            context=context
        ):
            if not resolved_path.exists():
                raise FileNotFoundError(f"File {file_path} not found")
            
            content, etag = self._read_file_atomic(resolved_path)
            
            # Update version tracking
            version = self.lock_manager.update_file_version(
                file_path=file_path,
                content=content,
                etag=etag,
                owner=owner
            )
            
            return content, etag, version.version
    
    async def atomic_delete(
        self,
        file_path: str,
        owner: str,
        context: Optional[str] = None
    ) -> AtomicOperationResult:
        """Atomically delete a file."""
        resolved_path = (self.workspace_root / file_path).resolve()
        
        # Ensure path is within workspace
        if not str(resolved_path).startswith(str(self.workspace_root)):
            return AtomicOperationResult(
                success=False,
                file_path=file_path,
                content="",
                etag="",
                version=0,
                error=f"Path {file_path} is outside workspace"
            )
        
        try:
            async with self.lock_manager.acquire_lock(
                file_path=file_path,
                owner=owner,
                operation_type="delete",
                context=context
            ):
                if not resolved_path.exists():
                    return AtomicOperationResult(
                        success=False,
                        file_path=file_path,
                        content="",
                        etag="",
                        version=0,
                        error=f"File {file_path} does not exist"
                    )
                
                # Create backup before deletion
                backup_path = resolved_path.with_suffix(f"{resolved_path.suffix}.deleted.{int(time.time())}")
                resolved_path.rename(backup_path)
                
                # Update version tracking
                version = self.lock_manager.update_file_version(
                    file_path=file_path,
                    content="",
                    etag="",
                    owner=owner
                )
                
                logger.info(f"Successfully deleted {file_path} (backup: {backup_path}) by {owner}")
                
                return AtomicOperationResult(
                    success=True,
                    file_path=file_path,
                    content="",
                    etag="",
                    version=version.version
                )
                
        except FileLockedError as e:
            return AtomicOperationResult(
                success=False,
                file_path=file_path,
                content="",
                etag="",
                version=0,
                error=f"File locked: {e}"
            )
        except Exception as e:
            return AtomicOperationResult(
                success=False,
                file_path=file_path,
                content="",
                etag="",
                version=0,
                error=f"Delete failed: {e}"
            )
    
    async def check_file_status(self, file_path: str) -> Dict[str, Any]:
        """Check the current status of a file (locked, version, etc.)."""
        lock_info = self.lock_manager.get_lock_info(file_path)
        version_info = self.lock_manager.get_file_version(file_path)
        
        resolved_path = (self.workspace_root / file_path).resolve()
        exists = resolved_path.exists()
        
        status = {
            "file_path": file_path,
            "exists": exists,
            "locked": lock_info is not None,
            "lock_info": {
                "owner": lock_info.owner if lock_info else None,
                "operation": lock_info.operation_type if lock_info else None,
                "acquired_at": lock_info.acquired_at if lock_info else None,
                "expires_at": lock_info.expires_at if lock_info else None,
            } if lock_info else None,
            "version_info": {
                "version": version_info.version if version_info else 0,
                "etag": version_info.etag if version_info else None,
                "last_modified_by": version_info.owner if version_info else None,
                "created_at": version_info.created_at if version_info else None,
            } if version_info else None,
        }
        
        return status
