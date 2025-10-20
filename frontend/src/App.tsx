import { useEffect, useMemo, useRef, useState } from 'react'
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

type ChatResponse = {
  reply: string
  editor_path?: string | null
  editor_content?: string | null
  usage?: Record<string, number>
}

const MessageBubble = () => (
  <MessagePrimitive.Root className="message-row">
    <MessagePrimitive.If user>
      <div className="message-bubble message-bubble--user">
        <MessagePrimitive.Parts />
      </div>
    </MessagePrimitive.If>
    <MessagePrimitive.If assistant>
      <div className="message-bubble message-bubble--assistant">
        <MessagePrimitive.Parts />
      </div>
    </MessagePrimitive.If>
  </MessagePrimitive.Root>
)

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
const DEFAULT_FILE_PATH = 'files/example.py'
const EDITOR_LANGUAGE = 'python'
const POLL_MS = 5000

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

function App() {
  const [conversationId] = useState(() => crypto.randomUUID())
  const [editorPath, setEditorPath] = useState<string>(DEFAULT_FILE_PATH)
  const [editorContent, setEditorContent] = useState<string>('# Loading example.py...\n')
  const [remoteEtag, setRemoteEtag] = useState<string>('')
  const [dirty, setDirty] = useState<boolean>(false)
  const [saving, setSaving] = useState<boolean>(false)
  const [error, setError] = useState<string>('')

  // Keep a ref to avoid racey setStates inside poll
  const contentRef = useRef(editorContent)
  useEffect(() => { contentRef.current = editorContent }, [editorContent])
  const dirtyRef = useRef(dirty)
  useEffect(() => { dirtyRef.current = dirty }, [dirty])

  // Bootstrap initial file through the HTTP file store
  useEffect(() => {
    let cancelled = false
    const run = async () => {
      try {
        const data = await readFromStore(DEFAULT_FILE_PATH)
        if (!cancelled) {
          setEditorPath(data.path)
          setEditorContent(data.content)
          setRemoteEtag(data.etag)
          setDirty(false)
          setError('')
        }
      } catch (e) {
        // Fallback to legacy /api/file loader (startup robustness)
        try {
          const legacy = await fetch(`${apiBase}/api/file?path=${encodeURIComponent(DEFAULT_FILE_PATH)}`)
          if (legacy.ok) {
            const data = (await legacy.json()) as FileResponse
            if (!cancelled) {
              setEditorPath(data.path)
              setEditorContent(data.content)
              setDirty(false)
              setError('')
            }
          } else {
            setError('Failed to load initial file.')
          }
        } catch {
          setError('Failed to load initial file.')
        }
      }
    }
    run()
    return () => { cancelled = true }
  }, [])

  // Lightweight polling: fetch latest content, if it changed and we are NOT dirty, update
  useEffect(() => {
    const id = setInterval(async () => {
      try {
        const data = await readFromStore(editorPath)
        if (data.etag !== remoteEtag && !dirtyRef.current) {
          setEditorContent(data.content)
          setRemoteEtag(data.etag)
        }
      } catch {
        /* ignore */
      }
    }, POLL_MS)
    return () => clearInterval(id)
  }, [editorPath, remoteEtag])

  const onChange: OnChange = (value) => {
    setEditorContent(value ?? '')
    setDirty(true)
  }

  const onSave = async () => {
    setSaving(true)
    setError('')
    try {
      const data = await writeToStore(editorPath, contentRef.current)
      // Overwrite on server → server is source of truth; update etag
      setRemoteEtag(data.etag)
      setDirty(false)
    } catch (e: any) {
      setError(e?.message ?? 'Save failed.')
    } finally {
      setSaving(false)
    }
  }

  const onReload = async () => {
    try {
      const data = await readFromStore(editorPath)
      setEditorContent(data.content)
      setRemoteEtag(data.etag)
      setDirty(false)
      setError('')
    } catch (e: any) {
      setError(e?.message ?? 'Reload failed.')
    }
  }

  // Hook the chat adapter (unchanged except for var deref)
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

        try {
          const response = await fetch(`${apiBase}/api/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ conversation_id: conversationId, message: text }),
            signal: abortSignal,
          })

          if (!response.ok) throw new Error(await response.text() || `HTTP ${response.status}`)
          const data = (await response.json()) as ChatResponse
          if (abortSignal.aborted) throw new DOMException('Run aborted', 'AbortError')

          if (data.editor_content) setEditorContent(data.editor_content)
          if (data.editor_path) setEditorPath(data.editor_path)

          // After agent write, refresh ETag if we can
          try {
            const read = await readFromStore(data.editor_path ?? editorPath)
            setRemoteEtag(read.etag)
            setDirty(false)
          } catch { /* ignore */ }

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
  }, [conversationId, editorPath])

  const runtime = useLocalRuntime(chatAdapter, useMemo(() => ({ initialMessages: [] as const }), []))

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <div className="layout">
        <section className="editor-pane">
          <div className="file-toolbar">
            <div className="file-toolbar__left">
              <span className="file-path" title={editorPath}>{editorPath}</span>
              {dirty && <span className="badge badge--dirty">unsaved</span>}
            </div>
            <div className="file-toolbar__right">
              <button className="btn" onClick={onReload} title="Reload from server">Reload</button>
              <button className="btn btn--primary" onClick={onSave} disabled={!dirty || saving}>
                {saving ? 'Saving…' : 'Save'}
              </button>
            </div>
          </div>
          {error && <div className="error-banner">{error}</div>}
          <div className="editor-content">
            <Editor
              height="100%"
              defaultLanguage={EDITOR_LANGUAGE}
              language={EDITOR_LANGUAGE}
              value={editorContent}
              theme="vs-dark"
              onChange={onChange}
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
            <ThreadPrimitive.Root className="thread-root">
              <ThreadPrimitive.Viewport className="thread-viewport">
                <ThreadPrimitive.Messages components={{ Message: MessageBubble }} />
              </ThreadPrimitive.Viewport>
              <ThreadPrimitive.ScrollToBottom className="scroll-button">
                Scroll to bottom
              </ThreadPrimitive.ScrollToBottom>
            </ThreadPrimitive.Root>
            <Composer />
          </div>
        </section>
      </div>
    </AssistantRuntimeProvider>
  )
}

export default App
