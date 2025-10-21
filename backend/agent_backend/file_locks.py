from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional, Set
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)


@dataclass
class FileLock:
    """Represents a file lock with metadata."""
    file_path: str
    lock_id: str
    owner: str  # 'agent', 'user', 'third_party', etc.
    acquired_at: float
    expires_at: float
    operation_type: str  # 'read', 'write', 'delete'
    context: Optional[str] = None  # Additional context about the operation


@dataclass
class FileVersion:
    """Represents a file version for conflict detection."""
    file_path: str
    version: int
    etag: str
    content: str
    created_at: float
    owner: str


class FileLockManager:
    """Manages file locks and prevents race conditions."""
    
    def __init__(self, lock_timeout: float = 30.0):
        self._locks: Dict[str, FileLock] = {}
        self._versions: Dict[str, FileVersion] = {}
        self._lock_timeout = lock_timeout
        self._lock_semaphores: Dict[str, asyncio.Semaphore] = {}
        self._cleanup_task: Optional[asyncio.Task] = None
        self._start_cleanup_task()
    
    def _start_cleanup_task(self):
        """Start background task to clean up expired locks."""
        async def cleanup_expired_locks():
            while True:
                try:
                    await asyncio.sleep(5)  # Check every 5 seconds
                    current_time = time.time()
                    expired_locks = [
                        path for path, lock in self._locks.items()
                        if current_time > lock.expires_at
                    ]
                    for path in expired_locks:
                        logger.warning(f"Cleaning up expired lock for {path}")
                        self._release_lock(path)
                except Exception as e:
                    logger.error(f"Error in lock cleanup task: {e}")
        
        self._cleanup_task = asyncio.create_task(cleanup_expired_locks())
    
    def _get_semaphore(self, file_path: str) -> asyncio.Semaphore:
        """Get or create a semaphore for a file path."""
        if file_path not in self._lock_semaphores:
            self._lock_semaphores[file_path] = asyncio.Semaphore(1)
        return self._lock_semaphores[file_path]
    
    @asynccontextmanager
    async def acquire_lock(
        self,
        file_path: str,
        owner: str,
        operation_type: str,
        context: Optional[str] = None,
        timeout: Optional[float] = None
    ):
        """Acquire a file lock with automatic cleanup."""
        lock_id = str(uuid.uuid4())
        acquired_time = time.time()
        expires_at = acquired_time + (timeout or self._lock_timeout)
        
        # Wait for semaphore (prevents multiple operations on same file)
        semaphore = self._get_semaphore(file_path)
        await asyncio.wait_for(semaphore.acquire(), timeout=timeout or self._lock_timeout)
        
        try:
            # Check if file is already locked
            if file_path in self._locks:
                existing_lock = self._locks[file_path]
                if time.time() < existing_lock.expires_at:
                    raise FileLockedError(
                        f"File {file_path} is locked by {existing_lock.owner} "
                        f"(operation: {existing_lock.operation_type})"
                    )
                else:
                    # Clean up expired lock
                    self._release_lock(file_path)
            
            # Create new lock
            lock = FileLock(
                file_path=file_path,
                lock_id=lock_id,
                owner=owner,
                acquired_at=acquired_time,
                expires_at=expires_at,
                operation_type=operation_type,
                context=context
            )
            
            self._locks[file_path] = lock
            logger.info(f"Acquired lock for {file_path} by {owner} ({operation_type})")
            
            yield lock
            
        finally:
            # Always release the lock
            self._release_lock(file_path)
            semaphore.release()
    
    def _release_lock(self, file_path: str):
        """Release a file lock."""
        if file_path in self._locks:
            lock = self._locks.pop(file_path)
            logger.info(f"Released lock for {file_path} (was held by {lock.owner})")
    
    def is_locked(self, file_path: str) -> bool:
        """Check if a file is currently locked."""
        if file_path not in self._locks:
            return False
        
        lock = self._locks[file_path]
        if time.time() > lock.expires_at:
            # Lock expired, clean it up
            self._release_lock(file_path)
            return False
        
        return True
    
    def get_lock_info(self, file_path: str) -> Optional[FileLock]:
        """Get information about a file lock."""
        if file_path not in self._locks:
            return None
        
        lock = self._locks[file_path]
        if time.time() > lock.expires_at:
            self._release_lock(file_path)
            return None
        
        return lock
    
    def update_file_version(
        self,
        file_path: str,
        content: str,
        etag: str,
        owner: str
    ) -> FileVersion:
        """Update file version for conflict detection."""
        current_version = self._versions.get(file_path, FileVersion(
            file_path=file_path,
            version=0,
            etag="",
            content="",
            created_at=0,
            owner=""
        ))
        
        new_version = FileVersion(
            file_path=file_path,
            version=current_version.version + 1,
            etag=etag,
            content=content,
            created_at=time.time(),
            owner=owner
        )
        
        self._versions[file_path] = new_version
        logger.debug(f"Updated version for {file_path} to v{new_version.version}")
        return new_version
    
    def get_file_version(self, file_path: str) -> Optional[FileVersion]:
        """Get current file version."""
        return self._versions.get(file_path)
    
    def check_conflict(
        self,
        file_path: str,
        expected_etag: str,
        owner: str
    ) -> bool:
        """Check if file has been modified since last read (conflict detection)."""
        current_version = self.get_file_version(file_path)
        if not current_version:
            return False  # No previous version, no conflict
        
        # If ETags don't match, file was modified
        if current_version.etag != expected_etag:
            logger.warning(
                f"Conflict detected for {file_path}: expected {expected_etag}, "
                f"got {current_version.etag} (last modified by {current_version.owner})"
            )
            return True
        
        return False
    
    def force_release_lock(self, file_path: str, owner: str) -> bool:
        """Force release a lock (for admin operations)."""
        if file_path in self._locks:
            lock = self._locks[file_path]
            if lock.owner == owner or owner == "admin":
                self._release_lock(file_path)
                return True
        return False
    
    def get_all_locks(self) -> Dict[str, FileLock]:
        """Get all current locks (for debugging)."""
        # Clean up expired locks first
        current_time = time.time()
        expired = [path for path, lock in self._locks.items() if current_time > lock.expires_at]
        for path in expired:
            self._release_lock(path)
        
        return self._locks.copy()
    
    def cleanup(self):
        """Clean up resources."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
        self._locks.clear()
        self._versions.clear()
        self._lock_semaphores.clear()


class FileLockedError(Exception):
    """Raised when a file cannot be locked."""
    pass


class FileConflictError(Exception):
    """Raised when a file conflict is detected."""
    pass


# Global lock manager instance
_lock_manager: Optional[FileLockManager] = None


def get_lock_manager() -> FileLockManager:
    """Get the global file lock manager instance."""
    global _lock_manager
    if _lock_manager is None:
        _lock_manager = FileLockManager()
    return _lock_manager


def cleanup_lock_manager():
    """Clean up the global lock manager."""
    global _lock_manager
    if _lock_manager:
        _lock_manager.cleanup()
        _lock_manager = None
