"""
Edit Versioning System

This module provides comprehensive versioning and aggregation capabilities for file edits
from both users and agents, with intelligent conflict resolution.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Union
from uuid import uuid4

from .atomic_operations import AtomicFileOperations, AtomicOperationResult

logger = logging.getLogger(__name__)


class EditSource(Enum):
    """Source of an edit operation."""
    USER = "user"
    AGENT = "agent"
    SYSTEM = "system"


class EditType(Enum):
    """Type of edit operation."""
    SEARCH_REPLACE = "search_replace"
    FULL_CONTENT = "full_content"
    INSERT = "insert"
    DELETE = "delete"


class ConflictResolutionStrategy(Enum):
    """Strategy for resolving edit conflicts."""
    USER_PRIORITY = "user_priority"
    AGENT_PRIORITY = "agent_priority"
    MERGE = "merge"
    MANUAL = "manual"


@dataclass
class EditOperation:
    """Represents a single edit operation."""
    id: str
    file_path: str
    source: EditSource
    edit_type: EditType
    timestamp: datetime
    owner: str
    description: str
    
    # For search/replace operations
    search_text: Optional[str] = None
    replace_text: Optional[str] = None
    
    # For full content operations
    content: Optional[str] = None
    
    # For insert/delete operations
    position: Optional[int] = None
    length: Optional[int] = None
    
    # Metadata
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        data = asdict(self)
        data['source'] = self.source.value
        data['edit_type'] = self.edit_type.value
        data['timestamp'] = self.timestamp.isoformat()
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'EditOperation':
        """Create from dictionary."""
        data = data.copy()
        data['source'] = EditSource(data['source'])
        data['edit_type'] = EditType(data['edit_type'])
        data['timestamp'] = datetime.fromisoformat(data['timestamp'])
        return cls(**data)


@dataclass
class EditVersion:
    """Represents a version of a file with associated edits."""
    version_id: str
    file_path: str
    content: str
    etag: str
    timestamp: datetime
    source: EditSource
    owner: str
    base_version_id: Optional[str] = None
    edit_operations: List[str] = None  # List of edit operation IDs
    conflicts: List[str] = None  # List of conflict IDs
    
    def __post_init__(self):
        if self.edit_operations is None:
            self.edit_operations = []
        if self.conflicts is None:
            self.conflicts = []
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        data = asdict(self)
        data['source'] = self.source.value
        data['timestamp'] = self.timestamp.isoformat()
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'EditVersion':
        """Create from dictionary."""
        data = data.copy()
        data['source'] = EditSource(data['source'])
        data['timestamp'] = datetime.fromisoformat(data['timestamp'])
        return cls(**data)


@dataclass
class EditConflict:
    """Represents a conflict between user and agent edits."""
    conflict_id: str
    file_path: str
    user_version_id: str
    agent_version_id: str
    timestamp: datetime
    resolution_strategy: ConflictResolutionStrategy
    resolved: bool = False
    resolved_version_id: Optional[str] = None
    resolution_notes: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        data = asdict(self)
        data['resolution_strategy'] = self.resolution_strategy.value
        data['timestamp'] = self.timestamp.isoformat()
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'EditConflict':
        """Create from dictionary."""
        data = data.copy()
        data['resolution_strategy'] = ConflictResolutionStrategy(data['resolution_strategy'])
        data['timestamp'] = datetime.fromisoformat(data['timestamp'])
        return cls(**data)


class EditVersionManager:
    """Manages edit versions and provides aggregation capabilities."""
    
    def __init__(self, workspace_root: Path, versions_dir: Optional[Path] = None):
        self.workspace_root = workspace_root
        self.versions_dir = versions_dir or (workspace_root / ".edit_versions")
        self.versions_dir.mkdir(exist_ok=True)
        
        self.atomic_ops = AtomicFileOperations(workspace_root)
        
        # In-memory caches
        self._edit_operations: Dict[str, EditOperation] = {}
        self._edit_versions: Dict[str, EditVersion] = {}
        self._edit_conflicts: Dict[str, EditConflict] = {}
        
        # Load existing data
        asyncio.create_task(self._load_existing_data())
    
    async def _load_existing_data(self):
        """Load existing edit data from storage."""
        try:
            await self._load_edit_operations()
            await self._load_edit_versions()
            await self._load_edit_conflicts()
            logger.info("Loaded existing edit version data")
        except Exception as e:
            logger.warning(f"Failed to load existing edit data: {e}")
    
    async def _load_edit_operations(self):
        """Load edit operations from storage."""
        operations_file = self.versions_dir / "edit_operations.json"
        if operations_file.exists():
            try:
                data = json.loads(operations_file.read_text())
                for op_data in data.get('operations', []):
                    op = EditOperation.from_dict(op_data)
                    self._edit_operations[op.id] = op
            except Exception as e:
                logger.error(f"Failed to load edit operations: {e}")
    
    async def _load_edit_versions(self):
        """Load edit versions from storage."""
        versions_file = self.versions_dir / "edit_versions.json"
        if versions_file.exists():
            try:
                data = json.loads(versions_file.read_text())
                for version_data in data.get('versions', []):
                    version = EditVersion.from_dict(version_data)
                    self._edit_versions[version.version_id] = version
            except Exception as e:
                logger.error(f"Failed to load edit versions: {e}")
    
    async def _load_edit_conflicts(self):
        """Load edit conflicts from storage."""
        conflicts_file = self.versions_dir / "edit_conflicts.json"
        if conflicts_file.exists():
            try:
                data = json.loads(conflicts_file.read_text())
                for conflict_data in data.get('conflicts', []):
                    conflict = EditConflict.from_dict(conflict_data)
                    self._edit_conflicts[conflict.conflict_id] = conflict
            except Exception as e:
                logger.error(f"Failed to load edit conflicts: {e}")
    
    async def _save_edit_operations(self):
        """Save edit operations to storage."""
        operations_file = self.versions_dir / "edit_operations.json"
        data = {
            'operations': [op.to_dict() for op in self._edit_operations.values()]
        }
        operations_file.write_text(json.dumps(data, indent=2))
    
    async def _save_edit_versions(self):
        """Save edit versions to storage."""
        versions_file = self.versions_dir / "edit_versions.json"
        data = {
            'versions': [version.to_dict() for version in self._edit_versions.values()]
        }
        versions_file.write_text(json.dumps(data, indent=2))
    
    async def _save_edit_conflicts(self):
        """Save edit conflicts to storage."""
        conflicts_file = self.versions_dir / "edit_conflicts.json"
        data = {
            'conflicts': [conflict.to_dict() for conflict in self._edit_conflicts.values()]
        }
        conflicts_file.write_text(json.dumps(data, indent=2))
    
    def _generate_etag(self, content: str) -> str:
        """Generate ETag for content."""
        return hashlib.sha256(content.encode('utf-8')).hexdigest()
    
    async def record_edit_operation(
        self,
        file_path: str,
        source: EditSource,
        edit_type: EditType,
        owner: str,
        description: str,
        **kwargs
    ) -> EditOperation:
        """Record a new edit operation."""
        operation = EditOperation(
            id=str(uuid4()),
            file_path=file_path,
            source=source,
            edit_type=edit_type,
            timestamp=datetime.now(timezone.utc),
            owner=owner,
            description=description,
            **kwargs
        )
        
        self._edit_operations[operation.id] = operation
        await self._save_edit_operations()
        
        logger.info(f"Recorded edit operation {operation.id} for {file_path} by {owner}")
        return operation
    
    async def create_edit_version(
        self,
        file_path: str,
        content: str,
        source: EditSource,
        owner: str,
        base_version_id: Optional[str] = None,
        edit_operation_ids: Optional[List[str]] = None
    ) -> EditVersion:
        """Create a new edit version."""
        version = EditVersion(
            version_id=str(uuid4()),
            file_path=file_path,
            content=content,
            etag=self._generate_etag(content),
            timestamp=datetime.now(timezone.utc),
            source=source,
            owner=owner,
            base_version_id=base_version_id,
            edit_operations=edit_operation_ids or []
        )
        
        self._edit_versions[version.version_id] = version
        await self._save_edit_versions()
        
        logger.info(f"Created edit version {version.version_id} for {file_path} by {owner}")
        return version
    
    async def get_latest_version(self, file_path: str, source: Optional[EditSource] = None) -> Optional[EditVersion]:
        """Get the latest version of a file, optionally filtered by source."""
        versions = [
            v for v in self._edit_versions.values()
            if v.file_path == file_path and (source is None or v.source == source)
        ]
        
        if not versions:
            return None
        
        return max(versions, key=lambda v: v.timestamp)
    
    async def get_versions_for_file(self, file_path: str) -> List[EditVersion]:
        """Get all versions for a specific file."""
        return [
            v for v in self._edit_versions.values()
            if v.file_path == file_path
        ]
    
    async def detect_conflicts(self, file_path: str) -> List[EditConflict]:
        """Detect conflicts between user and agent versions."""
        user_version = await self.get_latest_version(file_path, EditSource.USER)
        agent_version = await self.get_latest_version(file_path, EditSource.AGENT)
        
        conflicts = []
        
        if user_version and agent_version:
            # Check if there are actual conflicts
            if user_version.etag != agent_version.etag:
                # Look for existing unresolved conflicts
                existing_conflicts = [
                    c for c in self._edit_conflicts.values()
                    if c.file_path == file_path and not c.resolved
                ]
                
                if not existing_conflicts:
                    conflict = EditConflict(
                        conflict_id=str(uuid4()),
                        file_path=file_path,
                        user_version_id=user_version.version_id,
                        agent_version_id=agent_version.version_id,
                        timestamp=datetime.now(timezone.utc),
                        resolution_strategy=ConflictResolutionStrategy.MERGE
                    )
                    
                    self._edit_conflicts[conflict.conflict_id] = conflict
                    conflicts.append(conflict)
                    
                    # Update version conflict references
                    user_version.conflicts.append(conflict.conflict_id)
                    agent_version.conflicts.append(conflict.conflict_id)
                    
                    await self._save_edit_conflicts()
                    await self._save_edit_versions()
        
        return conflicts
    
    async def aggregate_edits(
        self,
        file_path: str,
        strategy: ConflictResolutionStrategy = ConflictResolutionStrategy.MERGE
    ) -> Tuple[str, List[EditConflict]]:
        """
        Aggregate user and agent edits for a file.
        
        Returns:
            Tuple of (aggregated_content, conflicts_requiring_manual_resolution)
        """
        user_version = await self.get_latest_version(file_path, EditSource.USER)
        agent_version = await self.get_latest_version(file_path, EditSource.AGENT)
        
        if not user_version and not agent_version:
            # No versions exist, read current file
            try:
                content, etag, _ = await self.atomic_ops.atomic_read(file_path, "version_manager")
                return content, []
            except FileNotFoundError:
                return "", []
        
        if not user_version:
            return agent_version.content, []
        
        if not agent_version:
            return user_version.content, []
        
        # Both versions exist - check for conflicts
        conflicts = await self.detect_conflicts(file_path)
        unresolved_conflicts = [c for c in conflicts if not c.resolved]
        
        if not unresolved_conflicts:
            # No conflicts, return the most recent version
            latest_version = max([user_version, agent_version], key=lambda v: v.timestamp)
            return latest_version.content, []
        
        # Handle conflicts based on strategy
        if strategy == ConflictResolutionStrategy.USER_PRIORITY:
            return user_version.content, []
        
        if strategy == ConflictResolutionStrategy.AGENT_PRIORITY:
            return agent_version.content, []
        
        if strategy == ConflictResolutionStrategy.MERGE:
            return await self._merge_versions(user_version, agent_version)
        
        # Manual resolution required
        return "", unresolved_conflicts
    
    async def _merge_versions(self, user_version: EditVersion, agent_version: EditVersion) -> Tuple[str, List[EditConflict]]:
        """Attempt to automatically merge two versions."""
        user_content = user_version.content
        agent_content = agent_version.content
        
        # Simple merge strategy: try to apply agent edits to user content
        # This is a basic implementation - more sophisticated merging could be added
        
        # For now, if the files are too different, we'll require manual resolution
        if self._content_similarity(user_content, agent_content) < 0.8:
            conflict = EditConflict(
                conflict_id=str(uuid4()),
                file_path=user_version.file_path,
                user_version_id=user_version.version_id,
                agent_version_id=agent_version.version_id,
                timestamp=datetime.now(timezone.utc),
                resolution_strategy=ConflictResolutionStrategy.MANUAL
            )
            
            self._edit_conflicts[conflict.conflict_id] = conflict
            await self._save_edit_conflicts()
            
            return "", [conflict]
        
        # Try to merge by applying agent edits to user content
        try:
            merged_content = await self._apply_agent_edits_to_user_content(user_version, agent_version)
            return merged_content, []
        except Exception as e:
            logger.warning(f"Failed to merge versions automatically: {e}")
            
            conflict = EditConflict(
                conflict_id=str(uuid4()),
                file_path=user_version.file_path,
                user_version_id=user_version.version_id,
                agent_version_id=agent_version.version_id,
                timestamp=datetime.now(timezone.utc),
                resolution_strategy=ConflictResolutionStrategy.MANUAL
            )
            
            self._edit_conflicts[conflict.conflict_id] = conflict
            await self._save_edit_conflicts()
            
            return "", [conflict]
    
    def _content_similarity(self, content1: str, content2: str) -> float:
        """Calculate similarity between two content strings."""
        if not content1 and not content2:
            return 1.0
        if not content1 or not content2:
            return 0.0
        
        # Simple similarity based on common lines
        lines1 = set(content1.splitlines())
        lines2 = set(content2.splitlines())
        
        if not lines1 and not lines2:
            return 1.0
        
        intersection = len(lines1.intersection(lines2))
        union = len(lines1.union(lines2))
        
        return intersection / union if union > 0 else 0.0
    
    async def _apply_agent_edits_to_user_content(self, user_version: EditVersion, agent_version: EditVersion) -> str:
        """Apply agent edits to user content."""
        user_content = user_version.content
        agent_content = agent_version.content
        
        # Get agent edit operations
        agent_operations = [
            op for op in self._edit_operations.values()
            if op.id in agent_version.edit_operations
        ]
        
        # Apply each agent operation to user content
        result = user_content
        for operation in agent_operations:
            if operation.edit_type == EditType.SEARCH_REPLACE:
                if operation.search_text and operation.replace_text:
                    result = result.replace(operation.search_text, operation.replace_text, 1)
            elif operation.edit_type == EditType.FULL_CONTENT:
                # For full content, we need to be more careful
                # This might indicate a major conflict
                raise ValueError("Full content edit conflicts require manual resolution")
        
        return result
    
    async def resolve_conflict(
        self,
        conflict_id: str,
        resolution_content: str,
        resolution_notes: Optional[str] = None
    ) -> EditVersion:
        """Manually resolve a conflict."""
        if conflict_id not in self._edit_conflicts:
            raise ValueError(f"Conflict {conflict_id} not found")
        
        conflict = self._edit_conflicts[conflict_id]
        conflict.resolved = True
        conflict.resolution_notes = resolution_notes
        
        # Create resolved version
        resolved_version = await self.create_edit_version(
            file_path=conflict.file_path,
            content=resolution_content,
            source=EditSource.SYSTEM,
            owner="conflict_resolution",
            base_version_id=conflict.user_version_id
        )
        
        conflict.resolved_version_id = resolved_version.version_id
        
        await self._save_edit_conflicts()
        
        logger.info(f"Resolved conflict {conflict_id} with version {resolved_version.version_id}")
        return resolved_version
    
    async def get_file_history(self, file_path: str) -> List[Dict[str, Any]]:
        """Get complete history for a file."""
        versions = await self.get_versions_for_file(file_path)
        versions.sort(key=lambda v: v.timestamp)
        
        history = []
        for version in versions:
            history_entry = {
                'version_id': version.version_id,
                'timestamp': version.timestamp.isoformat(),
                'source': version.source.value,
                'owner': version.owner,
                'etag': version.etag,
                'conflicts': version.conflicts,
                'edit_operations': version.edit_operations
            }
            history.append(history_entry)
        
        return history
    
    async def cleanup_old_versions(self, max_versions_per_file: int = 50):
        """Clean up old versions to prevent storage bloat."""
        files = set(v.file_path for v in self._edit_versions.values())
        
        for file_path in files:
            versions = await self.get_versions_for_file(file_path)
            if len(versions) > max_versions_per_file:
                # Keep the most recent versions
                versions.sort(key=lambda v: v.timestamp, reverse=True)
                versions_to_keep = versions[:max_versions_per_file]
                versions_to_remove = versions[max_versions_per_file:]
                
                for version in versions_to_remove:
                    del self._edit_versions[version.version_id]
                
                logger.info(f"Cleaned up {len(versions_to_remove)} old versions for {file_path}")
        
        await self._save_edit_versions()
