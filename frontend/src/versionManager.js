/**
 * Version Management and Conflict Resolution for the Agent Context Work Trial
 * 
 * This module provides functionality to:
 * 1. Save both user and agent versions of file edits
 * 2. Aggregate edits together intelligently
 * 3. Handle conflict resolution between user and agent changes
 */

class VersionManager {
    constructor(backendUrl = 'http://localhost:8000') {
        this.backendUrl = backendUrl;
        this.apiBase = `${backendUrl}/api/versions`;
    }

    /**
     * Record an unsaved user edit (for real-time collaboration)
     * @param {string} filePath - Path to the file being edited
     * @param {string} content - Current content of the file
     * @param {string} owner - User identifier (default: 'user')
     * @param {string} description - Description of the edit
     */
    async recordUnsavedUserEdit(filePath, content, owner = 'user', description = 'Unsaved user edit') {
        try {
            const response = await fetch(`${this.apiBase}/files/${encodeURIComponent(filePath)}/unsaved-user-edit`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    content,
                    owner,
                    description
                })
            });

            if (!response.ok) {
                throw new Error(`Failed to record unsaved user edit: ${response.statusText}`);
            }

            const result = await response.json();
            console.log('Unsaved user edit recorded:', result);
            return result;
        } catch (error) {
            console.error('Error recording unsaved user edit:', error);
            throw error;
        }
    }

    /**
     * Record a user edit when the user saves a file
     * @param {string} filePath - Path to the file being edited
     * @param {string} content - Current content of the file
     * @param {string} owner - User identifier (default: 'user')
     * @param {string} description - Description of the edit
     */
    async recordUserEdit(filePath, content, owner = 'user', description = 'User edit') {
        try {
            const response = await fetch(`${this.apiBase}/files/${encodeURIComponent(filePath)}/user-edit`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    content,
                    owner,
                    description
                })
            });

            if (!response.ok) {
                throw new Error(`Failed to record user edit: ${response.statusText}`);
            }

            const result = await response.json();
            console.log('User edit recorded:', result);
            return result;
        } catch (error) {
            console.error('Error recording user edit:', error);
            throw error;
        }
    }

    /**
     * Get all versions for a specific file
     * @param {string} filePath - Path to the file
     * @returns {Array} Array of version objects
     */
    async getFileVersions(filePath) {
        try {
            const response = await fetch(`${this.apiBase}/versions/${encodeURIComponent(filePath)}`);
            
            if (!response.ok) {
                throw new Error(`Failed to get file versions: ${response.statusText}`);
            }

            return await response.json();
        } catch (error) {
            console.error('Error getting file versions:', error);
            throw error;
        }
    }

    /**
     * Get the latest version of a file, optionally filtered by source
     * @param {string} filePath - Path to the file
     * @param {string} source - Optional source filter ('user', 'agent', 'system')
     * @returns {Object} Latest version object
     */
    async getLatestVersion(filePath, source = null) {
        try {
            const url = new URL(`${this.apiBase}/versions/${encodeURIComponent(filePath)}/latest`);
            if (source) {
                url.searchParams.set('source', source);
            }

            const response = await fetch(url);
            
            if (!response.ok) {
                throw new Error(`Failed to get latest version: ${response.statusText}`);
            }

            return await response.json();
        } catch (error) {
            console.error('Error getting latest version:', error);
            throw error;
        }
    }

    /**
     * Aggregate user and agent edits for a file
     * @param {string} filePath - Path to the file
     * @param {string} strategy - Aggregation strategy ('merge', 'user_priority', 'agent_priority', 'manual')
     * @returns {Object} Aggregation result with content and conflicts
     */
    async aggregateEdits(filePath, strategy = 'merge') {
        try {
            const response = await fetch(`${this.apiBase}/aggregate`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    file_path: filePath,
                    strategy
                })
            });

            if (!response.ok) {
                throw new Error(`Failed to aggregate edits: ${response.statusText}`);
            }

            const result = await response.json();
            console.log('Edit aggregation result:', result);
            return result;
        } catch (error) {
            console.error('Error aggregating edits:', error);
            throw error;
        }
    }

    /**
     * Get all conflicts for files
     * @param {string} filePath - Optional file path filter
     * @param {boolean} resolved - Optional resolution status filter
     * @returns {Array} Array of conflict objects
     */
    async getConflicts(filePath = null, resolved = null) {
        try {
            const url = new URL(`${this.apiBase}/conflicts`);
            if (filePath) {
                url.searchParams.set('file_path', filePath);
            }
            if (resolved !== null) {
                url.searchParams.set('resolved', resolved.toString());
            }

            const response = await fetch(url);
            
            if (!response.ok) {
                throw new Error(`Failed to get conflicts: ${response.statusText}`);
            }

            return await response.json();
        } catch (error) {
            console.error('Error getting conflicts:', error);
            throw error;
        }
    }

    /**
     * Manually resolve a conflict
     * @param {string} conflictId - ID of the conflict to resolve
     * @param {string} resolutionContent - Content to use for resolution
     * @param {string} resolutionNotes - Optional notes about the resolution
     * @returns {Object} Resolved version object
     */
    async resolveConflict(conflictId, resolutionContent, resolutionNotes = null) {
        try {
            const response = await fetch(`${this.apiBase}/conflicts/${conflictId}/resolve`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    resolution_content: resolutionContent,
                    resolution_notes: resolutionNotes
                })
            });

            if (!response.ok) {
                throw new Error(`Failed to resolve conflict: ${response.statusText}`);
            }

            const result = await response.json();
            console.log('Conflict resolved:', result);
            return result;
        } catch (error) {
            console.error('Error resolving conflict:', error);
            throw error;
        }
    }

    /**
     * Get complete history for a file
     * @param {string} filePath - Path to the file
     * @returns {Object} File history object
     */
    async getFileHistory(filePath) {
        try {
            const response = await fetch(`${this.apiBase}/history/${encodeURIComponent(filePath)}`);
            
            if (!response.ok) {
                throw new Error(`Failed to get file history: ${response.statusText}`);
            }

            return await response.json();
        } catch (error) {
            console.error('Error getting file history:', error);
            throw error;
        }
    }

    /**
     * Get unsaved edits for a file
     * @param {string} filePath - Path to the file
     * @returns {Object} Object containing unsaved operations
     */
    async getUnsavedEdits(filePath) {
        try {
            const response = await fetch(`${this.apiBase}/files/${encodeURIComponent(filePath)}/unsaved-edits`);
            
            if (!response.ok) {
                throw new Error(`Failed to get unsaved edits: ${response.statusText}`);
            }

            return await response.json();
        } catch (error) {
            console.error('Error getting unsaved edits:', error);
            throw error;
        }
    }

    /**
     * Clear unsaved edits for a file (when user saves or discards changes)
     * @param {string} filePath - Path to the file
     */
    async clearUnsavedEdits(filePath) {
        try {
            const response = await fetch(`${this.apiBase}/files/${encodeURIComponent(filePath)}/unsaved-edits`, {
                method: 'DELETE'
            });

            if (!response.ok) {
                throw new Error(`Failed to clear unsaved edits: ${response.statusText}`);
            }

            const result = await response.json();
            console.log('Unsaved edits cleared:', result);
            return result;
        } catch (error) {
            console.error('Error clearing unsaved edits:', error);
            throw error;
        }
    }

    /**
     * Save current file state before agent operations to prevent data loss
     * @param {string} filePath - Path to the file
     * @param {string} content - Current content of the file
     * @param {string} owner - User identifier (default: 'user')
     * @param {string} description - Description of the save operation
     */
    async saveBeforeAgentOperation(filePath, content, owner = 'user', description = 'Save before agent operation') {
        try {
            const response = await fetch(`${this.apiBase}/files/${encodeURIComponent(filePath)}/save-before-agent`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    content,
                    owner,
                    description
                })
            });

            if (!response.ok) {
                throw new Error(`Failed to save before agent operation: ${response.statusText}`);
            }

            const result = await response.json();
            console.log('File saved before agent operation:', result);
            return result;
        } catch (error) {
            console.error('Error saving before agent operation:', error);
            throw error;
        }
    }

    /**
     * Restore file from a backup version
     * @param {string} filePath - Path to the file
     * @param {string} backupVersionId - ID of the backup version to restore
     */
    async restoreFromBackup(filePath, backupVersionId) {
        try {
            const response = await fetch(`${this.apiBase}/files/${encodeURIComponent(filePath)}/restore-from-backup`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    backup_version_id: backupVersionId
                })
            });

            if (!response.ok) {
                throw new Error(`Failed to restore from backup: ${response.statusText}`);
            }

            const result = await response.json();
            console.log('File restored from backup:', result);
            return result;
        } catch (error) {
            console.error('Error restoring from backup:', error);
            throw error;
        }
    }

    /**
     * Clean up old versions
     * @param {number} maxVersionsPerFile - Maximum versions to keep per file
     */
    async cleanupOldVersions(maxVersionsPerFile = 50) {
        try {
            const response = await fetch(`${this.apiBase}/cleanup?max_versions_per_file=${maxVersionsPerFile}`, {
                method: 'POST'
            });

            if (!response.ok) {
                throw new Error(`Failed to cleanup old versions: ${response.statusText}`);
            }

            const result = await response.json();
            console.log('Cleanup completed:', result);
            return result;
        } catch (error) {
            console.error('Error cleaning up old versions:', error);
            throw error;
        }
    }
}

/**
 * Conflict Resolution UI Component
 * Provides a user interface for resolving conflicts between user and agent edits
 */
class ConflictResolutionUI {
    constructor(versionManager, containerId) {
        this.versionManager = versionManager;
        this.container = document.getElementById(containerId);
        this.currentConflicts = [];
    }

    /**
     * Display conflicts for a file
     * @param {string} filePath - Path to the file with conflicts
     */
    async displayConflicts(filePath) {
        try {
            const conflicts = await this.versionManager.getConflicts(filePath, false);
            this.currentConflicts = conflicts;
            
            if (conflicts.length === 0) {
                this.container.innerHTML = '<p>No conflicts found.</p>';
                return;
            }

            this.renderConflictList(conflicts);
        } catch (error) {
            console.error('Error displaying conflicts:', error);
            this.container.innerHTML = `<p class="error">Error loading conflicts: ${error.message}</p>`;
        }
    }

    /**
     * Render the list of conflicts
     * @param {Array} conflicts - Array of conflict objects
     */
    renderConflictList(conflicts) {
        const html = `
            <div class="conflicts-container">
                <h3>Conflicts Requiring Resolution</h3>
                ${conflicts.map(conflict => this.renderConflictItem(conflict)).join('')}
            </div>
        `;
        
        this.container.innerHTML = html;
    }

    /**
     * Render a single conflict item
     * @param {Object} conflict - Conflict object
     * @returns {string} HTML string for the conflict item
     */
    renderConflictItem(conflict) {
        return `
            <div class="conflict-item" data-conflict-id="${conflict.conflict_id}">
                <div class="conflict-header">
                    <h4>Conflict in ${conflict.file_path}</h4>
                    <span class="conflict-timestamp">${new Date(conflict.timestamp).toLocaleString()}</span>
                </div>
                <div class="conflict-actions">
                    <button class="btn btn-primary" onclick="conflictUI.showConflictDetails('${conflict.conflict_id}')">
                        View Details
                    </button>
                    <button class="btn btn-success" onclick="conflictUI.resolveWithStrategy('${conflict.conflict_id}', 'user_priority')">
                        Use User Version
                    </button>
                    <button class="btn btn-warning" onclick="conflictUI.resolveWithStrategy('${conflict.conflict_id}', 'agent_priority')">
                        Use Agent Version
                    </button>
                </div>
            </div>
        `;
    }

    /**
     * Show detailed conflict resolution interface
     * @param {string} conflictId - ID of the conflict to show details for
     */
    async showConflictDetails(conflictId) {
        const conflict = this.currentConflicts.find(c => c.conflict_id === conflictId);
        if (!conflict) {
            console.error('Conflict not found:', conflictId);
            return;
        }

        try {
            // Get the actual versions
            const userVersion = await this.versionManager.getLatestVersion(conflict.file_path, 'user');
            const agentVersion = await this.versionManager.getLatestVersion(conflict.file_path, 'agent');

            const html = `
                <div class="conflict-details" data-conflict-id="${conflictId}">
                    <h4>Resolve Conflict: ${conflict.file_path}</h4>
                    <div class="version-comparison">
                        <div class="version-panel user-version">
                            <h5>User Version</h5>
                            <textarea readonly class="version-content">${userVersion?.content || 'No user version'}</textarea>
                            <div class="version-meta">
                                <small>Modified: ${userVersion ? new Date(userVersion.timestamp).toLocaleString() : 'Never'}</small>
                            </div>
                        </div>
                        <div class="version-panel agent-version">
                            <h5>Agent Version</h5>
                            <textarea readonly class="version-content">${agentVersion?.content || 'No agent version'}</textarea>
                            <div class="version-meta">
                                <small>Modified: ${agentVersion ? new Date(agentVersion.timestamp).toLocaleString() : 'Never'}</small>
                            </div>
                        </div>
                    </div>
                    <div class="resolution-panel">
                        <h5>Resolution</h5>
                        <textarea id="resolution-content-${conflictId}" class="resolution-content" placeholder="Enter the final content to resolve the conflict...">${userVersion?.content || ''}</textarea>
                        <textarea id="resolution-notes-${conflictId}" class="resolution-notes" placeholder="Optional notes about this resolution..."></textarea>
                        <div class="resolution-actions">
                            <button class="btn btn-success" onclick="conflictUI.resolveConflict('${conflictId}')">
                                Resolve Conflict
                            </button>
                            <button class="btn btn-secondary" onclick="conflictUI.cancelResolution()">
                                Cancel
                            </button>
                        </div>
                    </div>
                </div>
            `;

            this.container.innerHTML = html;
        } catch (error) {
            console.error('Error showing conflict details:', error);
            this.container.innerHTML = `<p class="error">Error loading conflict details: ${error.message}</p>`;
        }
    }

    /**
     * Resolve conflict with a specific strategy
     * @param {string} conflictId - ID of the conflict
     * @param {string} strategy - Resolution strategy
     */
    async resolveWithStrategy(conflictId, strategy) {
        const conflict = this.currentConflicts.find(c => c.conflict_id === conflictId);
        if (!conflict) {
            console.error('Conflict not found:', conflictId);
            return;
        }

        try {
            let resolutionContent;
            
            if (strategy === 'user_priority') {
                const userVersion = await this.versionManager.getLatestVersion(conflict.file_path, 'user');
                resolutionContent = userVersion?.content || '';
            } else if (strategy === 'agent_priority') {
                const agentVersion = await this.versionManager.getLatestVersion(conflict.file_path, 'agent');
                resolutionContent = agentVersion?.content || '';
            } else {
                console.error('Unknown strategy:', strategy);
                return;
            }

            const result = await this.versionManager.resolveConflict(
                conflictId, 
                resolutionContent, 
                `Resolved using ${strategy} strategy`
            );

            console.log('Conflict resolved:', result);
            alert('Conflict resolved successfully!');
            
            // Refresh the conflicts list
            await this.displayConflicts(conflict.file_path);
        } catch (error) {
            console.error('Error resolving conflict:', error);
            alert(`Error resolving conflict: ${error.message}`);
        }
    }

    /**
     * Resolve conflict with custom content
     * @param {string} conflictId - ID of the conflict
     */
    async resolveConflict(conflictId) {
        const resolutionContent = document.getElementById(`resolution-content-${conflictId}`)?.value;
        const resolutionNotes = document.getElementById(`resolution-notes-${conflictId}`)?.value;

        if (!resolutionContent) {
            alert('Please enter resolution content');
            return;
        }

        try {
            const result = await this.versionManager.resolveConflict(
                conflictId, 
                resolutionContent, 
                resolutionNotes
            );

            console.log('Conflict resolved:', result);
            alert('Conflict resolved successfully!');
            
            // Refresh the conflicts list
            const conflict = this.currentConflicts.find(c => c.conflict_id === conflictId);
            if (conflict) {
                await this.displayConflicts(conflict.file_path);
            }
        } catch (error) {
            console.error('Error resolving conflict:', error);
            alert(`Error resolving conflict: ${error.message}`);
        }
    }

    /**
     * Cancel conflict resolution and return to conflict list
     */
    cancelResolution() {
        const conflictId = this.container.querySelector('.conflict-details')?.dataset.conflictId;
        if (conflictId) {
            const conflict = this.currentConflicts.find(c => c.conflict_id === conflictId);
            if (conflict) {
                this.displayConflicts(conflict.file_path);
            }
        }
    }
}

// Export for use in other modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { VersionManager, ConflictResolutionUI };
}
