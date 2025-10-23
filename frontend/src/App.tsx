import React, { useEffect, useMemo, useRef, useState } from 'react'
import {
  AssistantRuntimeProvider,
  ComposerPrimitive,
  MessagePrimitive,
  ThreadPrimitive,
  useLocalRuntime,
} from '@assistant-ui/react'
import type { ChatModelAdapter, ChatModelRunResult } from '@assistant-ui/react'
import Editor, { type OnChange } from '@monaco-editor/react'
import './App.css'

type FileResponse = {
  path: string
  content: string
}

type FileReadResponse = {
  path: string
  content: string
  etag: string
}

type ModelMessage = ModelRequest | ModelResponse

type ChatResponse = {
  reply: string
  editor_path?: string | null
  editor_content?: string | null
  usage?: Record<string, number>
  messages?: ModelMessage[]
}

type ModelRequest = {
  kind: 'request'
  parts: ModelRequestPart[]
  instructions?: string | null
}

type ModelResponse = {
  kind: 'response'
  parts: ModelResponsePart[]
  usage: any
  model_name?: string | null
  timestamp: string
}

type ModelRequestPart =
  | SystemPromptPart
  | UserPromptPart
  | ToolReturnPart
  | RetryPromptPart

type ModelResponsePart =
  | TextPart
  | ToolCallPart
  | ThinkingPart

type SystemPromptPart = {
  part_kind: 'system-prompt'
  content: string
  timestamp: string
}

type UserPromptPart = {
  part_kind: 'user-prompt'
  content: string | any[]
  timestamp: string
}

type ToolReturnPart = {
  part_kind: 'tool-return'
  tool_name: string
  content: any
  tool_call_id: string
  timestamp: string
}

type RetryPromptPart = {
  part_kind: 'retry-prompt'
  content: any
  tool_call_id: string
  timestamp: string
}

type TextPart = {
  part_kind: 'text'
  content: string
}

type ToolCallPart = {
  part_kind: 'tool-call'
  tool_name: string
  args: string | Record<string, any> | null
  tool_call_id: string
}

type ThinkingPart = {
  part_kind: 'thinking'
  content: string
}

const formatToolArgs = (args: string | Record<string, any> | null): string => {
  if (!args) return '{}'
  if (typeof args === 'string') {
    try {
      return JSON.stringify(JSON.parse(args), null, 2)
    } catch {
      return args
    }
  }
  return JSON.stringify(args, null, 2)
}

const MessagePartDisplay = ({ part }: { part: ModelRequestPart | ModelResponsePart }) => {
  switch (part.part_kind) {
    case 'user-prompt':
      const content = typeof part.content === 'string' ? part.content : JSON.stringify(part.content)
      const cleanContent = content.replace(/^\[User is viewing: [^\]]+\]\n/, '')
      return (
        <div className="message-bubble message-bubble--user">
          <div className="message-content">{cleanContent}</div>
        </div>
      )

    case 'text':
      return (
        <div className="message-bubble message-bubble--assistant">
          <div className="message-content">{part.content}</div>
        </div>
      )

    case 'tool-call':
      return (
        <div className="message-tool-call">
          <div className="tool-header">
            <span className="tool-icon">🔧</span>
            <span className="tool-name">{part.tool_name}</span>
          </div>
          <pre className="tool-args">{formatToolArgs(part.args)}</pre>
        </div>
      )

    case 'tool-return':
      const returnContent = typeof part.content === 'string'
        ? part.content
        : JSON.stringify(part.content, null, 2)
      return (
        <div className="message-tool-return">
          <div className="tool-header">
            <span className="tool-icon">✓</span>
            <span className="tool-name">{part.tool_name} result</span>
          </div>
          <pre className="tool-result">{returnContent}</pre>
        </div>
      )

    case 'thinking':
      return (
        <div className="message-thinking">
          <div className="thinking-header">
            <span className="thinking-icon">💭</span>
            <span>Thinking...</span>
          </div>
          <div className="thinking-content">{part.content}</div>
        </div>
      )

    case 'system-prompt':
    case 'retry-prompt':
      return null

    default:
      return null
  }
}

const CustomMessage = ({ message }: { message: ModelMessage }) => {
  if (message.kind === 'request') {
    return (
      <>
        {message.parts.map((part, idx) => (
          <MessagePartDisplay key={idx} part={part} />
        ))}
      </>
    )
  } else {
    return (
      <>
        {message.parts.map((part, idx) => (
          <MessagePartDisplay key={idx} part={part} />
        ))}
      </>
    )
  }
}

const Composer = () => (
  <ComposerPrimitive.Root className="composer">
    <ComposerPrimitive.Input
      className="composer-input"
      placeholder="Ask the agent to read or edit a file"
    />
    <ComposerPrimitive.Send className="composer-send">
      Send
    </ComposerPrimitive.Send>
  </ComposerPrimitive.Root>
)

const apiBase = import.meta.env.VITE_BACKEND_URL ?? 'http://localhost:8000'
const filesBase = `${apiBase}/files`
const DEFAULT_FILE_PATH = 'files/__init__.py'
const EDITOR_LANGUAGE = 'python'
const POLL_MS = 5000

interface FileTreeNode {
  name: string
  path: string
  isFile: boolean
  children: FileTreeNode[]
}

function buildFileTree(files: string[]): FileTreeNode[] {
  const root: FileTreeNode[] = []

  files.forEach(filePath => {
    const parts = filePath.split('/')
    let currentLevel = root
    let currentPath = ''

    parts.forEach((part, index) => {
      currentPath = currentPath ? `${currentPath}/${part}` : part
      const isFile = index === parts.length - 1

      let existingNode = currentLevel.find(node => node.name === part)

      if (!existingNode) {
        existingNode = {
          name: part,
          path: currentPath,
          isFile,
          children: []
        }
        currentLevel.push(existingNode)
      }

      currentLevel = existingNode.children
    })
  })

  return root
}

const FileTreeItem = ({
  node,
  currentFile,
  onFileClick,
  depth = 0
}: {
  node: FileTreeNode
  currentFile: string
  onFileClick: (path: string) => void
  depth?: number
}) => {
  const containsCurrentFile = React.useMemo(() => {
    if (node.isFile) return false
    return currentFile.startsWith(node.path + '/')
  }, [node, currentFile])

  const [isOpen, setIsOpen] = React.useState(containsCurrentFile)

  React.useEffect(() => {
    if (containsCurrentFile) {
      setIsOpen(true)
    }
  }, [containsCurrentFile])

  if (node.isFile) {
    return (
      <button
        className={`file-tree-item ${node.path === currentFile ? 'file-tree-item--active' : ''}`}
        style={{ paddingLeft: `${depth * 12 + 8}px` }}
        onClick={() => onFileClick(node.path)}
        title={node.path}
      >
        <span className="file-icon">📄</span>
        <span className="file-tree-name">{node.name}</span>
      </button>
    )
  }

  return (
    <div className="file-tree-folder">
      <button
        className="file-tree-item file-tree-folder-name"
        style={{ paddingLeft: `${depth * 12 + 8}px` }}
        onClick={() => setIsOpen(!isOpen)}
      >
        <span className="folder-icon">{isOpen ? '📂' : '📁'}</span>
        <span className="file-tree-name">{node.name}</span>
      </button>
      {isOpen && node.children.map(child => (
        <FileTreeItem
          key={child.path}
          node={child}
          currentFile={currentFile}
          onFileClick={onFileClick}
          depth={depth + 1}
        />
      ))}
    </div>
  )
}

async function readFromStore(path: string): Promise<FileReadResponse> {
  const resp = await fetch(`${filesBase}/read`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path }),
  })
  if (!resp.ok) throw new Error(await resp.text())
  return resp.json()
}

async function writeToStore(path: string, content: string): Promise<FileReadResponse> {
  const resp = await fetch(`${filesBase}/write`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path, content }),
  })
  if (!resp.ok) throw new Error(await resp.text())
  return resp.json()
}

async function listFiles(): Promise<string[]> {
  const resp = await fetch(`${filesBase}/list`)
  if (!resp.ok) throw new Error(await resp.text())
  const data = await resp.json()
  return data.files || []
}

function App() {
  const [conversationId] = useState(() => crypto.randomUUID())
  const [files, setFiles] = useState<string[]>([])
  const [currentFile, setCurrentFile] = useState<string>(DEFAULT_FILE_PATH)
  const [fileContents, setFileContents] = useState<Record<string, string>>({})
  const [remoteEtags, setRemoteEtags] = useState<Record<string, string>>({})
  const [dirty, setDirty] = useState<boolean>(false)
  const [saving, setSaving] = useState<boolean>(false)
  const [error, setError] = useState<string>('')
  const [messages, setMessages] = useState<ModelMessage[]>([])
  const [autoSaveStatus, setAutoSaveStatus] = useState<string>('')

  const editorRef = useRef<any>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const dirtyRef = useRef(dirty)
  const autoSaveTimeoutRef = useRef<NodeJS.Timeout | null>(null)
  useEffect(() => { dirtyRef.current = dirty }, [dirty])

  const etagRef = useRef(remoteEtags)
  useEffect(() => { etagRef.current = remoteEtags }, [remoteEtags])

  const onSaveRef = useRef<() => void>()
  const onReloadRef = useRef<() => void>()

  const onSave = async () => {
    setSaving(true)
    setError('')
    try {
      const content = editorRef.current?.getValue() ?? fileContents[currentFile] ?? ''
      const data = await writeToStore(currentFile, content)
      setRemoteEtags(prev => ({ ...prev, [data.path]: data.etag }))
      setDirty(false)
    } catch (e: any) {
      setError(e?.message ?? 'Save failed.')
    } finally {
      setSaving(false)
    }
  }

  const autoSave = async () => {
    if (!dirtyRef.current) return
    
    try {
      setAutoSaveStatus('Auto-saving...')
      const content = editorRef.current?.getValue() ?? fileContents[currentFile] ?? ''
      const data = await writeToStore(currentFile, content)
      setRemoteEtags(prev => ({ ...prev, [data.path]: data.etag }))
      setDirty(false)
      setAutoSaveStatus('Auto-saved')
      setTimeout(() => setAutoSaveStatus(''), 2000)
    } catch (e: any) {
      setAutoSaveStatus('Auto-save failed')
      setTimeout(() => setAutoSaveStatus(''), 3000)
    }
  }

  const onReloadHandler = async () => {
    try {
      const data = await readFromStore(currentFile)
      setFileContents(prev => ({ ...prev, [data.path]: data.content }))
      setRemoteEtags(prev => ({ ...prev, [data.path]: data.etag }))
      setDirty(false)
      setError('')
    } catch (e: any) {
      setError(e?.message ?? 'Reload failed.')
    }
  }

  useEffect(() => {
    onSaveRef.current = onSave
    onReloadRef.current = onReloadHandler
  })

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 's') {
        e.preventDefault()
        if (dirtyRef.current && onSaveRef.current) {
          onSaveRef.current()
        }
      }
      if ((e.metaKey || e.ctrlKey) && e.key === 'r') {
        e.preventDefault()
        if (onReloadRef.current) {
          onReloadRef.current()
        }
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => {
      window.removeEventListener('keydown', handleKeyDown)
      // Cleanup auto-save timeout
      if (autoSaveTimeoutRef.current) {
        clearTimeout(autoSaveTimeoutRef.current)
      }
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    const loadFiles = async () => {
      try {
        const fileList = await listFiles()
        if (!cancelled) {
          setFiles(fileList)
        }
      } catch (e) {
        console.error('Failed to load file list:', e)
      }
    }
    loadFiles()
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    let cancelled = false
    const loadFile = async () => {
      try {
        const data = await readFromStore(DEFAULT_FILE_PATH)
        if (!cancelled) {
          setFileContents(prev => ({ ...prev, [data.path]: data.content }))
          setRemoteEtags(prev => ({ ...prev, [data.path]: data.etag }))
          setCurrentFile(data.path)
          setError('')
        }
      } catch (e) {
        setError('Failed to load initial file.')
      }
    }
    loadFile()
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    let cancelled = false
    const id = setInterval(async () => {
      const ctrl = new AbortController()
      try {
        const fileList = await listFiles()
        if (!cancelled) setFiles(fileList)

        const data = await readFromStore(currentFile)
        const currentEtag = etagRef.current[currentFile]
        if (data.etag !== currentEtag && !dirtyRef.current && !cancelled) {
          setFileContents(prev => ({ ...prev, [data.path]: data.content }))
          setRemoteEtags(prev => ({ ...prev, [data.path]: data.etag }))
        }
      } catch {
        /* ignore polling errors */
      } finally {
        ctrl.abort()
      }
    }, POLL_MS)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [currentFile])

  const onChange: OnChange = (value) => {
    if (value !== undefined) {
      setFileContents(prev => ({ ...prev, [currentFile]: value }))
      setDirty(true)
      
      // Clear existing auto-save timeout
      if (autoSaveTimeoutRef.current) {
        clearTimeout(autoSaveTimeoutRef.current)
      }
      
      // Set new auto-save timeout (1 second after user stops typing)
      autoSaveTimeoutRef.current = setTimeout(() => {
        autoSave()
      }, 1000)
    }
  }

  const switchFile = async (filePath: string) => {
    if (filePath === currentFile) return
    if (dirtyRef.current) {
      console.warn('Switching files discards unsaved changes.')
    }

    if (!fileContents[filePath]) {
      try {
        const data = await readFromStore(filePath)
        setFileContents(prev => ({ ...prev, [data.path]: data.content }))
        setRemoteEtags(prev => ({ ...prev, [data.path]: data.etag }))
      } catch (e: any) {
        setError(e?.message ?? 'Failed to load file.')
        return
      }
    }

    setCurrentFile(filePath)
    setDirty(false)
    setError('')
  }

  const getLanguageFromPath = (path: string): string => {
    const ext = path.split('.').pop()?.toLowerCase()
    const langMap: Record<string, string> = {
      'py': 'python',
      'js': 'javascript',
      'ts': 'typescript',
      'jsx': 'javascript',
      'tsx': 'typescript',
      'json': 'json',
      'html': 'html',
      'css': 'css',
      'md': 'markdown',
      'txt': 'plaintext',
    }
    return langMap[ext || ''] || 'plaintext'
  }

  const chatAdapter = useMemo<ChatModelAdapter>(() => {
    const adapter: ChatModelAdapter = {
      async run({ messages, abortSignal }): Promise<ChatModelRunResult> {
        const latestUser = [...messages].reverse().find((m) => m.role === 'user')
        const text = latestUser?.content
          ?.filter((part) => part.type === 'text')
          .map((part) => part.text)
          .join('\n')
          .trim()

        if (!text) {
          return {
            content: [{ type: 'text', text: 'Please enter a message for the agent.' }],
            status: { type: 'incomplete', reason: 'other', error: 'empty-input' },
          }
        }

        // CRITICAL: Auto-save immediately before agent processes the message
        if (dirtyRef.current) {
          console.log('Agent about to process message - triggering immediate auto-save...')
          try {
            const content = editorRef.current?.getValue() ?? fileContents[currentFile] ?? ''
            const data = await writeToStore(currentFile, content)
            setRemoteEtags(prev => ({ ...prev, [data.path]: data.etag }))
            setDirty(false)
            setAutoSaveStatus('Auto-saved before agent')
            setTimeout(() => setAutoSaveStatus(''), 3000)
            console.log('Immediate auto-save completed before agent processing')
          } catch (e) {
            console.error('Immediate auto-save failed before agent processing:', e)
            setAutoSaveStatus('Auto-save failed before agent')
            setTimeout(() => setAutoSaveStatus(''), 3000)
          }
        }

        const userMessage: ModelRequest = {
          kind: 'request',
          parts: [{
            part_kind: 'user-prompt',
            content: text,
            timestamp: new Date().toISOString()
          }],
          instructions: null
        }
        setMessages(prev => [...prev, userMessage])

        try {
          const response = await fetch(`${apiBase}/api/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              conversation_id: conversationId,
              message: text,
              current_file: currentFile
            }),
            signal: abortSignal,
          })

          if (!response.ok) throw new Error(await response.text() || `HTTP ${response.status}`)
          const data = (await response.json()) as ChatResponse
          if (abortSignal.aborted) throw new DOMException('Run aborted', 'AbortError')

          if (data.messages) {
            setMessages(data.messages)
          }

          if (data.editor_content && data.editor_path) {
            setFileContents(prev => ({ ...prev, [data.editor_path!]: data.editor_content! }))
            setCurrentFile(data.editor_path)
            setDirty(false) // Mark as clean since this is the latest content from agent
          } else {
            // Only re-read from store if agent didn't provide updated content
            try {
              const path = data.editor_path ?? currentFile
              const read = await readFromStore(path)
              setRemoteEtags(prev => ({ ...prev, [read.path]: read.etag }))
              setDirty(false)
            } catch { /* ignore */ }
          }

          return {
            content: data.reply ? [{ type: 'text' as const, text: data.reply }] : [],
            status: { type: 'complete', reason: 'stop' },
            metadata: { custom: { usage: data.usage, editorPath: data.editor_path } },
          }
        } catch (error: any) {
          if (abortSignal.aborted || (error instanceof DOMException && error.name === 'AbortError')) {
            throw error
          }
          const message = error?.message ?? 'Unexpected error contacting the backend.'
          return {
            content: [{ type: 'text' as const, text: `Request failed: ${message}` }],
            status: { type: 'incomplete', reason: 'error', error: message },
          }
        }
      },
    }
    return adapter
  }, [conversationId, currentFile])

  const runtime = useLocalRuntime(chatAdapter, useMemo(() => ({ initialMessages: [] as const }), []))

  const fileTree = useMemo(() => buildFileTree(files), [files])

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <div className="layout">
        <aside className="file-list-pane">
          <div className="file-list-header">Explorer</div>
          <div className="file-tree">
            {fileTree.map((node) => (
              <FileTreeItem
                key={node.path}
                node={node}
                currentFile={currentFile}
                onFileClick={switchFile}
              />
            ))}
          </div>
        </aside>

        <section className="editor-pane">
          <div className="file-toolbar">
            <div className="file-toolbar__left">
              <span className="file-path" title={currentFile}>{currentFile}</span>
              {dirty && <span className="badge badge--dirty">unsaved</span>}
              {autoSaveStatus && (
                <span 
                  className="badge badge--autosave" 
                  data-status={autoSaveStatus.includes('before agent') ? 'before-agent' : 'normal'}
                >
                  {autoSaveStatus}
                </span>
              )}
            </div>
            <div className="file-toolbar__right">
              <button className="btn" onClick={onReloadHandler} title="Reload from server">Reload</button>
              <button className="btn btn--primary" onClick={onSave} disabled={!dirty || saving}>
                {saving ? 'Saving…' : 'Save'}
              </button>
            </div>
          </div>
          {error && <div className="error-banner">{error}</div>}
          <div className="editor-content">
            <Editor
              height="100%"
              path={currentFile}
              defaultLanguage={getLanguageFromPath(currentFile)}
              language={getLanguageFromPath(currentFile)}
              value={fileContents[currentFile] || ''}
              theme="vs-dark"
              onChange={onChange}
              onMount={(editor) => { editorRef.current = editor }}
              options={{
                readOnly: false,
                minimap: { enabled: false },
                scrollBeyondLastLine: false,
                fontSize: 14,
              }}
            />
          </div>
        </section>

        <section className="chat-pane">
          <div className="chat-pane__inner">
            <div className="thread-root">
              <div className="thread-viewport">
                {messages.map((message, idx) => (
                  <CustomMessage key={idx} message={message} />
                ))}
                <div ref={messagesEndRef} />
              </div>
            </div>
            <Composer />
          </div>
        </section>
      </div>
    </AssistantRuntimeProvider>
  )
}

export default App
